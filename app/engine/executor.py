"""Execute validated TurnPlans against YAML flows and existing business APIs."""
import json
import logging
import re

from jinja2 import Environment, StrictUndefined

from .. import db
from ..intents import order_no
from ..llm import chitchat_reply as llm_chitchat_reply
from .business import answer, execute as execute_business, make_cards, object_ack, resolve_business_objects
from .clarify import ClarifyResponder
from .configuration import FlowCatalog
from .history_builder import HistoryBuilder
from .planner import TurnPlanner, _fallback_chitchat, _is_chitchat, _is_object_ack
from .validator import TurnPlanValidationError, TurnPlanValidator

log = logging.getLogger('listen_cs.engine.executor')
TEMPLATE_ENV = Environment(undefined=StrictUndefined, autoescape=False)
KNOWLEDGE_TO_BUSINESS = {'book_query': 'book_query', 'membership_query': 'membership_query', 'faq': 'faq'}
ACTION_REGISTRY = {
    'action_submit_refund': '_action_submit_refund',
    'action_submit_ticket': '_action_submit_ticket',
    'action_query_order': '_action_query_order',
    'action_query_playback': '_action_query_playback',
    'action_purchase_guide': '_action_purchase_guide',
}


class TurnExecutor:
    def __init__(self, database=db, catalog=None, planner=None, validator=None, clarifier=None):
        self.database = database
        self.catalog = catalog or FlowCatalog()
        self.history_builder = HistoryBuilder(database)
        self.planner = planner or TurnPlanner(self.catalog, self.history_builder)
        self.validator = validator or TurnPlanValidator(self.catalog)
        self.clarifier = clarifier or ClarifyResponder()

    def run(self, session_id, message, objects=None, user_id=None, turn_id=None):
        import time
        import uuid
        started = time.monotonic()
        text = (message or '').strip()
        turn_id = turn_id or uuid.uuid4().hex
        raw_objects = objects or []
        persisted = self.database.get_state(session_id, user_id)
        if persisted is None: raise ValueError('会话任务状态不存在')
        state = self._decode_state(persisted)
        self._migrate_slot_names(state['slots'])
        task, slots, stack = state['current_task'], state['slots'], state['suspended_stack']
        focused = state.get('focused_object')
        resolved = resolve_business_objects(raw_objects, user_id) if raw_objects else []
        incoming = resolved[-1] if resolved else None
        if incoming: focused = incoming
        result = {'message': '', 'source': None, 'cards': [], 'branch': ''}

        # Structured object messages are intercepted before the planner. A matching
        # order object fills the currently locked order_id slot or remains focused.
        current_slot = self._next_slot(task, slots) if task else None
        if incoming and task and current_slot == 'order_id' and incoming.get('type') == 'order':
            value = incoming.get('orderNo') or incoming.get('orderId') or incoming.get('id')
            if value is not None: slots['order_id'] = str(value)
        if incoming and _is_object_ack(text):
            if task and current_slot == 'order_id' and slots.get('order_id'):
                result = self._drive_flow(task, slots, stack, user_id, text)
                result['message'] = object_ack(incoming) + '\n\n' + result['message']
            else:
                result = {'message': object_ack(incoming), 'source': None, 'cards': [], 'branch': 'object_focus'}
            result['intent'] = {'intent': 'object_focus', 'track': 'task', 'confidence': 1.0}
            self._persist(session_id, turn_id, text, resolved, result, task, slots, stack,
                          state['awaiting_resume'], focused if result['branch'] == 'object_focus' else None, None)
            return self._response(turn_id, result, task if result['branch'] == 'object_focus' else result.get('task'),
                                  slots if result['branch'] != 'object_focus' else state['slots'], stack,
                                  state['awaiting_resume'], focused if result['branch'] == 'object_focus' else None)

        # “继续” during an active flow means repeat the current configured
        # prompt; it must never be captured as the value of that slot.
        if task and self._is_resume(text):
            result = self._drive_flow(task, slots, stack, user_id, text)
            result['intent'] = {'intent': task, 'track': 'task', 'confidence': 1.0}
            if result.get('task') is None:
                task, slots = None, {}
            self._persist(session_id, turn_id, text, resolved, result, task, slots, stack,
                          state['awaiting_resume'], focused, None)
            return self._response(turn_id, result, task, slots, stack, state['awaiting_resume'], focused)
        if task and self._is_same_flow_reaffirm(task, text):
            result = self._drive_flow(task, slots, stack, user_id, text)
            result['intent'] = {'intent': task, 'track': 'task', 'confidence': 1.0}
            self._persist(session_id, turn_id, text, resolved, result, task, slots, stack,
                          state['awaiting_resume'], focused, None)
            return self._response(turn_id, result, task, slots, stack, state['awaiting_resume'], focused)

        # Plan every ordinary turn with the full context. Deterministic task
        # guards below may constrain the candidate before validation/execution.
        preplanned = self.planner.plan(session_id, user_id, text, state, focused, resolved)

        # Rule guard for a locked slot: explicit controls, unmistakable small talk,
        # or an unmistakable cross-track request are allowed; all other text is a
        # value for the current slot. The LLM cannot drift this deterministic lock.
        planner_state = dict(state)
        planner_state['slots'] = slots
        try:
            if task and self._is_cancel(text):
                plan = {'track': 'task', 'task_commands': [{'type': 'CancelTask'}], 'knowledge_intents': [], 'chitchat_reply': ''}
            elif task and self._is_resume(text) and stack:
                plan = {'track': 'task', 'task_commands': [{'type': 'ResumeTask', 'task_id': stack[-1]['task']}], 'knowledge_intents': [], 'chitchat_reply': ''}
            elif task and current_slot and _is_chitchat(text):
                plan = preplanned if isinstance(preplanned, dict) and preplanned.get('track') == 'chitchat' else self._chitchat_plan(text)
            elif task and current_slot and not self._is_explicit_route(text):
                # Resolve card slot fill above; avoid treating the card button label as a reason.
                if incoming and current_slot == 'order_id' and slots.get('order_id'):
                    plan = {'track': 'task', 'task_commands': [{'type': 'SetSlots', 'slots': {'order_id': slots['order_id']}}], 'knowledge_intents': [], 'chitchat_reply': ''}
                elif _is_object_ack(text):
                    plan = self._chitchat_plan('')
                else:
                    values = self._normalize_locked_slot(current_slot, text, task)
                    if values:
                        plan = {'track': 'task', 'task_commands': [{'type': 'SetSlots', 'slots': values}], 'knowledge_intents': [], 'chitchat_reply': ''}
                    else:
                        prompt = self._slot_prompt(task, current_slot)
                        result.update({'message': prompt, 'branch': 'slot_prompt',
                                       'intent': {'intent': task, 'track': 'task', 'confidence': 1.0}})
                        self._persist(session_id, turn_id, text, resolved, result, task, slots, stack,
                                      state['awaiting_resume'], focused, None)
                        return self._response(turn_id, result, task, slots, stack, state['awaiting_resume'], focused)
            else:
                plan = preplanned
            plan = self.validator.validate(plan, planner_state)
        except (TurnPlanValidationError, TypeError, AttributeError, KeyError, ValueError) as exc:
            log.warning('invalid TurnPlan session=%s (%s): %s', session_id, type(exc).__name__, exc)
            result['message'] = self.clarifier.respond(text, str(exc), state)
            result['branch'] = 'clarify'
            result['intent'] = {'intent': 'clarify', 'track': 'chitchat', 'confidence': .2}
            self._persist(session_id, turn_id, text, resolved, result, task, slots, stack,
                          state['awaiting_resume'], focused, None)
            return self._response(turn_id, result, task, slots, stack, state['awaiting_resume'], focused)

        if plan['track'] == 'chitchat':
            result['message'] = self._chitchat_reply(text, plan['chitchat_reply'])
            result['branch'] = 'chitchat'
            result['intent'] = {'intent': 'chitchat', 'track': 'chitchat', 'confidence': .95}
            # Chitchat deliberately does not mutate the active task, slots, stack,
            # awaiting flag, or focused object.
            task, slots, stack = state['current_task'], state['slots'], state['suspended_stack']
            focused = incoming or state.get('focused_object')
        elif plan['track'] == 'knowledge':
            intent = plan['knowledge_intents'][0]
            query_text = text
            if intent == 'book_query' and focused and focused.get('type') == 'album':
                title = focused.get('title') or focused.get('albumTitle')
                if title and not any(mark in text for mark in ('《', '「')): query_text = f'《{title}》'
            result['message'] = answer(KNOWLEDGE_TO_BUSINESS[intent], query_text, user_id, focused, slots)
            result['cards'] = make_cards(intent, query_text, user_id, focused, slots)
            result['source'] = 'FAQ知识库' if intent == 'faq' else '业务数据查询'
            result['branch'] = 'knowledge'
            result['intent'] = {'intent': intent, 'track': 'knowledge', 'confidence': .95}
            # A knowledge answer leaves any in-progress task intact.
            focused = None
        else:
            task, slots, stack, focused, awaiting, result = self._execute_commands(
                plan['task_commands'], text, user_id, task, slots, stack, focused,
                state['awaiting_resume'], incoming)
            state['awaiting_resume'] = awaiting
            result.setdefault('intent', {'intent': task or 'task', 'track': 'task', 'confidence': .95})

        self._persist(session_id, turn_id, text, resolved, result, task, slots, stack,
                      state['awaiting_resume'], focused, None)
        log.info('session=%s track=%s branch=%s task=%s slots=%s stack_depth=%d elapsed_ms=%d',
                 session_id, plan['track'], result.get('branch'), task, slots, len(stack),
                 int((time.monotonic() - started) * 1000))
        return self._response(turn_id, result, task, slots, stack, state['awaiting_resume'], focused)

    def _execute_commands(self, commands, text, user_id, task, slots, stack, focused, awaiting, incoming):
        result = {'message': '', 'source': None, 'cards': [], 'branch': 'task'}
        started_flow = False
        for command in commands:
            kind = command['type']
            if kind == 'CancelTask':
                task, slots, stack, focused, awaiting = None, {}, [], None, False
                result['message'] = '已取消当前流程和所有挂起任务。'; result['branch'] = 'cancel'; break
            if kind == 'PauseTask':
                if task: stack.append({'task': task, 'slots': dict(slots)})
                task, slots, focused, awaiting = None, {}, None, False
                continue
            if kind == 'ResumeTask':
                index = next(i for i in range(len(stack) - 1, -1, -1) if stack[i].get('task') == command['task_id'])
                snapshot = stack.pop(index)
                task, slots, focused, awaiting = snapshot['task'], snapshot['slots'], None, False
                continue
            if kind == 'StartFlow':
                if task and task != command['flow_id']:
                    raise TurnPlanValidationError('切换流程前必须先挂起当前任务')
                task, slots, awaiting = command['flow_id'], {}, False
                started_flow = True
                text_order = order_no(text) or (text if re.fullmatch(r'\d{8,20}', text) else None)
                if text_order and self._flow_uses_slot(task, 'order_id'):
                    slots['order_id'] = text_order
                if focused and focused.get('type') == 'order':
                    oid = focused.get('orderNo') or focused.get('orderId') or focused.get('id')
                    if oid is not None and self._flow_uses_slot(task, 'order_id'): slots['order_id'] = str(oid)
                continue
            if kind == 'SetSlots':
                if not task: raise TurnPlanValidationError('没有活动流程可填充槽位')
                slot = self._next_slot(task, slots)
                values = command['slots']
                if slot and slot in values and len(values) == 1:
                    slots[slot] = str(values[slot])
                else:
                    for name, value in values.items():
                        if self._flow_uses_slot(task, name): slots[name] = str(value)

        if task:
            result = self._drive_flow(task, slots, stack, user_id, text)
            # Focus is consumed only when the flow used the object's matching slot.
            if started_flow and incoming and incoming.get('type') == 'order' and slots.get('order_id'):
                focused = None
            elif started_flow and focused and focused.get('type') == 'order' and slots.get('order_id'):
                focused = None
            task = result.get('task')
            if task is None: slots = {}
            if task is None and stack:
                awaiting = True
                result['message'] += '\n\n是否继续之前的流程？回复“继续”或“取消”。'
        elif not result['message']:
            result['message'] = '好的。'; result['branch'] = 'task_control'
        result['task'] = task
        return task, slots, stack, focused, awaiting, result

    def _drive_flow(self, flow_id, slots, stack, user_id, user_text):
        result = {'message': '', 'source': None, 'cards': [], 'branch': 'task'}
        step = self.catalog.first_step(flow_id)
        guard = 0
        while step['type'] != 'end':
            guard += 1
            if guard > len(self.catalog.flows[flow_id]['steps']) + 3:
                raise RuntimeError(f'流程 {flow_id} 可能存在步骤循环')
            if step['type'] == 'start':
                step = self.catalog.step(flow_id, step['next'])
                continue
            if step['type'] == 'collect':
                name = step['slot_name']
                if not slots.get(name):
                    result['message'] = step['template']['text']; result['branch'] = 'slot_prompt'
                    result['task'] = flow_id
                    return result
                target = step['next']
                if isinstance(target, dict):
                    target = target.get(str(slots.get('refund_type')), target.get('default'))
                    if target is None: raise RuntimeError(f'流程 {flow_id} 缺少 next 分支')
                step = self.catalog.step(flow_id, target)
                continue
            if step['type'] == 'action':
                try:
                    action_result = self._run_action(step['action'], slots, user_id, user_text)
                except Exception as exc:
                    log.exception('Python Action failed flow=%s action=%s', flow_id, step['action'])
                    result.update({'message': f'暂时无法完成：{exc}。你已填写的信息仍保留。',
                                   'task': flow_id, 'branch': 'action_error'})
                    return result
                if action_result.get('need_slot'):
                    name = action_result['need_slot']
                    result['message'] = action_result.get('prompt') or self.catalog.slots[name]['description']
                    result['task'] = flow_id
                    result['branch'] = 'slot_prompt'
                    return result
                slots.update(action_result.get('slots', {}))
                if action_result.get('message'): result['message'] = action_result['message']
                result['source'] = action_result.get('source') or result['source']
                result['cards'].extend(action_result.get('cards') or [])
                step = self.catalog.step(flow_id, step['next'])
                continue
            if step['type'] == 'response':
                rendered = TEMPLATE_ENV.from_string(step['template']['text']).render(slots=slots)
                if rendered and rendered != 'None': result['message'] = rendered
                step = self.catalog.step(flow_id, step['next'])
                continue
            raise RuntimeError(f'不支持的流程步骤类型: {step["type"]}')

        result['task'] = None
        result['branch'] = 'task_complete'
        return result

    def _run_action(self, name, slots, user_id, text):
        method_name = ACTION_REGISTRY.get(name)
        if not method_name: raise TurnPlanValidationError(f'未注册的 Python Action: {name}')
        return getattr(self, method_name)(slots, user_id, text)

    @staticmethod
    def _action_submit_refund(slots, user_id, _text):
        if slots.get('refund_type') == 'partial' and not slots.get('refund_amount'):
            return {'need_slot': 'refund_amount', 'prompt': '请提供部分退款金额（元）。'}
        adapted = dict(slots, reason=slots.get('refund_reason', ''))
        message, source = execute_business('refund_request', adapted, user_id)
        return {'slots': {'refund_result': message}, 'message': message, 'source': source}

    @staticmethod
    def _action_submit_ticket(slots, user_id, _text):
        adapted = dict(slots, description=slots.get('issue_desc', ''))
        message, source = execute_business('ticket_submit', adapted, user_id)
        return {'slots': {'ticket_result': message}, 'message': message, 'source': source}

    @staticmethod
    def _action_query_order(slots, user_id, text):
        query_text = slots.get('order_id') or text
        message = answer('order_query', str(query_text), user_id, None, slots)
        cards = make_cards('order_query', str(query_text), user_id, None, slots)
        return {'slots': {'order_result': message}, 'message': message, 'source': '业务数据查询', 'cards': cards}

    @staticmethod
    def _action_query_playback(_slots, user_id, text):
        message = answer('playback_query', text, user_id)
        cards = make_cards('playback_query', text, user_id)
        return {'slots': {'playback_result': message}, 'message': message, 'source': '业务数据查询', 'cards': cards}

    @staticmethod
    def _action_purchase_guide(_slots, _user_id, _text):
        message = '购买请在听书客户端打开对应专辑并选择购买。'
        return {'slots': {'purchase_result': message}, 'message': message}

    def _next_slot(self, task, slots):
        if not task or task not in self.catalog.flows: return None
        for step in self.catalog.flows[task]['steps']:
            if step['type'] == 'collect' and not slots.get(step['slot_name']):
                return step['slot_name']
        if task == 'refund_request' and slots.get('refund_type') == 'partial' and not slots.get('refund_amount'):
            return 'refund_amount'
        return None

    def _flow_uses_slot(self, flow_id, slot_name):
        return any(step.get('slot_name') == slot_name for step in self.catalog.flows[flow_id]['steps']) or (
            flow_id == 'refund_request' and slot_name == 'refund_amount')

    def _normalize_locked_slot(self, slot, text, task):
        value = text.strip()
        if slot == 'order_id':
            result = order_no(value) or (value if re.fullmatch(r'\d{8,20}', value) else None)
            if result: return {'order_id': result}
            if task == 'ticket_submit' and value in {'无', '没有', '无订单'}: return {'order_id': 'none'}
            return {}
        if slot == 'refund_type':
            if any(word in value for word in ('全额', '全部')): return {'refund_type': 'full'}
            if any(word in value for word in ('部分', '一部分')):
                values = {'refund_type': 'partial'}
                amount = re.search(r'(?<!\d)(\d+(?:\.\d{1,2})?)(?!\d)', value)
                if amount: values['refund_amount'] = amount.group(1)
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
        return {slot: value} if value else {}

    def _slot_prompt(self, task, slot):
        for step in self.catalog.flows[task]['steps']:
            if step['type'] == 'collect' and step['slot_name'] == slot:
                return step['template']['text']
        if slot == 'refund_amount': return '请提供部分退款金额（元）。'
        return self.catalog.slots[slot]['description']

    def _decode_state(self, row):
        def decode(value, default):
            if value is None: return default
            return json.loads(value) if isinstance(value, str) else value
        return {'current_task': row.get('current_task'), 'slots': decode(row.get('slots_json'), {}),
                'suspended_stack': decode(row.get('suspended_stack_json'), []),
                'awaiting_resume': bool(row.get('awaiting_resume')),
                'focused_object': decode(row.get('focused_object_json'), None),
                'pending_query': row.get('pending_query')}

    @staticmethod
    def _migrate_slot_names(slots):
        if 'reason' in slots and 'refund_reason' not in slots: slots['refund_reason'] = slots.pop('reason')
        if 'description' in slots and 'issue_desc' not in slots: slots['issue_desc'] = slots.pop('description')

    @staticmethod
    def _is_cancel(text): return text in {'取消', '取消任务', '算了', '停止', '不继续'}
    @staticmethod
    def _is_resume(text): return text in {'继续', '继续退款', '继续工单', '继续刚才的流程', '是'}

    @staticmethod
    def _is_same_flow_reaffirm(task, text):
        if task == 'refund_request': return any(x in text for x in ('我要退款', '申请退款', '我想退款', '退钱'))
        if task == 'ticket_submit': return any(x in text for x in ('提交工单', '我要投诉', '提交投诉'))
        return False

    @staticmethod
    def _is_explicit_route(text):
        return any(x in text for x in ('查订单', '查询订单', '订单状态', '查播放记录', '查询播放记录', '播放进度',
                                       '查专辑', '查询专辑', '会员权益', '查会员', '提交工单', '我要投诉', '我要退款',
                                       '购买', '下单', '退款政策', '退款规则'))

    def _chitchat_plan(self, text):
        reply = llm_chitchat_reply(text) if text else None
        return {'track': 'chitchat', 'task_commands': [], 'knowledge_intents': [],
                'chitchat_reply': reply or _fallback_chitchat(text)}

    def _chitchat_reply(self, text, planned):
        if planned.strip(): return planned.strip()
        return llm_chitchat_reply(text) or _fallback_chitchat(text)

    def _persist(self, session_id, turn_id, text, objects, result, task, slots, stack, awaiting, focused, pending):
        intent = {'track': result.get('branch', 'unknown'), 'planner': 'plan_validate_execute'}
        assistant_metadata = {'intent': intent, 'source': result.get('source'), 'task': task, 'slots': slots,
                              'stack': stack, 'awaiting_resume': awaiting, 'pending_query': pending,
                              'cards': result.get('cards', []), 'focused_object': focused}
        self.database.persist_turn(session_id, turn_id, text, {'objects': objects}, result['message'],
                                   assistant_metadata, task, slots, stack, awaiting, focused, pending)

    @staticmethod
    def _response(turn_id, result, task, slots, stack, awaiting, focused):
        return {'turnId': turn_id, 'message': result['message'],
                'state': {'current_task': task, 'slots': slots, 'suspended_stack': stack,
                          'awaiting_resume': awaiting, 'pending_query': None, 'focused_object': focused},
                'intent': {'track': result.get('branch', 'unknown')}, 'source': result.get('source'),
                'cards': result.get('cards', [])}
