from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import FakeCursor, fake_db_cursor

from app import dependencies
from app.routers import trade

NOW = datetime(2026, 6, 13, 10, 0, 0)


class TradeStore:
    def __init__(self) -> None:
        self.payments: dict[int, dict[str, Any]] = {
            1: {
                "id": 1,
                "payment_no": "PAY001",
                "pay_subject_type": "content_order",
                "pay_subject_id": 100,
                "payment_channel": "balance",
                "currency_code": "CNY",
                "payment_amount": Decimal("20.00"),
                "payment_status": "created",
                "paid_at": None,
                "created_at": NOW,
            }
        }
        self.orders: dict[int, dict[str, Any]] = {
            100: {
                "id": 100,
                "user_id": 1,
                "currency_code": "CNY",
                "order_status": "created",
                "payable_amount": Decimal("20.00"),
                "paid_at": None,
                "created_at": NOW,
            }
        }
        self.recharge_orders: dict[int, dict[str, Any]] = {}
        self.wallets: dict[int, dict[str, Any]] = {
            1: {
                "id": 1,
                "user_id": 1,
                "currency_code": "CNY",
                "balance_amount": Decimal("50.00"),
                "frozen_amount": Decimal("0.00"),
                "available_amount": Decimal("50.00"),
            }
        }
        self.order_items: list[dict[str, Any]] = [
            {
                "id": 1001,
                "order_id": 100,
                "item_type": "album",
                "vip_plan_id": None,
                "album_id": 7,
                "track_id": None,
                "quantity": 1,
                "payable_amount": Decimal("20.00"),
            }
        ]
        self.refunds: dict[int, dict[str, Any]] = {}
        self.refund_items: list[dict[str, Any]] = []
        self.wallet_ledgers: list[dict[str, Any]] = []
        self.entitlements: list[dict[str, Any]] = []
        self.next_refund_id = 1
        self.next_ledger_id = 1

    def cursor(self) -> StoreCursor:
        return StoreCursor(self)

    def fetch_one(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> dict[str, Any] | None:
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor.fetchone()

    def fetch_all(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
        cursor = self.cursor()
        cursor.execute(sql, params)
        return list(cursor.fetchall())


class StoreCursor:
    def __init__(self, store: TradeStore) -> None:
        self.store = store
        self.result: list[dict[str, Any]] = []
        self.lastrowid: int | None = None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> int:
        normalized = " ".join(sql.lower().split())
        values = params or ()
        self.result = []
        self.lastrowid = None

        if normalized.startswith("select"):
            self.result = self._select(normalized, values)
            return len(self.result)
        if normalized.startswith("update"):
            return self._update(normalized, values)
        if normalized.startswith("insert"):
            return self._insert(normalized, values)
        raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self) -> dict[str, Any] | None:
        return self.result[0] if self.result else None

    def fetchall(self) -> list[dict[str, Any]]:
        return self.result

    def close(self) -> None:
        return None

    def _select(
        self, normalized: str, values: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        if "from payment_record" in normalized and "payment_no = %s" in normalized:
            return [
                payment
                for payment in self.store.payments.values()
                if payment["payment_no"] == values[0]
            ]
        if "from payment_record" in normalized and "where id = %s" in normalized:
            payment = self.store.payments.get(int(values[0]))
            return [] if payment is None else [payment]
        if "from content_order_item" in normalized and "where order_id = %s" in normalized:
            return [
                item
                for item in self.store.order_items
                if item["order_id"] == int(values[0])
            ]
        if "from content_order_item" in normalized and "where id = %s" in normalized:
            order_item_id, order_id = int(values[0]), int(values[1])
            return [
                item
                for item in self.store.order_items
                if item["id"] == order_item_id and item["order_id"] == order_id
            ]
        if "select order_status as subject_status" in normalized:
            order = self.store.orders.get(int(values[0]))
            return [] if order is None else [{"subject_status": order["order_status"]}]
        if "from content_order" in normalized and "where id = %s" in normalized:
            order = self.store.orders.get(int(values[0]))
            if order is None:
                return []
            if "user_id = %s" in normalized and order["user_id"] != int(values[1]):
                return []
            return [order]
        if "from recharge_order" in normalized and "where id = %s" in normalized:
            recharge = self.store.recharge_orders.get(int(values[0]))
            return [] if recharge is None else [recharge]
        if "from wallet_account" in normalized and "user_id = %s" in normalized:
            user_id, currency_code = int(values[0]), values[1]
            return [
                wallet
                for wallet in self.store.wallets.values()
                if wallet["user_id"] == user_id
                and wallet["currency_code"] == currency_code
            ]
        if "from wallet_account" in normalized and "where id = %s" in normalized:
            wallet = self.store.wallets.get(int(values[0]))
            return [] if wallet is None else [wallet]
        if "from refund_record_item ri join refund_record r" in normalized:
            payment_id, order_item_id = int(values[0]), int(values[1])
            quantity = 0
            amount = Decimal("0.00")
            for item in self.store.refund_items:
                refund = self.store.refunds[item["refund_id"]]
                if (
                    refund["payment_id"] == payment_id
                    and item["order_item_id"] == order_item_id
                    and refund["refund_status"] in {"requested", "approved", "success"}
                ):
                    quantity += int(item["refund_quantity"])
                    amount += Decimal(item["refund_amount"])
            return [{"quantity": quantity, "amount": amount}]
        if "from refund_record_item ri join content_order_item oi" in normalized:
            refund_id = int(values[0])
            joined = []
            for refund_item in self.store.refund_items:
                if refund_item["refund_id"] != refund_id:
                    continue
                order_item = next(
                    item
                    for item in self.store.order_items
                    if item["id"] == refund_item["order_item_id"]
                )
                joined.append(refund_item | order_item)
            return joined
        if "from refund_record_item" in normalized and "where refund_id = %s" in normalized:
            refund_id = int(values[0])
            return [
                item
                for item in self.store.refund_items
                if item["refund_id"] == refund_id
            ]
        if "from refund_record" in normalized and "refund_no = %s" in normalized:
            return [
                refund
                for refund in self.store.refunds.values()
                if refund["refund_no"] == values[0]
            ]
        if "from refund_record" in normalized and "where id = %s" in normalized:
            refund = self.store.refunds.get(int(values[0]))
            return [] if refund is None else [refund]
        if "from refund_record" in normalized and "payment_id = %s" in normalized:
            payment_id = int(values[0])
            amount = sum(
                Decimal(refund["refund_amount"])
                for refund in self.store.refunds.values()
                if refund["payment_id"] == payment_id
                and refund["refund_status"] in {"requested", "approved", "success"}
            )
            return [{"amount": amount}]
        if (
            "from refund_record" in normalized
            and "refund_subject_type = 'content_order'" in normalized
        ):
            order_id = int(values[0])
            amount = sum(
                Decimal(refund["refund_amount"])
                for refund in self.store.refunds.values()
                if refund["refund_subject_id"] == order_id
                and refund["refund_status"] == "success"
            )
            return [{"amount": amount}]
        raise AssertionError(f"unexpected SELECT: {normalized}")

    def _update(self, normalized: str, values: tuple[Any, ...]) -> int:
        if normalized.startswith("update payment_record"):
            payment = self.store.payments[int(values[4])]
            if payment["payment_status"] in {"success", "failed", "closed"}:
                return 0
            payment["payment_status"] = values[0]
            if values[0] == "success":
                payment["paid_at"] = values[2]
            return 1
        if normalized.startswith("update wallet_account"):
            wallet = self.store.wallets[int(values[3])]
            wallet["balance_amount"] = Decimal(values[0])
            wallet["available_amount"] = Decimal(values[1])
            return 1
        if normalized.startswith("update content_order set order_status = 'paid'"):
            order = self.store.orders[int(values[2])]
            order["order_status"] = "paid"
            order["paid_at"] = values[0]
            return 1
        if normalized.startswith("update content_order"):
            order = self.store.orders[int(values[2])]
            order["order_status"] = values[0]
            return 1
        if normalized.startswith("update refund_record"):
            refund = self.store.refunds[int(values[6])]
            if refund["refund_status"] in {"rejected", "success", "failed"}:
                return 0
            refund["refund_status"] = values[0]
            if values[0] == "success":
                refund["refunded_at"] = values[4]
            return 1
        if normalized.startswith("update entitlement_record"):
            for entitlement in self.store.entitlements:
                entitlement["entitlement_status"] = "revoked"
            return len(self.store.entitlements)
        raise AssertionError(f"unexpected UPDATE: {normalized}")

    def _insert(self, normalized: str, values: tuple[Any, ...]) -> int:
        if normalized.startswith("insert into wallet_ledger"):
            ledger = {
                "id": self.store.next_ledger_id,
                "ledger_no": values[0],
                "wallet_id": values[1],
                "user_id": values[2],
                "ledger_type": values[3],
                "related_type": values[4],
                "related_id": values[5],
                "currency_code": values[6],
                "amount_delta": values[7],
                "balance_after": values[8],
                "available_after": values[10],
            }
            self.store.wallet_ledgers.append(ledger)
            self.lastrowid = self.store.next_ledger_id
            self.store.next_ledger_id += 1
            return 1
        if normalized.startswith("insert ignore into entitlement_record"):
            entitlement = {
                "user_id": values[0],
                "source_type": values[1],
                "order_id": values[2],
                "target_type": values[3],
                "target_id": values[4],
                "entitlement_status": "active",
            }
            if entitlement not in self.store.entitlements:
                self.store.entitlements.append(entitlement)
            return 1
        if normalized.startswith("insert into refund_record_item"):
            self.store.refund_items.append(
                {
                    "id": len(self.store.refund_items) + 1,
                    "refund_id": int(values[0]),
                    "order_item_id": int(values[1]),
                    "item_type": values[2],
                    "refund_quantity": int(values[3]),
                    "refund_amount": Decimal(values[4]),
                    "created_at": values[5],
                }
            )
            self.lastrowid = len(self.store.refund_items)
            return 1
        if normalized.startswith("insert into refund_record"):
            refund_id = self.store.next_refund_id
            self.store.refunds[refund_id] = {
                "id": refund_id,
                "refund_no": values[0],
                "refund_subject_type": values[1],
                "refund_subject_id": values[2],
                "payment_id": values[3],
                "refund_reason": values[4],
                "refund_amount": Decimal(values[5]),
                "refund_status": "requested",
                "requested_at": values[6],
                "handled_at": None,
                "refunded_at": None,
            }
            self.lastrowid = refund_id
            self.store.next_refund_id += 1
            return 1
        raise AssertionError(f"unexpected INSERT: {normalized}")


@contextmanager
def trade_db_cursor(store: TradeStore) -> Iterator[tuple[None, StoreCursor]]:
    yield None, store.cursor()


@pytest.fixture
def trade_store(monkeypatch: Any) -> TradeStore:
    store = TradeStore()

    monkeypatch.setattr(
        dependencies,
        "fetch_one",
        lambda sql, params=None: {"id": int(params[0])}
        if params and int(params[0]) == 1
        else None,
    )
    monkeypatch.setattr(trade, "fetch_one", store.fetch_one)
    monkeypatch.setattr(trade, "fetch_all", store.fetch_all)
    monkeypatch.setattr(
        trade,
        "db_cursor",
        lambda: trade_db_cursor(store),
    )
    monkeypatch.setattr(trade, "make_no", lambda prefix: f"{prefix}TEST")
    return store


def test_payment_notification_is_idempotent(
    client: TestClient, trade_store: TradeStore
) -> None:
    body = {"paymentNo": "PAY001", "paymentStatus": "success"}
    headers = {"X-Demo-Payment-Signature": "mock-payment-signature"}

    first = client.post("/api/v1/payment-notifications/mock", json=body, headers=headers)
    second = client.post("/api/v1/payment-notifications/mock", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert trade_store.payments[1]["payment_status"] == "success"
    assert trade_store.orders[100]["order_status"] == "paid"
    assert trade_store.wallets[1]["balance_amount"] == Decimal("30.00")
    assert len(trade_store.wallet_ledgers) == 1
    assert len(trade_store.entitlements) == 1
    assert second.json()["data"]["walletLedger"] is None


def test_create_refund_rejects_amount_above_item_remaining(
    client: TestClient, trade_store: TradeStore
) -> None:
    trade_store.payments[1]["payment_amount"] = Decimal("100.00")
    trade_store.payments[1]["payment_status"] = "success"
    trade_store.orders[100]["order_status"] = "paid"
    trade_store.orders[100]["payable_amount"] = Decimal("100.00")
    trade_store.refunds[1] = {
        "id": 1,
        "refund_no": "RFD001",
        "refund_subject_type": "content_order",
        "refund_subject_id": 100,
        "payment_id": 1,
        "refund_amount": Decimal("15.00"),
        "refund_status": "requested",
        "refund_reason": None,
        "requested_at": NOW,
        "handled_at": None,
        "refunded_at": None,
    }
    trade_store.refund_items.append(
        {
            "id": 1,
            "refund_id": 1,
            "order_item_id": 1001,
            "item_type": "album",
            "refund_quantity": 0,
            "refund_amount": Decimal("15.00"),
            "created_at": NOW,
        }
    )
    trade_store.next_refund_id = 2
    body = {
        "paymentId": 1,
        "items": [
            {"orderItemId": 1001, "refundQuantity": 1, "refundAmount": "10.00"}
        ],
    }

    response = client.post("/api/v1/refunds", json=body, headers={"X-User-Id": "1"})

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REFUND_AMOUNT"
    assert len(trade_store.refunds) == 1


def test_refund_notification_is_idempotent(
    client: TestClient, trade_store: TradeStore
) -> None:
    trade_store.payments[1]["payment_status"] = "success"
    trade_store.orders[100]["order_status"] = "paid"
    trade_store.wallets[1]["balance_amount"] = Decimal("30.00")
    trade_store.wallets[1]["available_amount"] = Decimal("30.00")
    trade_store.refunds[1] = {
        "id": 1,
        "refund_no": "RFD001",
        "refund_subject_type": "content_order",
        "refund_subject_id": 100,
        "payment_id": 1,
        "refund_amount": Decimal("5.00"),
        "refund_status": "requested",
        "refund_reason": None,
        "requested_at": NOW,
        "handled_at": None,
        "refunded_at": None,
    }
    trade_store.refund_items.append(
        {
            "id": 1,
            "refund_id": 1,
            "order_item_id": 1001,
            "item_type": "album",
            "refund_quantity": 1,
            "refund_amount": Decimal("5.00"),
            "created_at": NOW,
        }
    )
    body = {"refundNo": "RFD001", "refundStatus": "success"}
    headers = {"X-Demo-Payment-Signature": "mock-payment-signature"}

    first = client.post("/api/v1/refund-notifications/mock", json=body, headers=headers)
    second = client.post("/api/v1/refund-notifications/mock", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert trade_store.refunds[1]["refund_status"] == "success"
    assert trade_store.wallets[1]["balance_amount"] == Decimal("35.00")
    assert len(trade_store.wallet_ledgers) == 1
    assert second.json()["data"]["walletLedger"] is None


def test_vip_plans_and_entitlements_success(
    client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        dependencies,
        "fetch_one",
        lambda sql, params=None: {"id": 1} if params and int(params[0]) == 1 else None,
    )
    monkeypatch.setattr(
        trade,
        "fetch_all",
        lambda sql, params=None: [
            {
                "id": 1,
                "plan_code": "vip_month",
                "plan_name": "VIP 月卡",
                "member_level": "vip",
                "duration_days": 30,
                "currency_code": "CNY",
                "sale_price_amount": Decimal("19.90"),
                "original_price_amount": Decimal("29.90"),
                "benefit_payload": "{}",
                "source_type": "purchase",
                "order_id": 100,
                "target_type": "album",
                "target_id": 7,
                "valid_from": NOW,
                "valid_to": None,
                "entitlement_status": "active",
            }
        ],
    )
    monkeypatch.setattr(
        trade,
        "fetch_one",
        lambda sql, params=None: {
            "member_level": "vip",
            "member_status": "active",
            "valid_from": NOW,
            "valid_to": NOW,
        }
        if "FROM member_account" in sql
        else {"album_title": "专辑"}
        if "audio_album" in sql
        else None,
    )
    monkeypatch.setattr(trade, "target_name", lambda target_type, target_id: "专辑")

    plans = client.get("/api/v1/vip-plans", headers={"X-User-Id": "1"})
    entitlements = client.get(
        "/api/v1/entitlements",
        params={"targetType": "album", "entitlementStatus": "active"},
        headers={"X-User-Id": "1"},
    )

    assert plans.status_code == 200
    assert plans.json()["data"]["plans"][0]["planName"] == "VIP 月卡"
    assert entitlements.status_code == 200
    assert entitlements.json()["data"]["entitlements"][0]["targetName"] == "专辑"


def test_order_preview_and_create_success(client: TestClient, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        dependencies,
        "fetch_one",
        lambda sql, params=None: {"id": 1} if params and int(params[0]) == 1 else None,
    )

    order = {
        "id": 100,
        "order_no": "ORD001",
        "order_type": "album",
        "order_status": "created",
        "currency_code": "CNY",
        "total_amount": Decimal("20.00"),
        "discount_amount": Decimal("0.00"),
        "payable_amount": Decimal("20.00"),
        "paid_at": None,
        "created_at": NOW,
    }
    order_item = {
        "id": 1001,
        "order_id": 100,
        "item_type": "album",
        "vip_plan_id": None,
        "album_id": 7,
        "track_id": None,
        "item_name": "专辑",
        "quantity": 1,
        "unit_price_amount": Decimal("20.00"),
        "discount_amount": Decimal("0.00"),
        "payable_amount": Decimal("20.00"),
    }

    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM audio_album" in sql:
            return {"id": 7, "album_title": "专辑", "album_status": "published"}
        if "FROM album_price_rule" in sql:
            return {
                "price_type": "album_paid",
                "album_price_amount": Decimal("20.00"),
                "currency_code": "CNY",
            }
        if "FROM entitlement_record" in sql:
            return None
        if "FROM dim_channel" in sql:
            return {"id": 1}
        if "FROM content_order WHERE id = %s" in sql:
            return order
        return None

    monkeypatch.setattr(trade, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(
        trade,
        "current_price_rule",
        lambda album_id: {
            "price_type": "album_paid",
            "album_price_amount": Decimal("20.00"),
            "currency_code": "CNY",
        },
    )
    monkeypatch.setattr(trade, "fetch_all", lambda sql, params=None: [order_item])
    monkeypatch.setattr(trade, "db_cursor", lambda: fake_db_cursor(FakeCursor()))
    monkeypatch.setattr(trade, "make_no", lambda prefix: f"{prefix}TEST")

    body = {"orderType": "album", "items": [{"itemType": "album", "albumId": 7}]}
    preview = client.post("/api/v1/orders/preview", json=body, headers={"X-User-Id": "1"})
    created = client.post("/api/v1/orders", json=body, headers={"X-User-Id": "1"})

    assert preview.status_code == 200
    assert preview.json()["data"]["payableAmount"] == 20.0
    assert created.status_code == 200
    assert created.json()["data"]["order"]["orderStatus"] == "created"


def test_create_payment_success_and_conflict(client: TestClient, monkeypatch: Any) -> None:
    monkeypatch.setattr(
        dependencies,
        "fetch_one",
        lambda sql, params=None: {"id": 1} if params and int(params[0]) == 1 else None,
    )
    payment = {
        "id": 2,
        "payment_no": "PAY001",
        "pay_subject_type": "content_order",
        "pay_subject_id": 100,
        "payment_channel": "alipay",
        "payment_status": "created",
        "payment_amount": Decimal("20.00"),
        "currency_code": "CNY",
        "paid_at": None,
        "created_at": NOW,
    }

    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM content_order" in sql:
            return {
                "id": 100,
                "user_id": 1,
                "order_status": "created",
                "currency_code": "CNY",
                "payable_amount": Decimal("20.00"),
            }
        if "payment_status IN ('created', 'processing')" in sql:
            return None
        if "FROM payment_record WHERE id = %s" in sql:
            return payment
        return None

    monkeypatch.setattr(trade, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(trade, "db_cursor", lambda: fake_db_cursor(FakeCursor()))
    monkeypatch.setattr(trade, "make_no", lambda prefix: f"{prefix}TEST")

    response = client.post(
        "/api/v1/payments",
        json={"paySubjectType": "content_order", "paySubjectId": 100, "paymentChannel": "alipay"},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["payment"]["paymentStatus"] == "created"

    def paid_subject(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM content_order" in sql:
            return {
                "id": 100,
                "user_id": 1,
                "order_status": "paid",
                "currency_code": "CNY",
                "payable_amount": Decimal("20.00"),
            }
        return None

    monkeypatch.setattr(trade, "fetch_one", paid_subject)
    conflict_response = client.post(
        "/api/v1/payments",
        json={"paySubjectType": "content_order", "paySubjectId": 100, "paymentChannel": "alipay"},
        headers={"X-User-Id": "1"},
    )

    assert conflict_response.status_code == 409
    assert conflict_response.json()["code"] == "PAY_SUBJECT_NOT_PAYABLE"


@pytest.mark.parametrize(
    ("item", "expected_code"),
    [
        (
            {"orderItemId": 1001, "refundQuantity": 1, "refundAmount": "0"},
            "INVALID_REFUND_AMOUNT",
        ),
        (
            {"orderItemId": 1001, "refundQuantity": 1, "refundAmount": "-1.00"},
            "INVALID_REFUND_AMOUNT",
        ),
    ],
)
def test_create_refund_rejects_non_positive_amount(
    client: TestClient,
    trade_store: TradeStore,
    item: dict[str, Any],
    expected_code: str,
) -> None:
    trade_store.payments[1]["payment_status"] = "success"
    trade_store.orders[100]["order_status"] = "paid"

    response = client.post(
        "/api/v1/refunds",
        json={"paymentId": 1, "items": [item]},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == expected_code


def test_create_refund_rejects_duplicate_items(
    client: TestClient, trade_store: TradeStore
) -> None:
    trade_store.payments[1]["payment_status"] = "success"
    trade_store.orders[100]["order_status"] = "paid"
    body = {
        "paymentId": 1,
        "items": [
            {"orderItemId": 1001, "refundQuantity": 1, "refundAmount": "5.00"},
            {"orderItemId": 1001, "refundQuantity": 1, "refundAmount": "5.00"},
        ],
    }

    response = client.post("/api/v1/refunds", json=body, headers={"X-User-Id": "1"})

    assert response.status_code == 400
    assert response.json()["code"] == "DUPLICATE_REFUND_ITEM"


def test_multiple_partial_refunds_respect_quantity_and_amount(
    client: TestClient, trade_store: TradeStore
) -> None:
    trade_store.payments[1]["payment_status"] = "success"
    trade_store.payments[1]["payment_amount"] = Decimal("20.00")
    trade_store.orders[100]["order_status"] = "paid"
    trade_store.order_items[0]["quantity"] = 2
    trade_store.order_items[0]["payable_amount"] = Decimal("20.00")

    first = client.post(
        "/api/v1/refunds",
        json={
            "paymentId": 1,
            "items": [{"orderItemId": 1001, "refundQuantity": 1, "refundAmount": "8.00"}],
        },
        headers={"X-User-Id": "1"},
    )
    second = client.post(
        "/api/v1/refunds",
        json={
            "paymentId": 1,
            "items": [{"orderItemId": 1001, "refundQuantity": 1, "refundAmount": "12.00"}],
        },
        headers={"X-User-Id": "1"},
    )
    third = client.post(
        "/api/v1/refunds",
        json={
            "paymentId": 1,
            "items": [{"orderItemId": 1001, "refundQuantity": 1, "refundAmount": "1.00"}],
        },
        headers={"X-User-Id": "1"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 400
    assert third.json()["code"] == "INVALID_REFUND_QUANTITY"
    assert sum(refund["refund_amount"] for refund in trade_store.refunds.values()) == Decimal("20.00")


def test_order_and_refund_lists_cover_filters_and_empty(
    client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        dependencies,
        "fetch_one",
        lambda sql, params=None: {"id": 1} if params and int(params[0]) == 1 else None,
    )
    monkeypatch.setattr(trade, "count_total", lambda sql, params=None: 0)
    monkeypatch.setattr(trade, "fetch_all", lambda sql, params=None: [])

    orders = client.get(
        "/api/v1/orders",
        params={"orderType": "album", "orderStatus": "paid", "pageNo": 2, "pageSize": 5},
        headers={"X-User-Id": "1"},
    )
    refunds = client.get(
        "/api/v1/refunds",
        params={"refundStatus": "success", "pageNo": 2, "pageSize": 5},
        headers={"X-User-Id": "1"},
    )

    assert orders.status_code == 200
    assert orders.json()["data"] == {"list": [], "pageNo": 2, "pageSize": 5, "total": 0}
    assert refunds.status_code == 200
    assert refunds.json()["data"] == {"list": [], "pageNo": 2, "pageSize": 5, "total": 0}
