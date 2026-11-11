"""Application configuration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent

load_dotenv(ROOT_DIR / ".env")

APP_PORT = int(os.getenv("APP_PORT", "8000"))
DEMO_PAYMENT_SIGNATURE = os.getenv("DEMO_PAYMENT_SIGNATURE", "mock-payment-signature")

DB_CONFIG = {
    "host": os.environ["DB_HOST"],
    "port": int(os.environ["DB_PORT"]),
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "database": os.environ["DB_NAME"],
    "charset": "utf8mb4",
    "autocommit": False,
}

_ssl_ca = os.environ.get("DB_SSL_CA", "")
if _ssl_ca:
    DB_CONFIG["ssl"] = {"ca": _ssl_ca}
