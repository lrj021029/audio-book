from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import NOW, FakeCursor, fake_db_cursor, patch_auth_user

from app.routers import interactions, tickets, users, wallet


def test_me_profile_and_messages_success(client: TestClient, monkeypatch: Any) -> None:
    patch_auth_user(monkeypatch)

    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM user_account" in sql:
            return {
                "id": 1,
                "user_no": "U001",
                "nickname": "Alice",
                "avatar_url": "https://example.com/a.png",
                "account_status": "normal",
                "last_login_at": NOW,
            }
        if "FROM user_profile" in sql:
            return {
                "id": 1,
                "user_id": 1,
                "gender": "female",
                "birthday": NOW.date(),
                "province": "浙江",
                "city": "杭州",
                "occupation": "工程师",
                "listening_scene_payload": json.dumps(["通勤"], ensure_ascii=False),
            }
        if "FROM member_account" in sql:
            return {
                "member_level": "vip",
                "member_status": "active",
                "valid_from": NOW,
                "valid_to": NOW,
            }
        if "FROM wallet_account" in sql:
            return {"id": 1, "available_amount": Decimal("88.00"), "currency_code": "CNY"}
        if "FROM user_message" in sql:
            return {
                "id": 3,
                "receiver_user_id": 1,
                "read_status": "unread",
                "read_at": None,
            }
        return None

    monkeypatch.setattr(users, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(users, "db_cursor", lambda: fake_db_cursor(FakeCursor()))
    monkeypatch.setattr(
        users,
        "fetch_all",
        lambda sql, params=None: [
            {
                "id": 3,
                "message_no": "MSG001",
                "message_type": "system",
                "message_title": "通知",
                "message_content": "内容",
                "target_type": None,
                "target_id": None,
                "read_status": "unread",
                "sent_at": NOW,
                "read_at": None,
            }
        ],
    )
    monkeypatch.setattr(users, "count_total", lambda sql, params=None: 1)

    me = client.get("/api/v1/me", headers={"X-User-Id": "1"})
    profile = client.patch(
        "/api/v1/me/profile",
        json={"nickname": "Alice 2", "gender": "female", "listeningScene": ["睡前"]},
        headers={"X-User-Id": "1"},
    )
    messages = client.get(
        "/api/v1/messages",
        params={"messageType": "system", "readStatus": "unread", "pageNo": 1, "pageSize": 5},
        headers={"X-User-Id": "1"},
    )
    read = client.patch("/api/v1/messages/3/read", headers={"X-User-Id": "1"})

    assert me.status_code == 200
    assert me.json()["data"]["user"]["nickname"] == "Alice"
    assert profile.status_code == 200
    assert profile.json()["data"]["profile"]["gender"] == "female"
    assert messages.status_code == 200
    assert messages.json()["data"]["total"] == 1
    assert read.status_code == 200
    assert read.json()["data"]["readStatus"] == "read"


def test_profile_rejects_invalid_values(client: TestClient, monkeypatch: Any) -> None:
    patch_auth_user(monkeypatch)

    response = client.patch(
        "/api/v1/me/profile",
        json={"nickname": " ", "gender": "male"},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "EMPTY_NICKNAME"


def test_wallet_recharge_success_and_lists(client: TestClient, monkeypatch: Any) -> None:
    patch_auth_user(monkeypatch)

    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM wallet_account" in sql:
            return {
                "id": 1,
                "user_id": 1,
                "currency_code": "CNY",
                "wallet_status": "active",
                "balance_amount": Decimal("10.00"),
                "frozen_amount": Decimal("0.00"),
                "available_amount": Decimal("10.00"),
                "opened_at": NOW,
            }
        if "FROM dim_channel" in sql:
            return {"id": 1}
        if "FROM recharge_order" in sql:
            return {
                "id": 1,
                "recharge_no": "RCH001",
                "payable_amount": Decimal("20.00"),
                "recharge_status": "created",
            }
        if "FROM payment_record" in sql:
            return {
                "id": 2,
                "payment_no": "PAY001",
                "pay_subject_type": "recharge_order",
                "pay_subject_id": 1,
                "payment_channel": "alipay",
                "payment_status": "created",
                "payment_amount": Decimal("20.00"),
                "currency_code": "CNY",
                "paid_at": None,
                "created_at": NOW,
            }
        return None

    monkeypatch.setattr(wallet, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(wallet, "fetch_all", lambda sql, params=None: [])
    monkeypatch.setattr(wallet, "count_total", lambda sql, params=None: 0)
    monkeypatch.setattr(wallet, "db_cursor", lambda: fake_db_cursor(FakeCursor()))
    monkeypatch.setattr(wallet, "make_no", lambda prefix: f"{prefix}TEST")

    wallet_response = client.get("/api/v1/wallet", headers={"X-User-Id": "1"})
    ledgers = client.get(
        "/api/v1/wallet/ledgers",
        params={"ledgerType": "recharge", "pageNo": 2, "pageSize": 5},
        headers={"X-User-Id": "1"},
    )
    recharge = client.post(
        "/api/v1/recharge-orders",
        json={"walletId": 1, "rechargeAmount": "20.00", "paymentChannel": "alipay"},
        headers={"X-User-Id": "1"},
    )

    assert wallet_response.status_code == 200
    assert wallet_response.json()["data"]["wallet"]["availableAmount"] == 10.0
    assert ledgers.status_code == 200
    assert ledgers.json()["data"] == {"list": [], "pageNo": 2, "pageSize": 5, "total": 0}
    assert recharge.status_code == 200
    assert recharge.json()["data"]["rechargeOrder"]["rechargeStatus"] == "created"


@pytest.mark.parametrize("amount", ["0", "-1.00"])
def test_recharge_rejects_non_positive_amount(
    client: TestClient, monkeypatch: Any, amount: str
) -> None:
    patch_auth_user(monkeypatch)

    response = client.post(
        "/api/v1/recharge-orders",
        json={"walletId": 1, "rechargeAmount": amount, "paymentChannel": "alipay"},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_RECHARGE_AMOUNT"


def test_support_ticket_success_list_and_detail(
    client: TestClient, monkeypatch: Any
) -> None:
    patch_auth_user(monkeypatch)
    ticket = {
        "id": 1,
        "ticket_no": "TCK001",
        "ticket_type": "usage_feedback",
        "related_type": "none",
        "related_id": None,
        "ticket_title": "问题",
        "ticket_content": "内容",
        "contact_mobile": "13800000000",
        "contact_email": None,
        "ticket_status": "submitted",
        "submitted_at": NOW,
        "handled_at": None,
        "closed_at": None,
        "handle_result": None,
    }
    monkeypatch.setattr(tickets, "target_exists", lambda target_type, target_id: True)
    monkeypatch.setattr(tickets, "make_no", lambda prefix: "TCKTEST")
    monkeypatch.setattr(tickets, "db_cursor", lambda: fake_db_cursor(FakeCursor()))
    monkeypatch.setattr(tickets, "fetch_one", lambda sql, params=None: ticket)
    monkeypatch.setattr(tickets, "fetch_all", lambda sql, params=None: [ticket])
    monkeypatch.setattr(tickets, "count_total", lambda sql, params=None: 1)

    created = client.post(
        "/api/v1/support-tickets",
        json={
            "ticketType": "usage_feedback",
            "relatedType": "none",
            "ticketTitle": "问题",
            "ticketContent": "内容",
            "contactMobile": "13800000000",
        },
    )
    listed = client.get(
        "/api/v1/support-tickets",
        params={"ticketStatus": "submitted", "pageNo": 1, "pageSize": 5},
        headers={"X-User-Id": "1"},
    )
    detail = client.get("/api/v1/support-tickets/1", headers={"X-User-Id": "1"})

    assert created.status_code == 200
    assert created.json()["data"]["ticketStatus"] == "submitted"
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    assert detail.status_code == 200
    assert detail.json()["data"]["ticket"]["ticketContent"] == "内容"


def test_support_ticket_rejects_missing_guest_contact(
    client: TestClient, monkeypatch: Any
) -> None:
    response = client.post(
        "/api/v1/support-tickets",
        json={
            "ticketType": "usage_feedback",
            "relatedType": "none",
            "ticketTitle": "问题",
            "ticketContent": "内容",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "MISSING_CONTACT_INFO"


def test_interaction_success_paths(client: TestClient, monkeypatch: Any) -> None:
    patch_auth_user(monkeypatch)
    monkeypatch.setattr(interactions, "target_exists", lambda target_type, target_id: True)
    monkeypatch.setattr(interactions, "make_no", lambda prefix: f"{prefix}TEST")
    monkeypatch.setattr(interactions, "db_cursor", lambda: fake_db_cursor(FakeCursor()))
    monkeypatch.setattr(
        interactions,
        "fetch_one",
        lambda sql, params=None: {"reaction_status": "cancelled"}
        if "FROM user_reaction" in sql
        else {"id": 10}
        if "FROM content_comment" in sql
        else None,
    )
    monkeypatch.setattr(
        interactions,
        "fetch_all",
        lambda sql, params=None: [
            {
                "id": 10,
                "target_type": "album",
                "target_id": 7,
                "parent_comment_id": None,
                "comment_text": "好听",
                "audit_status": "approved",
                "like_count": 2,
                "created_at": NOW,
                "liked": 1,
                "user_id": 1,
                "nickname": "Alice",
                "avatar_url": None,
            }
        ],
    )
    monkeypatch.setattr(interactions, "count_total", lambda sql, params=None: 1)

    comments = client.get(
        "/api/v1/comments",
        params={"targetType": "album", "targetId": 7},
        headers={"X-User-Id": "1"},
    )
    created = client.post(
        "/api/v1/comments",
        json={"targetType": "album", "targetId": 7, "commentText": "好听"},
        headers={"X-User-Id": "1"},
    )
    rating = client.post(
        "/api/v1/ratings",
        json={"albumId": 7, "ratingScore": "9.5", "ratingText": "不错"},
        headers={"X-User-Id": "1"},
    )
    reaction = client.post(
        "/api/v1/reactions",
        json={"targetType": "comment", "targetId": 10, "reactionType": "like", "reactionStatus": "active"},
        headers={"X-User-Id": "1"},
    )
    report = client.post(
        "/api/v1/reports",
        json={"targetType": "album", "targetId": 7, "reportReason": "spam"},
        headers={"X-User-Id": "1"},
    )

    assert comments.status_code == 200
    assert comments.json()["data"]["list"][0]["liked"] is True
    assert created.status_code == 200
    assert created.json()["data"]["auditStatus"] == "pending"
    assert rating.status_code == 200
    assert rating.json()["data"]["ratingScore"] == 9.5
    assert reaction.status_code == 200
    assert reaction.json()["data"]["reactionStatus"] == "active"
    assert report.status_code == 200
    assert report.json()["data"]["handleStatus"] == "pending"


@pytest.mark.parametrize(
    ("path", "body", "expected_code"),
    [
        ("/api/v1/comments", {"targetType": "album", "targetId": 7, "commentText": " "}, "EMPTY_COMMENT"),
        ("/api/v1/ratings", {"albumId": 7, "ratingScore": "0"}, "INVALID_RATING_SCORE"),
        (
            "/api/v1/reactions",
            {"targetType": "album", "targetId": 7, "reactionType": "bad"},
            "INVALID_REACTION_TYPE",
        ),
        (
            "/api/v1/reports",
            {"targetType": "album", "targetId": 7, "reportReason": "bad"},
            "INVALID_REPORT_REASON",
        ),
    ],
)
def test_interaction_writes_reject_invalid_values(
    client: TestClient,
    monkeypatch: Any,
    path: str,
    body: dict[str, Any],
    expected_code: str,
) -> None:
    patch_auth_user(monkeypatch)

    response = client.post(path, json=body, headers={"X-User-Id": "1"})

    assert response.status_code == 400
    assert response.json()["code"] == expected_code
