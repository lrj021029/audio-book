import logging
import time

import httpx

from .config import AUDIO_DATA_BASE_URL,AUDIO_DATA_USER_ID

log=logging.getLogger('listen_cs.audio_data')


class AudioDataError(RuntimeError):
    """Business API failure with a retryability hint for the dialogue engine."""

    def __init__(self, message, retryable=False, status=None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


def _message(response):
    try:
        return response.json().get('message')
    except Exception:
        return None


class AudioDataClient:
    def __init__(self,user_id=None): self.client=httpx.Client(base_url=AUDIO_DATA_BASE_URL,timeout=10,headers={'X-User-Id':str(user_id or AUDIO_DATA_USER_ID)})
    def get(self,path,**params):
        started=time.monotonic()
        try:
            r=self.client.get(path,params=params)
            log.info('audio_data method=GET path=%s status=%d elapsed_ms=%d',path,r.status_code,int((time.monotonic()-started)*1000))
            if r.status_code>=500:
                raise AudioDataError(_message(r) or f'业务查询失败（HTTP {r.status_code}）',retryable=True,status=r.status_code)
            if r.status_code>=400:
                raise AudioDataError(_message(r) or f'业务查询失败（HTTP {r.status_code}）',retryable=False,status=r.status_code)
            body=r.json()
            if body.get('code') not in (0,None):
                raise AudioDataError(body.get('message','业务数据查询失败'),retryable=False)
            return body.get('data',body)
        except AudioDataError:
            log.exception('audio_data method=GET path=%s elapsed_ms=%d',path,int((time.monotonic()-started)*1000)); raise
        except httpx.TimeoutException as exc:
            log.exception('audio_data timeout method=GET path=%s elapsed_ms=%d',path,int((time.monotonic()-started)*1000))
            raise AudioDataError('业务数据请求超时',retryable=True) from exc
        except httpx.TransportError as exc:
            log.exception('audio_data transport error method=GET path=%s elapsed_ms=%d',path,int((time.monotonic()-started)*1000))
            raise AudioDataError('业务数据网络异常',retryable=True) from exc
        except Exception:
            log.exception('audio_data method=GET path=%s elapsed_ms=%d',path,int((time.monotonic()-started)*1000)); raise
    def post(self,path,payload):
        started=time.monotonic()
        try:
            r=self.client.post(path,json=payload)
            log.info('audio_data method=POST path=%s status=%d elapsed_ms=%d',path,r.status_code,int((time.monotonic()-started)*1000))
            if r.status_code>=500:
                raise AudioDataError(_message(r) or f'业务提交失败（HTTP {r.status_code}）',retryable=True,status=r.status_code)
            if r.status_code>=400:
                raise AudioDataError(_message(r) or f'业务提交失败（HTTP {r.status_code}）',retryable=False,status=r.status_code)
            body=r.json()
            if body.get('code') not in (0,None):
                raise AudioDataError(body.get('message','业务请求失败'),retryable=False)
            return body.get('data',body)
        except AudioDataError:
            log.exception('audio_data method=POST path=%s elapsed_ms=%d',path,int((time.monotonic()-started)*1000)); raise
        except httpx.TimeoutException as exc:
            log.exception('audio_data timeout method=POST path=%s elapsed_ms=%d',path,int((time.monotonic()-started)*1000))
            raise AudioDataError('业务数据请求超时',retryable=True) from exc
        except httpx.TransportError as exc:
            log.exception('audio_data transport error method=POST path=%s elapsed_ms=%d',path,int((time.monotonic()-started)*1000))
            raise AudioDataError('业务数据网络异常',retryable=True) from exc
        except Exception:
            log.exception('audio_data method=POST path=%s elapsed_ms=%d',path,int((time.monotonic()-started)*1000)); raise
