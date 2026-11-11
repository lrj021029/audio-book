import copy
import json
import unittest
from unittest.mock import patch

from app.audio_client import AudioDataError
from app.engine.business import BusinessRuleError
from app.engine.clarify import ClarifyResponder
from app.engine.configuration import FlowCatalog
from app.engine.executor import TurnExecutor
from app.engine.history_builder import HistoryBuilder, render_user_message
from app.engine.planner import TurnPlanner
from app.engine.validator import MULTIPLE_TRACKS, TurnPlanValidationError, TurnPlanValidator


class FakeDB:
    def __init__(self, state=None):
        self.state = {
            'current_task': None,
            'slots': {},
            'suspended_stack': [],
            'awaiting_resume': False,
            'focused_object': None,
            'pending_commands': [],
        }
        if state:
            self.state.update(copy.deepcopy(state))
        self.turns = []

    def get_state(self, session_id, user_id):
        state = self.state
        return {
            'current_task': state['current_task'],
            'slots_json': json.dumps(state['slots'], ensure_ascii=False),
            'suspended_stack_json': json.dumps(state['suspended_stack'], ensure_ascii=False),
            'awaiting_resume': int(state['awaiting_resume']),
            'focused_object_json': json.dumps(state['focused_object'], ensure_ascii=False) if state['focused_object'] else None,
            'pending_query': None,
            'pending_commands_json': json.dumps(state['pending_commands'], ensure_ascii=False),
        }

    def history(self, session_id, user_id):
        return []

    def persist_turn(self, session_id, turn_id, user_text, user_metadata, assistant_text, assistant_metadata,
                     task, slots, stack, awaiting_resume, focused_object, pending_query=None,
                     pending_commands=None):
        self.state = {
            'current_task': task,
            'slots': copy.deepcopy(slots),
            'suspended_stack': copy.deepcopy(stack),
            'awaiting_resume': bool(awaiting_resume),
            'focused_object': copy.deepcopy(focused_object),
            'pending_commands': copy.deepcopy(pending_commands or []),
        }
        self.turns.append({
            'turn_id': turn_id, 'user': user_text, 'assistant': assistant_text,
            'metadata': assistant_metadata,
        })


class StubPlanner:
    def __init__(self, plans):
        self.plans = list(plans)

    def plan(self, *args, **kwargs):
        if self.plans:
            return self.plans.pop(0)
        return {'track': 'chitchat', 'task_commands': [], 'knowledge_intents': [],
                'chitchat_reply': '好的。'}


class StubClarifier:
    def respond(self, error_reason, state, user_message, history=''):
        return f'CLARIFY:{error_reason}'


def task_plan(*commands):
    return {'track': 'task', 'task_commands': list(commands), 'knowledge_intents': [], 'chitchat_reply': ''}


def set_slots(**slots):
    return task_plan({'type': 'SetSlots', 'slots': slots})


def start_flow(flow_id):
    return {'type': 'StartFlow', 'flow_id': flow_id}


def build_executor(db, plans):
    return TurnExecutor(database=db, catalog=FlowCatalog(), planner=StubPlanner(plans),
                        clarifier=StubClarifier())


class ExecutorRefactorTests(unittest.TestCase):
    def setUp(self):
        self.catalog = FlowCatalog()

    def test_card_then_slot_fill_is_not_interrupted(self):
        db = FakeDB({'current_task': 'refund_request', 'slots': {}})
        executor = TurnExecutor(database=db, catalog=self.catalog,
                                clarifier=StubClarifier())
        card = {'type': 'order', 'orderNo': 'ORD000000000001', 'orderStatus': 'paid',
                'title': 'ORD000000000001', 'payableAmount': 39.0, 'currencyCode': 'CNY'}
        with patch('app.engine.planner.LLM_API_KEY', ''), \
             patch('app.engine.executor.resolve_business_objects', side_effect=lambda objs, uid: objs):
            first = executor.run('s1', '请查看我附加的业务对象', [card])
            second = executor.run('s1', '书的内容和预期不符')

        self.assertIn('退款原因', first['message'])
        self.assertEqual(first['state']['slots']['order_id'], 'ORD000000000001')
        self.assertNotIn('收到订单', first['message'])
        self.assertIn('全额退款或部分退款', second['message'])
        self.assertEqual(second['state']['slots']['refund_reason'], '书的内容和预期不符')

    def test_business_error_resets_state(self):
        slots = {'order_id': 'ORD000000000001', 'refund_reason': '不需要了', 'refund_type': 'full'}
        db = FakeDB({'current_task': 'refund_request', 'slots': slots})
        executor = build_executor(db, [task_plan()])
        with patch.object(executor, '_run_action',
                          side_effect=BusinessRuleError('订单状态为 cancelled，不能申请退款')):
            result = executor.run('s1', '确认退款')

        self.assertIsNone(result['state']['current_task'])
        self.assertEqual(result['state']['slots'], {})
        self.assertIn('无法完成', result['message'])
        self.assertEqual(result['intent']['track'], 'action_error_reset')

    def test_timeout_keeps_slots(self):
        slots = {'order_id': 'ORD000000000001', 'refund_reason': '不需要了', 'refund_type': 'full'}
        db = FakeDB({'current_task': 'refund_request', 'slots': slots})
        executor = build_executor(db, [task_plan()])
        with patch.object(executor, '_run_action',
                          side_effect=AudioDataError('业务数据请求超时', retryable=True)):
            result = executor.run('s1', '确认退款')

        self.assertEqual(result['state']['current_task'], 'refund_request')
        self.assertEqual(result['state']['slots'], slots)
        self.assertIn('仍保留', result['message'])

    def test_multi_intent_queue_drains_after_current_flow(self):
        db = FakeDB()
        planner = StubPlanner([
            task_plan(start_flow('refund_request'), start_flow('ticket_submit')),
            set_slots(order_id='ORD000000000001'),
            set_slots(refund_reason='不需要了'),
            set_slots(refund_type='full'),
        ])
        executor = TurnExecutor(database=db, catalog=self.catalog, planner=planner,
                                clarifier=StubClarifier())
        with patch.object(executor, '_run_action', return_value={
            'slots': {'refund_result': '退款申请已提交'}, 'message': '退款申请已提交', 'source': 'test'}):
            first = executor.run('s1', '我先退款再提交工单')
            executor.run('s1', 'ORD000000000001')
            executor.run('s1', '不需要了')
            final = executor.run('s1', '全额退款')

        self.assertIn('订单号', first['message'])
        self.assertEqual(len(first['state']['pending_commands']), 1)
        self.assertEqual(first['state']['current_task'], 'refund_request')
        self.assertIn('退款申请已提交', final['message'])
        self.assertIn('工单类型', final['message'])
        self.assertEqual(final['state']['current_task'], 'ticket_submit')
        self.assertEqual(final['state']['pending_commands'], [])

    def test_abandon_clears_suspended_stack(self):
        db = FakeDB({
            'current_task': None,
            'suspended_stack': [{'task': 'refund_request', 'slots': {'order_id': 'ORD1'}}],
            'awaiting_resume': True,
        })
        executor = build_executor(db, [task_plan({'type': 'AbandonTask', 'task_id': 'refund_request'})])
        result = executor.run('s1', '放弃退款')

        self.assertEqual(result['state']['suspended_stack'], [])
        self.assertFalse(result['state']['awaiting_resume'])
        self.assertIn('挂起队列已清空', result['message'])


class ValidatorRefactorTests(unittest.TestCase):
    def setUp(self):
        self.catalog = FlowCatalog()
        self.validator = TurnPlanValidator(self.catalog)

    def test_unknown_slot_is_warned_and_dropped(self):
        plan = set_slots(bogus='x', order_id='ORD000000000001')
        normalized = self.validator.validate(plan, {'current_task': 'refund_request', 'suspended_stack': []})
        self.assertEqual(normalized['task_commands'], [
            {'type': 'SetSlots', 'slots': {'order_id': 'ORD000000000001'}}
        ])

    def test_only_unknown_slot_keeps_empty_task_commands(self):
        plan = set_slots(bogus='x')
        normalized = self.validator.validate(plan, {'current_task': 'refund_request', 'suspended_stack': []})
        self.assertEqual(normalized['track'], 'task')
        self.assertEqual(normalized['task_commands'], [])

    def test_multiple_tracks_is_fatal(self):
        plan = task_plan(start_flow('refund_request'), {'type': 'ResumeTask', 'task_id': 'ticket_submit'})
        with self.assertRaisesRegex(TurnPlanValidationError, MULTIPLE_TRACKS):
            self.validator.validate(plan, {'current_task': None, 'suspended_stack': [{'task': 'ticket_submit'}]})

    def test_starting_other_flow_without_pause_is_multiple_tracks(self):
        plan = task_plan(start_flow('ticket_submit'))
        with self.assertRaisesRegex(TurnPlanValidationError, MULTIPLE_TRACKS):
            self.validator.validate(plan, {'current_task': 'refund_request', 'suspended_stack': []})

    def test_consecutive_start_flow_is_allowed_as_queue(self):
        plan = task_plan(start_flow('refund_request'), start_flow('ticket_submit'))
        normalized = self.validator.validate(plan, {'current_task': None, 'suspended_stack': []})
        self.assertEqual([item['flow_id'] for item in normalized['task_commands']],
                         ['refund_request', 'ticket_submit'])


class PlannerRepairTests(unittest.TestCase):
    def setUp(self):
        self.catalog = FlowCatalog()
        self.planner = TurnPlanner(self.catalog, HistoryBuilder(None))

    def test_pending_queue_is_not_started_while_slot_is_locked(self):
        state = {
            'current_task': 'refund_request', 'slots': {},
            'suspended_stack': [],
            'pending_commands': [{'type': 'StartFlow', 'flow_id': 'ticket_submit'}],
        }
        plan = task_plan(
            {'type': 'SetSlots', 'slots': None},
            {'type': 'PauseTask'},
            start_flow('ticket_submit'),
        )
        repaired = self.planner._repair(plan, 'ORD000000000001', state, None, [])
        self.assertEqual(repaired['task_commands'], [
            {'type': 'SetSlots', 'slots': {'order_id': 'ORD000000000001'}},
        ])

    def test_explicit_switch_fills_locked_slot_before_pausing(self):
        state = {
            'current_task': 'refund_request', 'slots': {},
            'suspended_stack': [], 'pending_commands': [],
        }
        plan = task_plan({'type': 'PauseTask'}, start_flow('ticket_submit'))
        repaired = self.planner._repair(plan, 'ORD000000000001', state, None, [])
        self.assertEqual(repaired['task_commands'], [
            {'type': 'SetSlots', 'slots': {'order_id': 'ORD000000000001'}},
            {'type': 'PauseTask'},
            start_flow('ticket_submit'),
        ])

    def test_object_ack_is_repaired_when_model_answers_generically(self):
        state = {
            'current_task': None, 'slots': {}, 'suspended_stack': [],
            'pending_commands': [],
        }
        plan = {'track': 'chitchat', 'task_commands': [], 'knowledge_intents': [],
                'chitchat_reply': '请把对象发给我。'}
        order = {'type': 'order', 'orderNo': 'ORD000000000001'}
        repaired = self.planner._repair(plan, '请查看我附加的业务对象', state, None, [order])
        self.assertEqual(repaired['track'], 'chitchat')
        self.assertIn('ORD000000000001', repaired['chitchat_reply'])

    def test_object_ack_overrides_task_plan_without_active_task(self):
        state = {
            'current_task': None, 'slots': {}, 'suspended_stack': [],
            'pending_commands': [],
        }
        plan = task_plan({'type': 'SetSlots', 'slots': None})
        album = {'type': 'album', 'title': '宝贝听我说', 'rating': 9.88}
        repaired = self.planner._repair(plan, '请查看我附加的业务对象', state, album, [album])
        self.assertEqual(repaired['track'], 'chitchat')
        self.assertIn('宝贝听我说', repaired['chitchat_reply'])

    def test_new_flow_repair_attaches_order_number_after_start_flow(self):
        state = {
            'current_task': None, 'slots': {}, 'suspended_stack': [],
            'pending_commands': [],
        }
        plan = task_plan(start_flow('order_query'), {'type': 'PauseTask'},
                         start_flow('ticket_submit'))
        repaired = self.planner._repair(
            plan, '先查订单 ORD000000000001，再提交工单', state, None, [])
        self.assertEqual(repaired['task_commands'], [
            start_flow('order_query'),
            {'type': 'SetSlots', 'slots': {'order_id': 'ORD000000000001'}},
            {'type': 'PauseTask'},
            start_flow('ticket_submit'),
        ])


class ContextTests(unittest.TestCase):
    def test_render_user_message_expands_card_fields(self):
        rendered = render_user_message('这个订单能退吗', [{
            'type': 'order', 'orderNo': 'ORD123', 'orderStatus': 'cancelled', 'payableAmount': 39,
        }])
        self.assertIn('订单卡片', rendered)
        self.assertIn('"order_id": "ORD123"', rendered)
        self.assertIn('"status": "cancelled"', rendered)

    def test_clarify_uses_current_missing_slot(self):
        catalog = FlowCatalog()
        responder = ClarifyResponder(catalog)
        with patch('app.engine.clarify.LLM_API_KEY', ''):
            reply = responder.respond('SetSlots 字段不合法', {
                'current_task': 'refund_request', 'slots': {}, 'suspended_stack': []
            }, '我要退款', '')
        self.assertIn('订单号', reply)

    def test_clarify_offers_choice_when_multiple_tracks(self):
        catalog = FlowCatalog()
        responder = ClarifyResponder(catalog)
        with patch('app.engine.clarify.LLM_API_KEY', ''):
            reply = responder.respond('MULTIPLE_TRACKS: 当前任务尚未挂起', {
                'current_task': None,
                'slots': {},
                'suspended_stack': [{'task': 'refund_request', 'slots': {'order_id': 'ORD1'}}],
            }, '先查订单再退款', '')
        self.assertIn('退款申请', reply)
        self.assertIn('继续', reply)


if __name__ == '__main__':
    unittest.main()
