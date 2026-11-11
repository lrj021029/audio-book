"""LLM-backed TurnPlanner with a deterministic safe fallback."""
import json
import logging
import re
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from ..intents import classify_intent, order_no
from .business import resolve_business_objects

log = logging.getLogger('listen_cs.engine.planner')
TEMPLATE_DIR = Path(__file__).parent / 'templates'
ENV = Environment(loader=FileSystemLoader(TEMPLATE_DIR), undefined=StrictUndefined, autoescape=False)
CHITCHAT_MARKERS = ('笑话', '开心', '高兴', '快乐', '兴奋', '难过', '伤心', '谢谢', '你好', '在吗', '无聊', '累', '天气')
INTENT_TO_FLOW = {'refund_request': 'refund_request', 'ticket_submit': 'ticket_submit',
                  'order_query': 'order_query', 'playback_query': 'playback_query', 'purchase': 'purchase'}


class TurnPlanner:
    def __init__(self, catalog, history_builder):
        self.catalog = catalog
        self.history_builder = history_builder

    def plan(self, session_id, user_id, message, state, focused_object, objects=None):
        context = {
            'history': self.history_builder.build(session_id, user_id),
            'user_message': message,
            'focused_object_json': json.dumps(focused_object, ensure_ascii=False),
            'task_state_json': json.dumps({
                'current_task': state.get('current_task'), 'slots': state.get('slots', {}),
                'suspended_stack': state.get('suspended_stack', []), 'awaiting_resume': state.get('awaiting_resume', False),
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
                                       {'role': 'user', 'content': message}],
                          'response_format': {'type': 'json_object'}}, timeout=12)
                response.raise_for_status()
                content = response.json()['choices'][0]['message']['content'].strip()
                match = re.search(r'\{.*\}', content, re.S)
                try:
                    proposed = json.loads(match.group(0) if match else content)
                except ValueError:
                    # Preserve malformed model output so TurnPlanValidator can
                    # reject it and route the turn through ClarifyResponder.
                    return {'track': None, 'task_commands': [], 'knowledge_intents': [], 'chitchat_reply': ''}
                # Preserve clear user commands when a model emits contradictory
                # slot instructions (for example SetSlots with slots=null).
                # The candidate is still validated by TurnPlanValidator; this
                # lexical guard only chooses the deterministic, schema-valid plan.
                if _has_explicit_action(message):
                    return self._fallback(message, state, focused_object, objects or [])
                return proposed
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
                log.warning('TurnPlanner falling back to deterministic plan (%s)', type(exc).__name__)
        return self._fallback(message, state, focused_object, objects or [])

    def _fallback(self, message, state, focused, objects):
        text = message.strip()
        task = state.get('current_task')
        stack = state.get('suspended_stack') or []
        slots = state.get('slots') or {}
        if text in {'取消', '取消任务', '算了', '停止', '不继续'}:
            return _task({'type': 'CancelTask'})
        if text in {'继续', '继续退款', '继续工单', '继续刚才的流程', '是'} and stack:
            return _task({'type': 'ResumeTask', 'task_id': stack[-1]['task']})

        rule = classify_intent(text)
        if focused and focused.get('type') == 'order' and any(
            phrase in text for phrase in ('查状态', '查询状态', '订单情况', '订单进度')
        ):
            rule = {'intent': 'order_query', 'track': 'task', 'confidence': .98,
                    'runner_up': None, 'margin': .98}
        current_slot = _next_slot(self.catalog, task, slots) if task else None
        # An attached order is offered to the currently requested order slot before routing.
        order = next((o for o in objects if o.get('type') == 'order'), None)
        if task and current_slot:
            if _is_chitchat(text):
                return _chitchat(_fallback_chitchat(text))
            if order and current_slot == 'order_id':
                value = order.get('orderNo') or order.get('orderId') or order.get('id')
                return _task({'type': 'SetSlots', 'slots': {'order_id': str(value)}})
            if _is_strong_other_intent(text, rule, task):
                other_flow = INTENT_TO_FLOW.get(rule['intent'])
                if other_flow and other_flow != task:
                    return _task({'type': 'PauseTask'}, {'type': 'StartFlow', 'flow_id': other_flow})
                if rule['intent'] in self.catalog.knowledge_intents():
                    return _knowledge(rule['intent'])
            slot = current_slot
            if slot == 'refund_type':
                value = 'full' if any(k in text for k in ('全额', '全部')) else 'partial' if any(k in text for k in ('部分', '一部分')) else None
                extra = {}
                if value == 'partial':
                    amount = re.search(r'(?<!\d)(\d+(?:\.\d{1,2})?)(?!\d)', text)
                    if amount: extra['refund_amount'] = amount.group(1)
                return _task({'type': 'SetSlots', 'slots': {'refund_type': value, **extra}}) if value else _chitchat('请回复“全额退款”或“部分退款”。')
            if slot == 'ticket_type':
                mappings = [('播放', 'usage_feedback'), ('投诉', 'copyright_complaint'), ('退款', 'payment_issue'),
                            ('账号', 'account_issue'), ('建议', 'feature_feedback'), ('其他', 'other')]
                value = next((v for k, v in mappings if k in text), None)
                return _task({'type': 'SetSlots', 'slots': {'ticket_type': value}}) if value else _chitchat('请从播放异常、投诉、退款、账号问题、建议或其他中选择一种工单类型。')
            if slot == 'order_id':
                value = order_no(text) or (text if re.fullmatch(r'\d{8,20}', text) else None)
                if value: return _task({'type': 'SetSlots', 'slots': {'order_id': value}})
            if slot == 'refund_amount':
                amount = re.search(r'(?<!\d)(\d+(?:\.\d{1,2})?)(?!\d)', text)
                if amount: return _task({'type': 'SetSlots', 'slots': {'refund_amount': amount.group(1)}})
            if slot == 'order_id' and task == 'ticket_submit' and text in {'无', '没有', '无订单'}:
                return _task({'type': 'SetSlots', 'slots': {'order_id': 'none'}})
            if text:
                return _task({'type': 'SetSlots', 'slots': {slot: text}})

        if objects and (rule['intent'] == 'unknown' or _is_object_ack(text)):
            return _chitchat('我收到附加的业务对象了。你想查询它的信息、进度，还是相关订单？')
        intent = rule['intent']
        if intent in INTENT_TO_FLOW:
            commands = []
            if task and intent != task:
                commands.append({'type': 'PauseTask'})
            commands.append({'type': 'StartFlow', 'flow_id': INTENT_TO_FLOW[intent]})
            # The executor itself applies a matching focused order to order_id.
            return _task(*commands)
        if intent in self.catalog.knowledge_intents(): return _knowledge(intent)
        if _is_chitchat(text) or intent in {'unknown', 'chitchat'}:
            return _chitchat(_fallback_chitchat(text))
        return _chitchat('你是想查询订单状态，还是发起退款或提交工单？')


def _next_slot(catalog, flow_id, slots):
    if flow_id not in catalog.flows: return None
    for step in catalog.flows[flow_id]['steps']:
        if step['type'] == 'collect' and not slots.get(step['slot_name']):
            return step['slot_name']
    if flow_id == 'refund_request' and slots.get('refund_type') == 'partial' and not slots.get('refund_amount'):
        return 'refund_amount'
    return None


def _is_chitchat(text): return any(marker in text for marker in CHITCHAT_MARKERS)


def _has_explicit_action(text):
    return any(term in text for term in (
        '我要退款', '申请退款', '我想退款', '退钱', '我要提交工单', '提交工单', '我要投诉',
        '查询订单', '查订单', '订单状态', '查状态', '查询状态', '查询播放记录', '查播放记录', '播放进度',
        '查专辑', '查询专辑', '查会员权益', '查询会员权益', '我要购买', '购买', '下单',
        '退款规则', '退款政策'))


def _is_object_ack(text): return text in {'请查看我附加的业务对象', '请查看附加的业务对象', '查看我附加的业务对象'}


def _is_strong_other_intent(text, route, current_task):
    explicit = ('查订单', '查询订单', '订单状态', '查播放记录', '查询播放记录', '播放进度',
                '查专辑', '查询专辑', '查会员', '查询会员', '提交工单', '我要投诉', '我要退款', '购买', '下单')
    return route.get('intent') != current_task and route.get('confidence', 0) >= .55 and any(x in text for x in explicit)


def _fallback_chitchat(text):
    if '笑话' in text:
        return '给你讲一个：书为什么不怕冷？因为它总有很多“章节”陪着。希望你笑一下！'
    if any(x in text for x in ('不开心', '难过', '伤心', '焦虑', '烦', '生气')):
        return '听起来你现在有些不好受。愿意的话，可以跟我说说发生了什么。'
    if any(x in text for x in ('开心', '高兴', '快乐', '兴奋')):
        return '真好，听起来你现在心情很不错！愿这份开心陪你度过今天。'
    if '谢谢' in text: return '不客气，能帮上忙就好。'
    if any(x in text for x in ('你好', '在吗')): return '你好，我在呢。'
    return '当然可以。希望你这会儿轻松一点；想继续处理刚才的事情时，告诉我“继续”就好。'


def _task(*commands):
    return {'track': 'task', 'task_commands': list(commands), 'knowledge_intents': [], 'chitchat_reply': ''}


def _knowledge(intent):
    return {'track': 'knowledge', 'task_commands': [], 'knowledge_intents': [intent], 'chitchat_reply': ''}


def _chitchat(reply):
    return {'track': 'chitchat', 'task_commands': [], 'knowledge_intents': [], 'chitchat_reply': reply}
