import re
RULES={
'refund_request':['退款','退钱','退费'], 'ticket_submit':['工单','投诉','反馈','播放不了','故障'],
'purchase':['购买','想买','我要买','下单','付费购买'],
'order_query':['订单','支付记录','付款记录'], 'playback_query':['听到哪','播放进度','收听记录','播放记录','听到哪里'],
'membership_query':['会员','vip','svip','权益','套餐'], 'book_query':['有声小说','有声书','专辑','多少集','多少章','评分比较高','悬疑'],
'faq':['能退款吗','怎么退款','下载规则','会员能退款','版权'],
# Keep everyday emotional statements out of the unknown/clarification path.
'chitchat':['天气不错','你好','谢谢','在吗','开心','高兴','快乐','兴奋','难过','伤心','不开心','不高兴','烦','累','无聊','焦虑','生气']}

INTENT_TRACK={
    'refund_request':'task','ticket_submit':'task','order_query':'task','playback_query':'task',
    'purchase':'task','book_query':'knowledge','membership_query':'knowledge','faq':'knowledge',
    'chitchat':'chitchat','unknown':'chitchat',
}
def classify_intent(text):
    s=text.lower()
    if any(q in s for q in ('会员能退款吗','会员可以退款吗','会员退款规则','能不能退款','退款规则')):
        return {'intent':'faq','track':'knowledge','confidence':.92,'runner_up':'membership_query','margin':.28}
    ranked=[]
    for intent, words in RULES.items():
        score=sum(1 for w in words if w.lower() in s)
        if score: ranked.append((intent,min(.55+score*.12,.96)))
    ranked.sort(key=lambda x:x[1],reverse=True)
    if not ranked:return {'intent':'unknown','track':'chitchat','confidence':.25,'runner_up':None,'margin':.25}
    top=ranked[0]; runner=ranked[1] if len(ranked)>1 else (None,.0)
    if len(ranked)>1 and top[1]==runner[1]: return {'intent':'unknown','track':'chitchat','confidence':top[1],'runner_up':runner[0],'margin':0}
    return {'intent':top[0],'track':INTENT_TRACK[top[0]],'confidence':top[1],'runner_up':runner[0],'margin':round(top[1]-runner[1],2)}


def classify_intents(text):
    """Return business intents ordered by their first mention in the message.

    This is only used by the deterministic planner fallback. The LLM path is
    free to produce a more nuanced ordered task queue.
    """
    s = text.lower()
    if any(q in s for q in ('会员能退款吗', '会员可以退款吗', '会员退款规则', '能不能退款', '退款规则')):
        return ['faq']
    hits = []
    for intent, words in RULES.items():
        positions = [s.find(word.lower()) for word in words if word.lower() in s]
        if positions:
            hits.append((min(positions), intent))
    hits.sort(key=lambda item: item[0])
    ordered = []
    for _, intent in hits:
        if intent not in ordered:
            ordered.append(intent)
    return ordered


def order_no(text):
    m=re.search(r'\b(?:ORD|O)[A-Z0-9]{6,}\b',text,re.I); return m.group(0) if m else None
