import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
AUDIO_DATA_BASE_URL = os.getenv('AUDIO_DATA_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
AUDIO_DATA_USER_ID = os.getenv('AUDIO_DATA_USER_ID', '10001')
LLM_API_KEY = os.getenv('LLM_API_KEY', '')
LLM_BASE_URL = os.getenv('LLM_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')
LLM_MODEL = os.getenv('LLM_MODEL', 'qwen-max')
SAG_JEV_URL = os.getenv('SAG_JEV_URL', '')
SAG_JEV_KEY = os.getenv('SAG_JEV_KEY', '')
SAG_COMMAND = os.getenv('SAG_COMMAND', 'sag')

def mysql_config():
    raw = os.getenv('LISTEN_CS_DSN', 'mysql://root:commerce2026@127.0.0.1:3306/listen_cs')
    p = urlparse(raw)
    return {'host': p.hostname, 'port': p.port or 3306, 'user': p.username, 'password': p.password, 'database': p.path.lstrip('/'), 'charset': 'utf8mb4', 'autocommit': True, 'connect_timeout': 5}
