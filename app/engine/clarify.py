"""Context-aware clarification when planning output fails validation."""
import json

import httpx

from ..config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

SLOT_PROMPTS = {
    'order_id': '请提供订单号，例如 ORD000000000001。',
    'refund_reason': '请简单说一下退款原因。',
    'refund_type': '请选择全额退款或部分退款；部分退款请同时说明金额。',
    'refund_amount': '请提供部分退款金额（元）。',
    'ticket_type': '请选择工单类型：播放异常、投诉、退款、账号问题、建议或其他。',
    'issue_desc': '请描述遇到的问题。',
    'book_name': '请告诉我你想查询的专辑名称。',
}


class ClarifyResponder:
    def __init__(self, catalog=None):
        self.catalog = catalog

    def respond(self, error_reason, state, user_message, history=''):
        missing_slot, slot_prompt = self._missing_slot(state)
        if LLM_API_KEY:
            prompt = (
                '你是听书平台客服。当前用户的计划无法通过安全校验。请用一句简短友好的中文澄清问题。'
                '如果缺少槽位，直接请用户提供该槽位；如果是多个意图或流程冲突，给出最多两个明确选项。'
                '不要重复固定菜单，不要声称已执行任何操作。只输出给用户看的回复。'
            )
            context = {
                'user_message': user_message,
                'error_reason': error_reason,
                'current_task': state.get('current_task'),
                'slots': state.get('slots') or {},
                'suspended_stack': state.get('suspended_stack') or [],
                'focused_object': state.get('focused_object'),
                'missing_slot': missing_slot,
                'missing_slot_prompt': slot_prompt,
                'history': (history or '')[-4000:],
            }
            try:
                response = httpx.post(
                    LLM_BASE_URL + '/chat/completions',
                    headers={'Authorization': f'Bearer {LLM_API_KEY}'},
                    json={'model': LLM_MODEL, 'temperature': .2, 'messages': [
                        {'role': 'system', 'content': prompt},
                        {'role': 'user', 'content': json.dumps(context, ensure_ascii=False, default=str)},
                    ]}, timeout=8)
                response.raise_for_status()
                result = response.json()['choices'][0]['message']['content'].strip()
                if result:
                    return result
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
                pass
        return self._fallback(error_reason, state, missing_slot, slot_prompt)

    def _missing_slot(self, state):
        task = state.get('current_task')
        slots = state.get('slots') or {}
        if not task or not self.catalog or task not in self.catalog.flows:
            return None, None
        for step in self.catalog.flows[task]['steps']:
            if step['type'] == 'collect' and not slots.get(step['slot_name']):
                return step['slot_name'], step['template']['text']
        if task == 'refund_request' and slots.get('refund_type') == 'partial' and not slots.get('refund_amount'):
            return 'refund_amount', '请提供部分退款金额（元）。'
        return None, None

    def _fallback(self, error_reason, state, missing_slot, slot_prompt):
        if 'MULTIPLE_TRACKS' in error_reason:
            stack = state.get('suspended_stack') or []
            if stack:
                names = '、'.join(self._flow_name(item.get('task')) for item in stack)
                return f'你同时提到了多个任务。要我先继续挂起的{names}，还是先处理当前的新请求？'
            return '你同时提到了多个任务，请先告诉我最想处理哪一项：查询订单、申请退款，还是提交客服工单？'
        if slot_prompt:
            return slot_prompt
        if missing_slot and missing_slot in SLOT_PROMPTS:
            return SLOT_PROMPTS[missing_slot]
        for slot, prompt in SLOT_PROMPTS.items():
            if slot in error_reason:
                return prompt
        if '流程不存在' in error_reason:
            return '抱歉，我暂时无法处理这个业务请求。你可以换成查询订单、申请退款或提交工单。'
        return '我需要再确认一下你的需求。你是想查询订单状态、申请退款，还是提交客服工单？'

    def _flow_name(self, flow_id):
        if self.catalog and flow_id in self.catalog.flows:
            return self.catalog.flows[flow_id]['name']
        return flow_id or '挂起任务'
