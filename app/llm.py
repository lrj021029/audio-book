import json
import logging
import re
import httpx
from .config import LLM_API_KEY,LLM_BASE_URL,LLM_MODEL
log=logging.getLogger('listen_cs.llm')

VALID_TRACKS={'task','knowledge','chitchat'}
VALID_INTENTS={'refund_request','ticket_submit','order_query','playback_query','purchase','book_query','membership_query','faq','chitchat','unknown'}

def plan_turn(text: str, fallback: dict) -> dict:
    """Ask the configured model for a constrained route; reject malformed or unsafe plans."""
    if not LLM_API_KEY:
        return fallback
    prompt=(
        '将用户输入路由为一个 JSON 对象，只输出 JSON：'
        '{"track":"task|knowledge|chitchat","intent":"refund_request|ticket_submit|order_query|playback_query|purchase|book_query|membership_query|faq|chitchat|unknown"}。'
        '订单查询、播放记录、退款、工单、购买属于 task；专辑、会员权益、规则属于 knowledge；'
        '寒暄、情绪表达、与业务无关的话属于 chitchat。不要执行动作，也不要提取业务数据。'
    )
    try:
        response=httpx.post(LLM_BASE_URL+'/chat/completions',headers={'Authorization':f'Bearer {LLM_API_KEY}'},json={
            'model':LLM_MODEL,'temperature':0,'messages':[{'role':'system','content':prompt},{'role':'user','content':text}],
        },timeout=8)
        response.raise_for_status()
        content=response.json()['choices'][0]['message']['content'].strip()
        match=re.search(r'\{.*?\}',content,re.S)
        proposed=json.loads(match.group(0)) if match else {}
        track=proposed.get('track'); intent=proposed.get('intent')
        if track not in VALID_TRACKS or intent not in VALID_INTENTS:
            return fallback
        expected={'task' if intent in {'refund_request','ticket_submit','order_query','playback_query','purchase'} else 'knowledge' if intent in {'book_query','membership_query','faq'} else 'chitchat'}
        if track not in expected:
            return fallback
        # Explicit deterministic business matches take precedence over a model route.
        if fallback.get('intent') not in {'unknown','chitchat'} and fallback.get('confidence',0)>=.55:
            return fallback
        return {'intent':intent,'track':track,'confidence':.8,'runner_up':None,'margin':.8,'planner':'llm'}
    except (httpx.HTTPError,KeyError,IndexError,TypeError,ValueError) as exc:
        log.warning('turn planner unavailable; using rules (%s)',type(exc).__name__)
        return fallback

def chitchat_reply(text: str) -> str | None:
    if not LLM_API_KEY:
        return None
    try:
        response=httpx.post(LLM_BASE_URL+'/chat/completions',headers={'Authorization':f'Bearer {LLM_API_KEY}'},json={
            'model':LLM_MODEL,'temperature':0.7,'messages':[
                {'role':'system','content':'你是听书平台的友好客服。先自然回应用户的情绪或闲聊，保持简短、真诚，不要假装拥有个人经历，不要使用固定菜单或兜底话术；结尾可轻柔地提示你也能帮助处理听书相关问题。'},
                {'role':'user','content':text},
            ],
        },timeout=10)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip() or None
    except (httpx.HTTPError,KeyError,IndexError,TypeError,ValueError) as exc:
        log.warning('chitchat generation unavailable (%s)',type(exc).__name__)
        return None

def rag_reply(question: str, passage: str) -> str | None:
    if not LLM_API_KEY:return None
    try:
        response=httpx.post(LLM_BASE_URL+'/chat/completions',headers={'Authorization':f'Bearer {LLM_API_KEY}'},json={'model':LLM_MODEL,'temperature':0.2,'messages':[{'role':'system','content':'只根据提供的 FAQ 原文用简洁中文回答用户问题。不得补充原文没有的规则。'},{'role':'user','content':f'用户问题：{question}\n\nFAQ 原文：\n{passage}'}]},timeout=10)
        response.raise_for_status(); data=response.json()
        return data['choices'][0]['message']['content'].strip() or None
    except (httpx.HTTPError,KeyError,IndexError,TypeError,ValueError) as exc:
        log.warning('RAG LLM unavailable; using source text (%s)',type(exc).__name__)
        return None
