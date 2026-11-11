import logging
import time
import httpx
from .config import AUDIO_DATA_BASE_URL,AUDIO_DATA_USER_ID
log=logging.getLogger('listen_cs.audio_data')
class AudioDataClient:
    def __init__(self,user_id=None): self.client=httpx.Client(base_url=AUDIO_DATA_BASE_URL,timeout=10,headers={'X-User-Id':str(user_id or AUDIO_DATA_USER_ID)})
    def get(self,path,**params):
        started=time.monotonic()
        try:
            r=self.client.get(path,params=params)
            log.info('audio_data method=GET path=%s status=%d elapsed_ms=%d',path,r.status_code,int((time.monotonic()-started)*1000))
            if r.status_code>=400:
                try: message=r.json().get('message')
                except Exception: message=None
                raise RuntimeError(message or f'业务查询失败（HTTP {r.status_code}）')
            body=r.json()
            if body.get('code') not in (0,None): raise RuntimeError(body.get('message','业务数据查询失败'))
            return body.get('data',body)
        except Exception:
            log.exception('audio_data method=GET path=%s elapsed_ms=%d',path,int((time.monotonic()-started)*1000)); raise
    def post(self,path,payload):
        started=time.monotonic()
        try:
            r=self.client.post(path,json=payload)
            log.info('audio_data method=POST path=%s status=%d elapsed_ms=%d',path,r.status_code,int((time.monotonic()-started)*1000))
            if r.status_code>=400:
                try: message=r.json().get('message')
                except Exception: message=None
                raise RuntimeError(message or f'业务提交失败（HTTP {r.status_code}）')
            body=r.json()
            if body.get('code') not in (0,None): raise RuntimeError(body.get('message','业务请求失败'))
            return body.get('data',body)
        except Exception:
            log.exception('audio_data method=POST path=%s elapsed_ms=%d',path,int((time.monotonic()-started)*1000)); raise
