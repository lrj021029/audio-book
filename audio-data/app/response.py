"""Unified response helpers."""

from __future__ import annotations

from typing import Any


def ok(data: Any = None) -> dict[str, Any]:
    return {"code": 0, "message": "ok", "data": data}


def fail(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message, "data": None}
