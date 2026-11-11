import asyncio, json, logging, uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from . import db
from .config import AUDIO_DATA_USER_ID
from .engine import run
from .audio_client import AudioDataClient

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
@asynccontextmanager
async def lifespan(_: FastAPI):
    for attempt in range(30):
        try: db.initialize(); break
        except Exception:
            if attempt==29: raise
            await asyncio.sleep(2)
    yield
app=FastAPI(title='听书平台智能客服',version='1.0.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
def user_id(x_user_id: str | None):
    try: return int(x_user_id or AUDIO_DATA_USER_ID)
    except (TypeError,ValueError): raise HTTPException(400,'X-User-Id 必须为有效用户编号')
def owned(session_id,uid):
    if not db.get_session(session_id,uid): raise HTTPException(404,'会话不存在')
class ChatRequest(BaseModel):
    session_id: str=Field(alias='sessionId')
    message: str
    objects: list[dict]=Field(default_factory=list)
    turn_id: str|None=Field(default=None,alias='turnId')
class RenameRequest(BaseModel): title: str
@app.get('/health')
def health(): return {'status':'ok'}
@app.get('/meta')
def meta(x_user_id: str|None=Header(default=None)): return {'userId':user_id(x_user_id)}
@app.post('/session')
def new_session(x_user_id: str|None=Header(default=None)):
    uid=user_id(x_user_id); sid=str(uuid.uuid4()); db.create_session(sid,uid); return {'sessionId':sid}
@app.get('/sessions')
def sessions(x_user_id: str|None=Header(default=None)):
    uid=user_id(x_user_id); rows=db.list_sessions(uid)
    return {'sessions':[dict(r,created_at=r['created_at'].isoformat(),updated_at=r['updated_at'].isoformat()) for r in rows]}
@app.patch('/session/{session_id}')
def rename(session_id:str,body:RenameRequest,x_user_id: str|None=Header(default=None)):
    uid=user_id(x_user_id); owned(session_id,uid); title=body.title.strip()[:120]
    if not title: raise HTTPException(400,'会话名称不能为空')
    db.rename_session(session_id,uid,title); return {'ok':True,'title':title}
@app.delete('/session/{session_id}')
def delete(session_id:str,x_user_id: str|None=Header(default=None)):
    uid=user_id(x_user_id); owned(session_id,uid); db.delete_session(session_id,uid); return {'ok':True}
@app.delete('/session/{session_id}/history')
def clear(session_id:str,x_user_id: str|None=Header(default=None)):
    uid=user_id(x_user_id); owned(session_id,uid); db.clear_history(session_id,uid); return {'ok':True}
@app.get('/session/{session_id}/history')
def get_history(session_id:str,x_user_id: str|None=Header(default=None)):
    uid=user_id(x_user_id); owned(session_id,uid); rows=db.history(session_id,uid)
    turns=[]; by_id={}
    for r in rows:
        tid=r['turn_id']; turn=by_id.get(tid)
        if turn is None:
            turn={'turn_id':tid,'user':None,'assistant':[]}; by_id[tid]=turn; turns.append(turn)
        meta=json.loads(r['metadata_json'] or '{}') if isinstance(r['metadata_json'],str) else (r['metadata_json'] or {})
        stamp=r['created_at'].isoformat()
        if r['role']=='user':
            objects=meta.get('objects',[])
            turn['user']={'text':r['content'],'timestamp':stamp,'objects':objects,'cards':objects}
        elif r['role']=='assistant':
            turn['assistant'].append({'type':'text','text':r['content'],'timestamp':stamp,'intent':meta.get('intent'),'source':meta.get('source')})
            turn['intent']=meta.get('intent')
            turn['assistant'].extend({'type':'card','card':card} for card in meta.get('cards',[]))
    return {'sessionId':session_id,'turns':turns}
@app.get('/session/{session_id}/state')
def get_state(session_id:str,x_user_id: str|None=Header(default=None)):
    uid=user_id(x_user_id); s=db.get_state(session_id,uid)
    if s is None: raise HTTPException(404,'会话不存在')
    def unpack(v): return json.loads(v or ('[]' if isinstance(v,str) and v.startswith('[') else '{}')) if isinstance(v,str) else v
    return {'sessionId':session_id,'userId':uid,'current_task':s['current_task'],'slots':unpack(s['slots_json']),'suspended_stack':unpack(s['suspended_stack_json']),'awaiting_resume':bool(s['awaiting_resume']),'pending_query':s.get('pending_query'),'focused_object':unpack(s.get('focused_object_json'))}
@app.get('/catalog/orders')
def catalog_orders(x_user_id: str|None=Header(default=None)):
    data=AudioDataClient(user_id(x_user_id)).get('/api/v1/orders',pageSize=30)
    return {'items':data.get('list',[])}
@app.get('/catalog/albums')
def catalog_albums(q:str='',x_user_id: str|None=Header(default=None)):
    c=AudioDataClient(user_id(x_user_id)); data=c.get('/api/v1/search',keyword=q,searchType='all',channelId=1,pageSize=30) if q else c.get('/api/v1/albums',albumType='audiobook',sortBy='rating',pageSize=30)
    items=data.get('list',[]); return {'items':[x.get('album',x) for x in items]}
@app.get('/catalog/context')
def catalog_context(x_user_id: str|None=Header(default=None)):
    c=AudioDataClient(user_id(x_user_id)); output={'user':{},'orders':[],'bookshelf':[],'progress':[],'albums':[]}
    for key,path,params,dest in [('user','/api/v1/me',{},'user'),('orders','/api/v1/orders',{'pageSize':5},'orders'),('bookshelf','/api/v1/bookshelf',{'pageSize':8},'bookshelf'),('progress','/api/v1/listening-progress',{'pageSize':5},'progress'),('albums','/api/v1/albums',{'albumType':'audiobook','sortBy':'rating','pageSize':5},'albums')]:
        try:
            data=c.get(path,**params)
            if key=='user': output[dest]=data
            else:
                items=data.get('list',data.get('items',[]))
                if key=='orders':
                    items=[{**x,'type':'order','id':x.get('orderId'),'title':x.get('orderNo'),'subtitle':' · '.join(v for v in (x.get('orderStatus'),x.get('firstItemName')) if v),'cover_url':None} for x in items]
                elif key=='bookshelf':
                    items=[{**(x.get('album') or {}),'type':'album','id':(x.get('album') or {}).get('albumId'),'subtitle':x.get('lastTrackTitle') or x.get('shelfStatus') or '', 'shelfStatus':x.get('shelfStatus'),'lastTrackTitle':x.get('lastTrackTitle'),'lastPositionSeconds':x.get('lastPositionSeconds'),'cover_url':(x.get('album') or {}).get('coverUrl')} for x in items]
                elif key=='progress':
                    enriched=[]
                    for x in items:
                        try: album=c.get(f"/api/v1/albums/{int(x.get('albumId'))}").get('album',{})
                        except Exception: album={}
                        enriched.append({**x,'type':'album','id':x.get('albumId'),'albumTitle':x.get('albumTitle') or album.get('albumTitle'),'title':x.get('albumTitle') or album.get('albumTitle'),'subtitle':x.get('trackTitle') or '最近收听','cover_url':album.get('coverUrl'),'coverUrl':album.get('coverUrl')})
                    items=enriched
                elif key=='albums':
                    items=[{**x,'type':'album','id':x.get('albumId'),'title':x.get('albumTitle'),'subtitle':x.get('narratorName') or x.get('authorName') or f"{x.get('trackCount','')} 集",'cover_url':x.get('coverUrl')} for x in items]
                output[dest]=items
        except Exception as exc: output[dest]={'error':str(exc)}
    return output
@app.post('/chat')
def chat(body:ChatRequest,x_user_id: str|None=Header(default=None)):
    uid=user_id(x_user_id); owned(body.session_id,uid); return run(body.session_id,body.message,body.objects,uid,body.turn_id)
@app.post('/chat/stream')
def chat_stream(body:ChatRequest,x_user_id: str|None=Header(default=None)):
    uid=user_id(x_user_id); owned(body.session_id,uid)
    def events():
        result=run(body.session_id,body.message,body.objects,uid,body.turn_id); text=result['message']
        for part in [text[i:i+20] for i in range(0,len(text),20)]: yield f"event: token\ndata: {json.dumps({'turnId':result['turnId'],'text':part},ensure_ascii=False)}\n\n"
        yield f"event: done\ndata: {json.dumps(result,ensure_ascii=False,default=str)}\n\n"
    return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
