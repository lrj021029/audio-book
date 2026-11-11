"""LLM-backed TurnPlanner with a deterministic safe fallback."""
import json
import logging
import re
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from ..intents import classify_intent, classify_intents, order_no
from .business import object_ack
from .history_builder import render_object_context, render_objects_context, render_user_message

log = logging.getLogger('listen_cs.engine.planner')
TEMPLATE_DIR = Path(__file__).parent / 'templates'
ENV = Environment(loader=FileSystemLoader(TEMPLATE_DIR), undefined=StrictUndefined, autoescape=False)
INTENT_TO_FLOW = {'refund_request': 'refund_request', 'ticket_submit': 'ticket_submit',
                  'order_query': 'order_query', 'playback_query': 'playback_query', 'purchase': 'purchase'}
CANCEL_WORDS = {'取消', '取消任务', '算了', '停止', '不继续', '不继续了', '不要了'}
RESUME_WORDS = {'继续', '继续退款', '继续工单', '继续刚才的流程', '是', '恢复'}
OBJECT_ACK_WORDS = {'请查看我附加的业务对象', '请查看附加的业务对象', '查看我附加的业务对象'}


class TurnPlanner:
    def __init__(self, catalog, history_builder):
        self.catalog = catalog
        self.history_builder = history_builder

    def plan(self, session_id, user_id, message, state, focused_object, objects=None):
        objects = objects or []
        context = {
            'history': self.history_builder.build(session_id, user_id),
            'user_message': render_user_message(message, objects),
            'focused_object_context': render_object_context(focused_object) if focused_object else 'null',
            'attached_objects_context': render_objects_context(objects),
            'task_state_json': json.dumps({
                'current_task': state.get('current_task'), 'slots': state.get('slots', {}),
                'suspended_stack': state.get('suspended_stack', []), 'awaiting_resume': state.get('awaiting_resume', False),
                'pending_commands': state.get('pending_commands', []),
            }, ensure_ascii=False),
            'flows_json': json.dumps(self.catalog.flow_summaries(), ensure_ascii=False),
            'knowledge_intents_json': json.dumps(self.catalog.knowledge_intents(), ensure_ascii=False),
        }
        if LLM_API_KEY:
            try:
                prompt = ENV.get_template('turn_plan.jinja2').render(**context)
                response = httpx.post(
                    LLM_BASE_URL + '/chat/completions',
                    headers={'Authorization': f'Bearer {LLM_API_KEY}'},
                    json={'model': LLM_MODEL, 'temperature': 0,
                          'messages': [{'role': 'system', 'content': prompt},
                                       {'role': 'user', 'content': context['user_message']}],
                          'response_format': {'type': 'json_object'}}, timeout=12)
                response.raise_for_status()
                content = response.json()['choices'][0]['message']['content'].strip()
                match = re.search(r'\{.*\}', content, re.S)
                try:
                    proposed = json.loads(match.group(0) if match else content)
                except ValueError:
                    log.warning('TurnPlanner returned malformed JSON; using deterministic plan')
                    return self._fallback(message, state, focused_object, objects)
                if not isinstance(proposed, dict) or proposed.get('track') not in {'task', 'knowledge', 'chitchat'}:
                    log.warning('TurnPlanner returned a plan without a valid track; using deterministic plan')
                    return self._fallback(message, state, focused_object, objects)
                return self._repair(proposed, message, state, focused_object, objects)
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                log.warning('TurnPlanner falling back to deterministic plan (%s)', type(exc).__name__)
        return self._fallback(message, state, focused_object, objects)

    def _repair(self, plan, message, state, focused, objects):
        """Fill an empty model SetSlots from the locked slot and attached card.

        This is a planner-side repair, not an executor-side intent override. It
        only fills a value for the slot the active YAML flow is already asking
        for; it never switches flows or guesses chitchat.
        """
        if objects and not state.get('current_task') and _is_object_ack(message):
            return _chitchat(object_ack(objects[-1]))
        if plan.get('track') != 'task':
            return plan
        commands = plan.get('task_commands')
        if not isinstance(commands, list):
            return plan
        task = state.get('current_task')
        slots = state.get('slots') or {}
        if not task:
            return self._repair_new_flow(plan, commands, message, objects)
        current_slot = _next_slot(self.catalog, task, slots) if task else None
        if not current_slot:
            return plan
        values = {}
        if current_slot == 'order_id':
            order = next((item for item in objects if item.get('type') == 'order'), None)
            if not order and focused and focused.get('type') == 'order':
                order = focused
            if order:
                ref = _order_ref(order)
                if ref:
                    values = {'order_id': str(ref)}
        if not values:
            values = _slot_values(current_slot, message, task)
        if not values:
            return plan

        pending = state.get('pending_commands') or []
        pending_starts = {item.get('flow_id') for item in pending
                          if isinstance(item, dict) and item.get('type') == 'StartFlow'}
        start_flows = {command.get('flow_id') for command in commands
                       if isinstance(command, dict) and command.get('type') == 'StartFlow'}
        if start_flows and start_flows <= pending_starts:
            # The executor drains pending_commands after the current flow ends.
            # Never let the model jump the queue while the locked slot is being
            # filled; keep only the slot value for the active flow.
            merged = dict(values)
            for command in commands:
                if (isinstance(command, dict) and command.get('type') == 'SetSlots'
                        and isinstance(command.get('slots'), dict)):
                    merged.update({name: value for name, value in command['slots'].items()
                                   if value is not None})
            plan['task_commands'] = [{'type': 'SetSlots', 'slots': merged}]
            return plan

        for command in commands:
            if isinstance(command, dict) and command.get('type') == 'SetSlots':
                command['slots'] = values
                return plan
        # Preserve an explicit switch, but fill the locked slot before pausing.
        plan['task_commands'] = [{'type': 'SetSlots', 'slots': values}] + commands
        return plan

    def _repair_new_flow(self, plan, commands, message, objects):
        """Attach an explicit order reference to the first flow that needs it.

        Models occasionally start the right flow but omit the order number that
        is already present in the message or attached card. Only insert a value
        when the plan has no non-empty SetSlots yet.
        """
        for command in commands:
            if (isinstance(command, dict) and command.get('type') == 'SetSlots'
                    and isinstance(command.get('slots'), dict) and command['slots']):
                return plan
        order = next((item for item in objects if item.get('type') == 'order'), None)
        reference = _order_ref(order) if order else None
        if not reference:
            text = message.strip()
            reference = order_no(text) or (text if re.fullmatch(r'\d{8,20}', text) else None)
        if not reference:
            return plan
        order_flows = {'refund_request', 'order_query', 'ticket_submit'}
        for index, command in enumerate(commands):
            if (isinstance(command, dict) and command.get('type') == 'StartFlow'
                    and command.get('flow_id') in order_flows):
                commands.insert(index + 1, {'type': 'SetSlots', 'slots': {'order_id': str(reference)}})
                return plan
        return plan

    def _fallback(self, message, state, focused, objects):
        text = message.strip()
        task = state.get('current_task')
        stack = state.get('suspended_stack') or []
        slots = state.get('slots') or {}
        if text in CANCEL_WORDS:
            return _task({'type': 'CancelTask'})
        if stack and _is_abandon(text):
            return _task({'type': 'AbandonTask', 'task_id': _target_task(text, stack, self.catalog)})
        if stack and _is_resume(text):
            return _task({'type': 'ResumeTask', 'task_id': _target_task(text, stack, self.catalog)})

        rule = classify_intent(text)
        current_slot = _next_slot(self.catalog, task, slots) if task else None
        order = next((o for o in objects if o.get('type') == 'order'), None)

        # Slot lock: while a flow is collecting a slot, ordinary text is a value
        # for that slot. The planner does not guess chitchat from keyword lists.
        if task and current_slot:
            if _is_strong_other_intent(text, rule, task):
                other_flow = INTENT_TO_FLOW.get(rule['intent'])
                if other_flow and other_flow != task:
                    return _task({'type': 'PauseTask'}, {'type': 'StartFlow', 'flow_id': other_flow})
                if rule['intent'] in self.catalog.knowledge_intents():
                    return _knowledge(rule['intent'])
            if order and current_slot == 'order_id':
                value = _order_ref(order)
                if value:
                    return _task({'type': 'SetSlots', 'slots': {'order_id': str(value)}})
            values = _slot_values(current_slot, text, task)
            if values:
                return _task({'type': 'SetSlots', 'slots': values})
            return _chitchat(_slot_hint(self.catalog, task, current_slot))

        if objects and (rule['intent'] == 'unknown' or _is_object_ack(text)):
            return _chitchat(object_ack(objects[-1]))

        # Questions about the focused card must be answered from its real fields.
        if focused and focused.get('type') == 'album' and any(
            word in text for word in ('评分', '评价', '简介', '作者', '主播', '多少集', '讲什么', '内容')
        ):
            return _knowledge('book_query')
        if focused and focused.get('type') == 'order' and any(
            word in text for word in ('状态', '进度', '商品', '能退', '可以退', '退款')
        ):
            if any(word in text for word in ('能退', '可以退', '退款')):
                return _chitchat(_focused_order_reply(focused))
            return _task({'type': 'StartFlow', 'flow_id': 'order_query'})

        intents = [item for item in classify_intents(text) if item in INTENT_TO_FLOW]
        if len(intents) > 1:
            commands = []
            if task:
                commands.append({'type': 'PauseTask'})
            commands.extend({'type': 'StartFlow', 'flow_id': INTENT_TO_FLOW[item]} for item in intents)
            return _task(*commands)

        intent = rule['intent']
        if intent in INTENT_TO_FLOW:
            commands = []
            if task and intent != task:
                commands.append({'type': 'PauseTask'})
            flow_id = INTENT_TO_FLOW[intent]
            commands.append({'type': 'StartFlow', 'flow_id': flow_id})
            order_ref = order_no(text) or (text if re.fullmatch(r'\d{8,20}', text) else None)
            if order_ref and flow_id in {'refund_request', 'order_query', 'ticket_submit'}:
                commands.append({'type': 'SetSlots', 'slots': {'order_id': order_ref}})
            elif order and flow_id in {'refund_request', 'order_query', 'ticket_submit'}:
                value = _order_ref(order)
                if value:
                    commands.append({'type': 'SetSlots', 'slots': {'order_id': str(value)}})
            return _task(*commands)
        if intent in self.catalog.knowledge_intents():
            return _knowledge(intent)
        if intent in {'unknown', 'chitchat'}:
            return _chitchat(_fallback_chitchat(text))
        return _chitchat('你是想查询订单状态，还是发起退款或提交工单？')


def _next_slot(catalog, flow_id, slots):
    if flow_id not in catalog.flows:
        return None
    for step in catalog.flows[flow_id]['steps']:
        if step['type'] == 'collect' and not slots.get(step['slot_name']):
            return step['slot_name']
    if flow_id == 'refund_request' and slots.get('refund_type') == 'partial' and not slots.get('refund_amount'):
        return 'refund_amount'
    return None


def _slot_values(slot, text, task):
    value = text.strip()
    if not value:
        return {}
    if slot == 'order_id':
        result = order_no(value) or (value if re.fullmatch(r'\d{8,20}', value) else None)
        if result:
            return {'order_id': result}
        if task == 'ticket_submit' and value in {'无', '没有', '无订单'}:
            return {'order_id': 'none'}
        return {}
    if slot == 'refund_type':
        if any(word in value for word in ('全额', '全部')):
            return {'refund_type': 'full'}
        if any(word in value for word in ('部分', '一部分')):
            values = {'refund_type': 'partial'}
            amount = re.search(r'(?<!\d)(\d+(?:\.\d{1,2})?)(?!\d)', value)
            if amount:
                values['refund_amount'] = amount.group(1)
            return values
        return {}
    if slot == 'refund_amount':
        amount = re.search(r'(?<!\d)(\d+(?:\.\d{1,2})?)(?!\d)', value)
        return {'refund_amount': amount.group(1)} if amount else {}
    if slot == 'ticket_type':
        mapping = (('播放', 'usage_feedback'), ('投诉', 'copyright_complaint'), ('退款', 'payment_issue'),
                   ('账号', 'account_issue'), ('建议', 'feature_feedback'), ('其他', 'other'))
        kind = next((result for word, result in mapping if word in value), None)
        return {'ticket_type': kind} if kind else {}
    return {slot: value}


def _slot_hint(catalog, task, slot):
    if task in catalog.flows:
        for step in catalog.flows[task]['steps']:
            if step['type'] == 'collect' and step['slot_name'] == slot:
                return step['template']['text']
    if slot == 'refund_amount':
        return '请提供部分退款金额（元）。'
    return catalog.slots.get(slot, {}).get('description') or '请继续补充当前流程需要的信息。'


def _order_ref(obj):
    return obj.get('orderNo') or obj.get('orderId') or obj.get('id')


def _is_resume(text):
    return text in RESUME_WORDS or text.startswith('继续')


def _is_abandon(text):
    return text.startswith('放弃') or text in {'不要了', '不继续了'}


def _target_task(text, stack, catalog):
    for item in reversed(stack):
        task = item.get('task')
        name = catalog.flows.get(task, {}).get('name') or task
        if task and (task in text or (name and name in text)):
            return task
    return stack[-1]['task']


def _is_object_ack(text):
    return text in OBJECT_ACK_WORDS


def _is_strong_other_intent(text, route, current_task):
    explicit = ('查订单', '查询订单', '订单状态', '查播放记录', '查询播放记录', '播放进度',
                '查专辑', '查询专辑', '查会员', '查询会员', '提交工单', '我要投诉', '我要退款', '购买', '下单')
    return route.get('intent') != current_task and route.get('confidence', 0) >= .55 and any(x in text for x in explicit)


def _focused_order_reply(focused):
    status = focused.get('orderStatus') or focused.get('status') or '未知'
    if status == 'paid':
        return f'这个订单当前状态是 {status}，如果符合退款规则，我可以继续帮你申请退款。'
    return f'这个订单当前状态是 {status}，目前不适合直接申请退款。你可以先查询订单详情或提交客服工单。'


def _fallback_chitchat(text):
    if '笑话' in text:
        return '给你讲一个：书为什么不怕冷？因为它总有很多“章节”陪着。希望你笑一下！'
    if any(x in text for x in ('不开心', '难过', '伤心', '焦虑', '烦', '生气')):
        return '听起来你现在有些不好受。愿意的话，可以跟我说说发生了什么。'
    if any(x in text for x in ('开心', '高兴', '快乐', '兴奋')):
        return '真好，听起来你现在心情很不错！愿这份开心陪你度过今天。'
    if '谢谢' in text:
        return '不客气，能帮上忙就好。'
    if any(x in text for x in ('你好', '在吗')):
        return '你好，我在呢。'
    return '当然可以。希望你这会儿轻松一点；想继续处理刚才的事情时，告诉我“继续”就好。'


def _task(*commands):
    return {'track': 'task', 'task_commands': list(commands), 'knowledge_intents': [], 'chitchat_reply': ''}


def _knowledge(intent):
    return {'track': 'knowledge', 'task_commands': [], 'knowledge_intents': [intent], 'chitchat_reply': ''}


def _chitchat(reply):
    return {'track': 'chitchat', 'task_commands': [], 'knowledge_intents': [], 'chitchat_reply': reply}
