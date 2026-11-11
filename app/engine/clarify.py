"""Friendly clarification when planning output fails validation."""
import httpx
from ..config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL


class ClarifyResponder:
    def respond(self, message, error, state):
        if LLM_API_KEY:
            prompt = ('你是听书平台客服。用户意图计划无法通过校验。请用一句简短友好的中文澄清问题，'
                      '优先在查订单、申请退款、提交工单之间给出选项。不要声称已执行操作。')
            try:
                response = httpx.post(LLM_BASE_URL + '/chat/completions',
                    headers={'Authorization': f'Bearer {LLM_API_KEY}'},
                    json={'model': LLM_MODEL, 'temperature': .3, 'messages': [
                        {'role': 'system', 'content': prompt},
                        {'role': 'user', 'content': f'用户：{message}\n校验原因：{error}\n当前任务：{state.get("current_task")}'}]}, timeout=8)
                response.raise_for_status()
                result = response.json()['choices'][0]['message']['content'].strip()
                if result: return result
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
                pass
        return '我想确认一下：你是想查订单状态、申请退款，还是提交客服工单？'
