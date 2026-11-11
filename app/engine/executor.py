"""Execute validated TurnPlans against YAML flows and existing business APIs."""
import json
import logging

from jinja2 import Environment, StrictUndefined

from .. import db
from ..audio_client import AudioDataError
from ..llm import chitchat_reply as llm_chitchat_reply
from .business import BusinessRuleError, answer, execute as execute_business, make_cards, resolve_business_objects
from .clarify import ClarifyResponder
from .configuration import FlowCatalog
from .history_builder import HistoryBuilder
from .planner import TurnPlanner, _fallback_chitchat
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
        self.clarifier = clarifier or ClarifyResponder(self.catalog)

    def run(self, session_id, message, objects=None, user_id=None, turn_id=None):
        import time
        import uuid
        started = time.monotonic()
        text = (message or '').strip()
        turn_id = turn_id or uuid.uuid4().hex
        raw_objects = objects or []
        persisted = self.database.get_state(session_id, user_id)
        if persisted is None:
            raise ValueError('会话任务状态不存在')
        state = self._decode_state(persisted)
        self._migrate_slot_names(state['slots'])
        task, slots, stack = state['current_task'], state['slots'], state['suspended_stack']
        pending = state.get('pending_commands') or []
        focused = state.get('focused_object')
        resolved = resolve_business_objects(raw_objects, user_id) if raw_objects else []
        incoming = resolved[-1] if resolved else None
        if incoming:
            focused = incoming
        result = self._new_result()

        planner_state = dict(state)
        planner_state.update({'current_task': task, 'slots': slots, 'suspended_stack': stack,
                              'pending_commands': pending, 'focused_object': focused})
        try:
            plan = self.planner.plan(session_id, user_id, text, planner_state, focused, resolved)
            plan = self.validator.validate(plan, planner_state)
        except (TurnPlanValidationError, TypeError, AttributeError, KeyError, ValueError) as exc:
            log.warning('invalid TurnPlan session=%s (%s): %s', session_id, type(exc).__name__, exc)
            history = self.history_builder.build(session_id, user_id)
            result['message'] = self.clarifier.respond(str(exc), planner_state, text, history)
            result['branch'] = 'clarify'
            result['intent'] = {'intent': 'clarify', 'track': 'chitchat', 'confidence': .2}
            self._persist(session_id, turn_id, text, resolved, result, task, slots, stack,
                          state['awaiting_resume'], focused, pending)
            return self._response(turn_id, result, task, slots, stack, state['awaiting_resume'], focused, pending)

        awaiting = state['awaiting_resume']
        if plan['track'] == 'chitchat':
            result['message'] = self._chitchat_reply(text, plan['chitchat_reply'])
            result['branch'] = 'chitchat'
            result['intent'] = {'intent': 'chitchat', 'track': 'chitchat', 'confidence': .95}
            # Chitchat deliberately does not mutate the active task, slots, stack,
            # awaiting flag, pending queue, or focused object.
        elif plan['track'] == 'knowledge':
            intent = plan['knowledge_intents'][0]
            query_text = text
            if intent == 'book_query' and focused and focused.get('type') == 'album':
                title = focused.get('title') or focused.get('albumTitle')
                if title and not any(mark in text for mark in ('《', '「')):
                    query_text = f'《{title}》'
            result['message'] = answer(KNOWLEDGE_TO_BUSINESS[intent], query_text, user_id, focused, slots)
            result['cards'] = make_cards(intent, query_text, user_id, focused, slots)
            result['source'] = 'FAQ知识库' if intent == 'faq' else '业务数据查询'
            result['branch'] = 'knowledge'
            result['intent'] = {'intent': intent, 'track': 'knowledge', 'confidence': .95}
            # Keep focused_object so the user can continue asking about the card.
        else:
            task, slots, stack, focused, awaiting, pending, result = self._execute_commands(
                plan['task_commands'], text, user_id, task, slots, stack, focused,
                awaiting, pending)
            result.setdefault('intent', {'intent': task or 'task', 'track': 'task', 'confidence': .95})

        self._persist(session_id, turn_id, text, resolved, result, task, slots, stack,
                      awaiting, focused, pending)
        log.info('session=%s track=%s branch=%s task=%s slots=%s stack_depth=%d pending=%d elapsed_ms=%d',
                 session_id, plan['track'], result.get('branch'), task, slots, len(stack), len(pending),
                 int((time.monotonic() - started) * 1000))
        return self._response(turn_id, result, task, slots, stack, awaiting, focused, pending)

    def _execute_commands(self, commands, text, user_id, task, slots, stack, focused, awaiting, pending_commands):
        result = self._new_result()
        queue = list(commands)
        pending = list(pending_commands or [])
        started_flow = False

        while True:
            while queue:
                command = queue.pop(0)
                kind = command['type']

                if kind == 'CancelTask':
                    task, slots, stack, focused, awaiting, pending = None, {}, [], None, False, []
                    queue = []
                    result = self._merge(result, {
                        'message': '已取消当前流程和所有挂起任务。', 'branch': 'cancel'})
                    break

                if kind == 'AbandonTask':
                    task_id = command.get('task_id')
                    name = self._flow_name(task_id) if task_id else '挂起任务'
                    stack = []
                    awaiting = False
                    result = self._merge(result, {
                        'message': f'已放弃挂起的任务“{name}”，挂起队列已清空。', 'branch': 'abandon'})
                    continue

                if kind == 'PauseTask':
                    if task:
                        stack.append({'task': task, 'slots': dict(slots), 'focused_object': focused})
                    task, slots, focused, awaiting = None, {}, None, False
                    continue

                if kind == 'ResumeTask':
                    index = next((i for i in range(len(stack) - 1, -1, -1)
                                  if stack[i].get('task') == command['task_id']), None)
                    if index is None:
                        log.warning('忽略无效 ResumeTask: %s', command['task_id'])
                        continue
                    snapshot = stack.pop(index)
                    task = snapshot['task']
                    slots = dict(snapshot.get('slots') or {})
                    focused = snapshot.get('focused_object')
                    awaiting = False
                    continue

                if kind == 'StartFlow':
                    flow_id = command['flow_id']
                    if task and task != flow_id:
                        # Defensive fallback: the validator should have required
                        # PauseTask, but never discard the previous flow's slots.
                        stack.append({'task': task, 'slots': dict(slots), 'focused_object': focused})
                        log.warning('StartFlow %s while %s active; auto-suspending previous task', flow_id, task)
                        task, slots, focused = None, {}, None
                    if task != flow_id:
                        task, slots, focused, awaiting = flow_id, {}, None, False
                    while queue and queue[0]['type'] == 'SetSlots':
                        for name, value in queue.pop(0)['slots'].items():
                            slots[name] = str(value)
                    started_flow = True
                    flow_result = self._drive_flow(task, slots, stack, user_id, text)
                    result = self._merge(result, flow_result)
                    if flow_result.get('reset'):
                        task, slots, focused, pending = None, {}, None, []
                        queue = []
                        break
                    if flow_result.get('task'):
                        task = flow_result['task']
                        pending = queue
                        queue = []
                        break
                    task, slots = None, {}
                    continue

                if kind == 'SetSlots':
                    if not task:
                        log.warning('忽略无活动任务的 SetSlots: %s', command.get('slots'))
                        continue
                    for name, value in command['slots'].items():
                        slots[name] = str(value)
                    continue

            if task and not started_flow:
                flow_result = self._drive_flow(task, slots, stack, user_id, text)
                result = self._merge(result, flow_result)
                if flow_result.get('reset'):
                    task, slots, focused, pending = None, {}, None, []
                    queue = []
                elif flow_result.get('task'):
                    task = flow_result['task']
                else:
                    task, slots = None, {}

            if task is None and pending:
                queue = pending
                pending = []
                started_flow = False
                continue
            break

        if task is None:
            if stack:
                awaiting = True
                result['message'] = self._append_message(result['message'], self._resume_prompt(stack))
            else:
                awaiting = False
        else:
            awaiting = False
        if not result['message']:
            result['message'] = '好的。'
            result['branch'] = 'task_control'
        result['task'] = task
        return task, slots, stack, focused, awaiting, pending, result

    def _drive_flow(self, flow_id, slots, stack, user_id, user_text):
        result = self._new_result()
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
                    result['message'] = step['template']['text']
                    result['branch'] = 'slot_prompt'
                    result['task'] = flow_id
                    return result
                target = step['next']
                if isinstance(target, dict):
                    target = target.get(str(slots.get('refund_type')), target.get('default'))
                    if target is None:
                        raise RuntimeError(f'流程 {flow_id} 缺少 next 分支')
                step = self.catalog.step(flow_id, target)
                continue
            if step['type'] == 'action':
                try:
                    action_result = self._run_action(step['action'], slots, user_id, user_text)
                except BusinessRuleError as exc:
                    result.update({'message': f'无法完成：{exc}', 'task': None,
                                   'branch': 'action_error_reset', 'reset': True})
                    return result
                except AudioDataError as exc:
                    if exc.retryable:
                        result.update({'message': f'业务系统暂时不可用：{exc}。你已填写的信息仍保留，请稍后重试。',
                                       'task': flow_id, 'branch': 'action_error_retry'})
                    else:
                        result.update({'message': f'无法完成：{exc}', 'task': None,
                                       'branch': 'action_error_reset', 'reset': True})
                    return result
                except Exception as exc:
                    log.exception('Python Action failed flow=%s action=%s', flow_id, step['action'])
                    result.update({'message': f'暂时无法完成：{exc}。你已填写的信息仍保留，请稍后重试。',
                                   'task': flow_id, 'branch': 'action_error'})
                    return result
                if action_result.get('need_slot'):
                    name = action_result['need_slot']
                    result['message'] = action_result.get('prompt') or self.catalog.slots[name]['description']
                    result['task'] = flow_id
                    result['branch'] = 'slot_prompt'
                    return result
                slots.update(action_result.get('slots', {}))
                if action_result.get('message'):
                    result['message'] = action_result['message']
                result['source'] = action_result.get('source') or result['source']
                result['cards'].extend(action_result.get('cards') or [])
                step = self.catalog.step(flow_id, step['next'])
                continue
            if step['type'] == 'response':
                rendered = TEMPLATE_ENV.from_string(step['template']['text']).render(slots=slots)
                if rendered and rendered != 'None':
                    result['message'] = rendered
                step = self.catalog.step(flow_id, step['next'])
                continue
            raise RuntimeError(f'不支持的流程步骤类型: {step["type"]}')

        result['task'] = None
        result['branch'] = 'task_complete'
        return result

    def _run_action(self, name, slots, user_id, text):
        method_name = ACTION_REGISTRY.get(name)
        if not method_name:
            raise TurnPlanValidationError(f'未注册的 Python Action: {name}')
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

    def _flow_name(self, flow_id):
        if flow_id in self.catalog.flows:
            return self.catalog.flows[flow_id]['name']
        return flow_id or '挂起任务'

    def _resume_prompt(self, stack):
        names = []
        for item in stack:
            name = self._flow_name(item.get('task'))
            count = len(item.get('slots') or {})
            names.append(f'{name}（已填 {count} 项）')
        return ('当前任务已结束。挂起中的任务：' + '、'.join(names) +
                '。回复“继续 任务名”恢复，或回复“放弃 任务名”结束并清理挂起任务。')

    @staticmethod
    def _new_result():
        return {'message': '', 'source': None, 'cards': [], 'branch': 'task'}

    @staticmethod
    def _merge(target, source):
        if not source:
            return target
        message = (source.get('message') or '').strip()
        if message:
            target['message'] = f"{target.get('message', '')}\n\n{message}".strip() if target.get('message') else message
        target['cards'] = (target.get('cards') or []) + (source.get('cards') or [])
        target['source'] = source.get('source') or target.get('source')
        if source.get('branch'):
            target['branch'] = source['branch']
        if source.get('reset'):
            target['reset'] = True
        return target

    @staticmethod
    def _append_message(message, extra):
        message = (message or '').strip()
        extra = (extra or '').strip()
        if not message:
            return extra
        if not extra:
            return message
        return f'{message}\n\n{extra}'

    def _decode_state(self, row):
        def decode(value, default):
            if value is None:
                return default
            return json.loads(value) if isinstance(value, str) else value
        return {'current_task': row.get('current_task'), 'slots': decode(row.get('slots_json'), {}),
                'suspended_stack': decode(row.get('suspended_stack_json'), []),
                'awaiting_resume': bool(row.get('awaiting_resume')),
                'focused_object': decode(row.get('focused_object_json'), None),
                'pending_commands': decode(row.get('pending_commands_json'), []),
                'pending_query': row.get('pending_query')}

    @staticmethod
    def _migrate_slot_names(slots):
        if 'reason' in slots and 'refund_reason' not in slots:
            slots['refund_reason'] = slots.pop('reason')
        if 'description' in slots and 'issue_desc' not in slots:
            slots['issue_desc'] = slots.pop('description')

    def _chitchat_reply(self, text, planned):
        if planned.strip():
            return planned.strip()
        return llm_chitchat_reply(text) or _fallback_chitchat(text)

    def _persist(self, session_id, turn_id, text, objects, result, task, slots, stack, awaiting, focused, pending_commands):
        intent = {'track': result.get('branch', 'unknown'), 'planner': 'plan_validate_execute'}
        assistant_metadata = {'intent': intent, 'source': result.get('source'), 'task': task, 'slots': slots,
                              'stack': stack, 'awaiting_resume': awaiting,
                              'pending_commands': pending_commands,
                              'cards': result.get('cards', []), 'focused_object': focused}
        self.database.persist_turn(session_id, turn_id, text, {'objects': objects}, result['message'],
                                   assistant_metadata, task, slots, stack, awaiting, focused, None,
                                   pending_commands)

    @staticmethod
    def _response(turn_id, result, task, slots, stack, awaiting, focused, pending_commands):
        return {'turnId': turn_id, 'message': result['message'],
                'state': {'current_task': task, 'slots': slots, 'suspended_stack': stack,
                          'awaiting_resume': awaiting, 'pending_query': None,
                          'pending_commands': pending_commands, 'focused_object': focused},
                'intent': {'track': result.get('branch', 'unknown')}, 'source': result.get('source'),
                'cards': result.get('cards', [])}
