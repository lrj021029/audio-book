from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from app import dependencies

NOW = datetime(2026, 6, 13, 10, 0, 0)


class FakeCursor:
    def __init__(
        self,
        on_execute: Callable[[str, tuple[Any, ...], "FakeCursor"], None] | None = None,
    ) -> None:
        self.on_execute = on_execute
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.result: list[dict[str, Any]] = []
        self.lastrowid = 1

    def execute(self, sql: str, params: Any | None = None) -> int:
        values = tuple(params or ())
        self.executed.append((sql, values))
        self.result = []
        if self.on_execute is not None:
            self.on_execute(sql, values, self)
        return 1

    def fetchone(self) -> dict[str, Any] | None:
        return self.result[0] if self.result else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.result

    def close(self) -> None:
        return None


@contextmanager
def fake_db_cursor(cursor: FakeCursor | None = None) -> Iterator[tuple[None, FakeCursor]]:
    yield None, cursor or FakeCursor()


def patch_auth_user(monkeypatch: Any, user_id: int = 1) -> None:
    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM user_account" in sql and params and int(params[0]) == user_id:
            return {"id": user_id}
        return None

    monkeypatch.setattr(dependencies, "fetch_one", fake_fetch_one)


def response_code(payload: dict[str, Any]) -> Any:
    return payload["code"]
