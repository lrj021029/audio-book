import logging, re
from ..audio_client import AudioDataClient
from ..intents import order_no
from ..retrieval import retrieve
from ..llm import rag_reply
log=logging.getLogger('listen_cs.engine.actions')

def normalize_object(obj):
    if not isinstance(obj,dict):return None
    return {**obj,'type':str(obj.get('type') or 'unknown'),'id':obj.get('id'),'title':obj.get('title') or str(obj.get('id') or '未命名对象'),'subtitle':obj.get('subtitle') or '', 'cover_url':obj.get('cover_url') or obj.get('coverUrl')}

def resolve_business_objects(objects,user_id=None):
    resolved=[]
    for raw in objects:
        obj=normalize_object(raw)
        if not obj: continue
        try:
            client=AudioDataClient(user_id)
            raw_id=obj.get('id') or obj.get('albumId') or obj.get('orderId') or obj.get('orderNo')
            if obj['type']=='album':
                album_id=int(obj.get('albumId') or raw_id)
                detail=client.get(f'/api/v1/albums/{album_id}')
                album=detail.get('album',{}); narrators=detail.get('narrators') or []; authors=detail.get('authors') or []
                narrator=narrators[0].get('narratorName') if narrators else None
                author=authors[0].get('authorName') if authors else None
                cover=album.get('coverUrl')
                obj={**obj,'type':'album','id':album.get('albumId',album_id),'albumId':album.get('albumId',album_id),
                     'title':album.get('albumTitle') or obj['title'],'subtitle':narrator or author or f"{album.get('trackCount','')} 集",
                     'cover_url':cover,'coverUrl':cover,'trackCount':album.get('trackCount'),
                     'rating':album.get('ratingScore'),'summary':album.get('summary')}
            elif obj['type']=='order':
                order_id=obj.get('orderId'); order_no=obj.get('orderNo')
                if not order_id and str(raw_id or '').isdigit(): order_id=int(raw_id)
                if not order_id:
                    order_no=order_no or str(raw_id or '')
                    rows=client.get('/api/v1/orders',pageSize=100).get('list',[])
                    match=next((r for r in rows if r.get('orderNo')==order_no),None)
                    order_id=match.get('orderId') if match else None
                if order_id:
                    detail=client.get(f'/api/v1/orders/{int(order_id)}')
                    order=detail.get('order',{}); items=detail.get('items') or []
                    order_no=order.get('orderNo') or order_no
                    item_name=items[0].get('itemName') if items else None
                    subtitle=' · '.join(x for x in (order.get('orderStatus'),item_name) if x)
                    obj={**obj,'type':'order','id':order.get('orderId',int(order_id)),'orderId':order.get('orderId',int(order_id)),
                         'orderNo':order_no,'title':order_no or obj['title'],'subtitle':subtitle,
                         'orderStatus':order.get('orderStatus'),'payableAmount':order.get('payableAmount'),
                         'currencyCode':order.get('currencyCode'),'items':items,'cover_url':None}
        except Exception as exc:
            log.warning('business object hydration failed type=%s (%s)',obj['type'],type(exc).__name__)
        resolved.append(obj)
    return resolved

def object_ack(obj):
    if not obj:return '我收到你附加的业务对象了。你希望我帮你查询什么？'
    title=obj.get('title') or obj.get('orderNo') or obj.get('id') or '未命名对象'
    if obj.get('type')=='album':
        return f'好的，我已收到专辑《{title}》。你是想查询它的专辑信息、收听进度，还是相关订单？'
    if obj.get('type')=='order':
        return f'好的，我已收到订单 {title}。你想查询订单状态，还是申请退款？'
    return f'好的，我已收到你附加的业务对象“{title}”。你希望我帮你查询或处理什么？'

def chitchat_reply(text):
    """Natural contextual fallback used only when the optional LLM is unavailable."""
    if any(word in text for word in ('不开心','不高兴','难过','伤心','焦虑','烦','生气')):
        return '听起来你现在有些不好受。愿意的话，可以跟我说说发生了什么。'
    if any(word in text for word in ('开心','高兴','快乐','兴奋')):
        return '真好，听起来你现在心情很不错！愿这份开心陪你度过今天。'
    if '累' in text:
        return '辛苦了，忙了一阵的话不妨歇一会儿。'
    if '无聊' in text:
        return '想找点乐子的话，我可以帮你挑一部有声书。'
    if any(word in text for word in ('你好','在吗')):
        return '你好，我在呢。想聊聊天，或查专辑、订单和收听进度都可以。'
    if '谢谢' in text:
        return '不客气，能帮上忙就好。'
    return '是呀，适合戴上耳机听一会儿。需要查书、订单或播放进度时告诉我就好。'

def make_cards(intent,text,user_id,focused_object=None,slots=None):
    slots=slots or {}
    c=AudioDataClient(user_id)
    try:
        if intent=='book_query':
            m=re.search(r'[《「](.+?)[》」]',text)
            if m:
                data=c.get('/api/v1/search',keyword=m.group(1),searchType='all',channelId=1,pageSize=5)
                rows=data.get('list',[])
            else:
                data=c.get('/api/v1/albums',albumType='audiobook',sortBy='rating',pageSize=5)
                rows=data.get('list',[])
            out=[]
            for row in rows[:3]:
                album_data=row.get('album',row); album_id=album_data.get('albumId') or row.get('albumId')
                if not album_id: continue
                d=c.get(f'/api/v1/albums/{album_id}'); a=d.get('album',{})
                narrator=(d.get('narrators') or [{}])[0].get('narratorName'); author=(d.get('authors') or [{}])[0].get('authorName'); cover=a.get('coverUrl') or a.get('cover_url')
                out.append({'type':'album','id':album_id,'albumId':album_id,'title':a.get('albumTitle') or row.get('title'),'subtitle':narrator or author or f"{a.get('trackCount','')} 集",'cover_url':cover,'coverUrl':cover,'narrator':narrator,'author':author,'rating':a.get('ratingScore'),'trackCount':a.get('trackCount'),'summary':a.get('summary')})
            return out
        if intent=='order_query':
            target=focused_object or {}
            order_id=target.get('orderId') or (target.get('id') if target.get('type')=='order' else None)
            order_ref=target.get('orderNo') or slots.get('order_id') or order_no(text)
            if not order_id and order_ref:
                rows=c.get('/api/v1/orders',pageSize=100).get('list',[])
                match=next((x for x in rows if x.get('orderNo')==order_ref or str(x.get('orderId'))==str(order_ref)),None)
                order_id=match.get('orderId') if match else None
            if order_id:
                detail=c.get(f'/api/v1/orders/{int(order_id)}'); order=detail.get('order',{}); items=detail.get('items') or []
                item_name=items[0].get('itemName') if items else None
                return [{'type':'order','id':order.get('orderId'),'orderId':order.get('orderId'),'orderNo':order.get('orderNo'),'title':order.get('orderNo'),'subtitle':' · '.join(x for x in (order.get('orderStatus'),item_name) if x),'orderStatus':order.get('orderStatus'),'payableAmount':order.get('payableAmount'),'currencyCode':order.get('currencyCode'),'cover_url':None}]
        if intent=='playback_query':
            rows=c.get('/api/v1/listening-progress',pageSize=1).get('list',[])
            if not rows:return []
            row=rows[0]
            try: album=c.get(f"/api/v1/albums/{int(row.get('albumId'))}").get('album',{})
            except Exception: album={}
            return [{'type':'playback','id':row.get('albumId'),'albumId':row.get('albumId'),'title':row.get('albumTitle'),'subtitle':row.get('trackTitle') or '最近收听','trackTitle':row.get('trackTitle'),'positionSeconds':row.get('positionSeconds'),'durationSeconds':row.get('durationSeconds'),'lastPlayedAt':row.get('lastPlayedAt'),'cover_url':album.get('coverUrl'),'coverUrl':album.get('coverUrl')}]
    except Exception: log.exception('business card lookup failed intent=%s',intent)
    return []

def answer(intent,text,user_id=None,focused_object=None,slots=None):
    slots=slots or {}
    c=AudioDataClient(user_id)
    try:
        if intent=='book_query':
            m=re.search(r'[《「](.+?)[》」]',text); title=m.group(1) if m else ''
            if title:
                data=c.get('/api/v1/search',keyword=title,searchType='all',channelId=1,pageSize=5); rows=data.get('list',[])
                if rows:
                    album_id=rows[0].get('album',{}).get('albumId')
                    detail=c.get(f'/api/v1/albums/{album_id}') if album_id else {}
                    album=detail.get('album',{}); narrators=detail.get('narrators',[])
                    return f"《{album.get('albumTitle',rows[0].get('title'))}》共 {album.get('trackCount',0)} 集，主播 {narrators[0].get('narratorName','未提供') if narrators else '未提供'}，总时长 {album.get('totalDurationSeconds',0)//60} 分钟。\n简介：{album.get('summary','暂无简介')}\n来源：业务数据（audio_album、audio_track）"
                return f'暂未在当前样本中检索到《{title}》。来源：业务数据（audio_album）'
            tag_id=None
            tags=c.get('/api/v1/tags',tagType='genre').get('tags',[])
            def walk(nodes):
                for node in nodes:
                    if '悬疑' in node.get('tagName',''): return node.get('tagId')
                    found=walk(node.get('children',[]))
                    if found:return found
                return None
            tag_id=walk(tags)
            data=c.get('/api/v1/albums',albumType='audiobook',sortBy='rating',pageSize=5,**({'tagId':tag_id} if tag_id else {}))
            lines=[]
            for item in data.get('list',[])[:3]:
                detail=c.get(f"/api/v1/albums/{item['albumId']}"); album=detail.get('album',{})
                authors=detail.get('authors',[]); narrators=detail.get('narrators',[])
                summary=(album.get('summary') or '').replace('\n',' ')
                lines.append(f"• {item.get('albumTitle')}｜作者 {authors[0].get('authorName','未提供') if authors else '未提供'}｜主播 {narrators[0].get('narratorName','未提供') if narrators else '未提供'}｜评分 {item.get('ratingScore')}｜{summary[:64]}")
            if not re.search(r'[《「](.+?)[》」]',text):
                return '按评分找到以下专辑，作者、主播和简介见卡片。\n来源：业务数据（audio_album、album_author_rel、album_narrator_rel）'
            return '专辑信息：\n'+'\n'.join(lines)+'\n来源：业务数据（audio_album、album_author_rel、album_narrator_rel）'
        if intent=='order_query':
            no=order_no(text); numeric=re.search(r'\b\d{1,20}\b',text)
            focus=focused_object or {}
            fallback=focus.get('orderNo') or slots.get('order_id') or (focus.get('orderId') if focus.get('type')=='order' else None) or (focus.get('id') if focus.get('type')=='order' else None)
            if not no and not numeric and not fallback:return '请提供订单号，例如 ORD000000000001。'
            key=no or (numeric.group(0) if numeric else str(fallback)); data=c.get('/api/v1/orders',pageSize=100)
            row=next((x for x in data.get('list',[]) if x.get('orderNo')==key or str(x.get('orderId'))==key),None)
            order_id=row['orderId'] if row else (int(key[3:]) if key.startswith('ORD') and key[3:].isdigit() else int(key) if key.isdigit() else None)
            if order_id is None:return f'暂未查到订单 {key}。请确认订单号或当前用户。'
            detail=c.get(f'/api/v1/orders/{order_id}'); o=detail['order']
            if o.get('orderNo') != key and str(o.get('orderId')) != key:return f'暂未查到订单 {key}。请确认订单号或当前用户。'
            return f"订单 {o['orderNo']}：状态 {o['orderStatus']}，商品 {', '.join(i['itemName'] for i in detail.get('items',[]))}，金额 {o['payableAmount']} {o['currencyCode']}，支付时间 {o.get('paidAt') or '暂无'}。\n来源：业务数据（content_order、payment_record）"
        if intent=='playback_query':
            data=c.get('/api/v1/listening-progress',pageSize=1); rows=data.get('list',[])
            if not rows:return '暂时没有找到收听记录。来源：业务数据（listening_progress）'
            p=rows[0]; percent=round(p['positionSeconds']*100/max(p['durationSeconds'],1)); return f"最近收听《{p['albumTitle']}》章节《{p['trackTitle']}》，进度 {percent}%，时间 {p['lastPlayedAt']}。\n来源：业务数据（listening_progress）"
        if intent=='membership_query':
            d=c.get('/api/v1/vip-plans'); return '会员套餐：\n'+'\n'.join(f"• {p['planName']}：{p['salePriceAmount']} {p['currencyCode']} / {p['durationDays']}天" for p in d.get('plans',[]))+'\n来源：业务数据（vip_plan、member_account）'
        if intent=='faq':
            retrieved=retrieve(text)
            match=re.search(r'\n\n来源：([^\n]+)$',retrieved)
            passage=retrieved[:match.start()] if match else retrieved
            source=match.group(1) if match else 'knowledge/'
            generated=rag_reply(text,passage)
            if generated:return f'{generated}\n\nFAQ 原文：\n{passage}\n来源：{source}'
            return f'{passage}\n\n来源：{source}'
        return '我可以协助查询专辑、订单、播放进度和会员信息，也能处理退款申请与客服工单。'
    except Exception as e:
        log.exception('audio-data request failed'); return f'业务数据暂时不可用，请稍后再试。来源：业务数据查询失败（{type(e).__name__}）'

def execute(task,slots,user_id=None):
    c=AudioDataClient(user_id)
    if task=='refund_request':
        orders=c.get('/api/v1/orders',pageSize=100); key=slots['order_id']
        row=next((x for x in orders.get('list',[]) if x.get('orderNo')==key or str(x.get('orderId'))==key),None)
        order_id=row['orderId'] if row else (int(key[3:]) if key.startswith('ORD') and key[3:].isdigit() else int(key) if key.isdigit() else None)
        if order_id is None: raise ValueError('未找到该订单')
        detail=c.get(f'/api/v1/orders/{order_id}')
        if detail['order'].get('orderNo') != key and str(detail['order'].get('orderId')) != key: raise ValueError('订单号与当前用户不匹配')
        pay=next((p for p in detail.get('payments',[]) if p.get('paymentStatus')=='success'),None)
        if not pay: raise ValueError('订单没有可退款的成功支付记录')
        if slots.get('refund_type')=='partial':
            amount=float(slots['refund_amount'])
            first=detail.get('items',[])[0]
            items=[{'orderItemId':first['itemId'],'refundQuantity':first['quantity'],'refundAmount':amount}]
        else:
            items=[{'orderItemId':i['itemId'],'refundQuantity':i['quantity'],'refundAmount':i['payableAmount']} for i in detail.get('items',[])]
        data=c.post('/api/v1/refunds',{'paymentId':pay['paymentId'],'refundReason':slots['reason'],'items':items})
        return f"退款申请已提交，退款单号 {data['refund']['refundNo']}，状态 {data['refund']['refundStatus']}。",'业务数据（refund_record）'
    allowed={'feature_feedback','usage_feedback','copyright_complaint','payment_issue','account_issue','content_issue','other'}
    kind=slots['ticket_type'] if slots['ticket_type'] in allowed else 'other'
    related_type='none'; related_id=None; order_ref=slots.get('order_id')
    if order_ref and order_ref!='none':
        rows=c.get('/api/v1/orders',pageSize=100).get('list',[])
        row=next((x for x in rows if x.get('orderNo')==order_ref or str(x.get('orderId'))==order_ref),None)
        related_id=row['orderId'] if row else (int(order_ref[3:]) if order_ref.startswith('ORD') and order_ref[3:].isdigit() else int(order_ref) if order_ref.isdigit() else None)
        if related_id: related_type='content_order'
    data=c.post('/api/v1/support-tickets',{'ticketType':kind,'relatedType':related_type,'relatedId':related_id,'ticketTitle':slots['description'][:100],'ticketContent':slots['description']})
    return f"工单已提交，编号 {data['ticketNo']}。",'业务数据（support_ticket）'
