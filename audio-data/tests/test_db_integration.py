from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.database import db_cursor, fetch_all, fetch_one
from app.main import app
from app.utils import local_now


def _require_row(row: dict[str, Any] | None, message: str) -> dict[str, Any]:
    assert row is not None, message
    return row


def _execute(sql: str, params: tuple[Any, ...] | None = None) -> None:
    with db_cursor() as (_, cursor):
        cursor.execute(sql, params)


def _delete_by_ids(cursor: Any, table: str, column: str, ids: list[int]) -> None:
    if not ids:
        return
    placeholders = ", ".join(["%s"] * len(ids))
    cursor.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", tuple(ids))


def _query_ids(sql: str, params: tuple[Any, ...]) -> list[int]:
    return [int(row["id"]) for row in fetch_all(sql, params)]


@pytest.fixture
def test_user_factory() -> Iterator[Callable[[], dict[str, Any]]]:
    user_ids: list[int] = []

    def create_user() -> dict[str, Any]:
        channel = _require_row(
            fetch_one("SELECT id FROM dim_channel WHERE yn = 1 ORDER BY id LIMIT 1"),
            "测试库缺少启用渠道",
        )
        unique = uuid4().hex[:12]
        now = local_now()
        with db_cursor() as (_, cursor):
            cursor.execute(
                """
                INSERT INTO user_account (
                    user_no, nickname, register_channel_id, account_status,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, 'normal', %s, %s)
                """,
                (f"TST{unique}", f"测试用户{unique}", channel["id"], now, now),
            )
            user_id = int(cursor.lastrowid)
            cursor.execute(
                """
                INSERT INTO wallet_account (
                    user_id, currency_code, wallet_status,
                    balance_amount, frozen_amount, available_amount,
                    opened_at, created_at, updated_at
                ) VALUES (%s, 'CNY', 'active', 10000.00, 0.00, 10000.00, %s, %s, %s)
                """,
                (user_id, now, now, now),
            )
            wallet_id = int(cursor.lastrowid)
        user_ids.append(user_id)
        return {"user_id": user_id, "wallet_id": wallet_id, "channel_id": int(channel["id"])}

    yield create_user

    for user_id in reversed(user_ids):
        _cleanup_test_user(user_id)


def _cleanup_test_user(user_id: int) -> None:
    order_ids = _query_ids("SELECT id FROM content_order WHERE user_id = %s", (user_id,))
    recharge_ids = _query_ids("SELECT id FROM recharge_order WHERE user_id = %s", (user_id,))
    payment_ids = _query_ids(
        """
        SELECT id
        FROM payment_record
        WHERE (
            pay_subject_type = 'content_order'
            AND pay_subject_id IN (SELECT id FROM content_order WHERE user_id = %s)
        ) OR (
            pay_subject_type = 'recharge_order'
            AND pay_subject_id IN (SELECT id FROM recharge_order WHERE user_id = %s)
        )
        """,
        (user_id, user_id),
    )
    refund_ids = _query_ids(
        f"""
        SELECT id
        FROM refund_record
        WHERE payment_id IN ({", ".join(["%s"] * len(payment_ids))})
        """,
        tuple(payment_ids),
    ) if payment_ids else []
    comment_ids = _query_ids("SELECT id FROM content_comment WHERE user_id = %s", (user_id,))
    report_ids = _query_ids("SELECT id FROM content_report WHERE user_id = %s", (user_id,))
    upload_task_ids = _query_ids(
        """
        SELECT task.id
        FROM content_upload_task task
        JOIN creator_profile creator ON creator.id = task.creator_id
        WHERE creator.user_id = %s
        """,
        (user_id,),
    )

    with db_cursor() as (_, cursor):
        _delete_by_ids(cursor, "refund_record_item", "refund_id", refund_ids)
        _delete_by_ids(cursor, "refund_record", "id", refund_ids)
        _delete_by_ids(cursor, "wallet_ledger", "user_id", [user_id])
        _delete_by_ids(cursor, "entitlement_record", "user_id", [user_id])
        _delete_by_ids(cursor, "payment_record", "id", payment_ids)
        _delete_by_ids(cursor, "content_order_item", "order_id", order_ids)
        _delete_by_ids(cursor, "content_order", "id", order_ids)
        _delete_by_ids(cursor, "recharge_order", "id", recharge_ids)
        _delete_by_ids(cursor, "content_audit_record", "upload_task_id", upload_task_ids)
        _delete_by_ids(cursor, "content_upload_task", "id", upload_task_ids)
        _delete_by_ids(cursor, "play_session", "user_id", [user_id])
        _delete_by_ids(cursor, "listening_progress", "user_id", [user_id])
        _delete_by_ids(cursor, "user_bookshelf", "user_id", [user_id])
        _delete_by_ids(cursor, "user_follow", "user_id", [user_id])
        _delete_by_ids(cursor, "user_reaction", "user_id", [user_id])
        _delete_by_ids(cursor, "content_rating", "user_id", [user_id])
        _delete_by_ids(cursor, "content_report", "id", report_ids)
        _delete_by_ids(cursor, "content_comment", "id", comment_ids)
        _delete_by_ids(cursor, "support_ticket", "user_id", [user_id])
        _delete_by_ids(cursor, "search_query_log", "user_id", [user_id])
        _delete_by_ids(cursor, "wallet_account", "user_id", [user_id])
        _delete_by_ids(cursor, "member_account", "user_id", [user_id])
        _delete_by_ids(cursor, "user_profile", "user_id", [user_id])
        _delete_by_ids(cursor, "user_account", "id", [user_id])


def _paid_album_candidate() -> dict[str, Any]:
    return _require_row(
        fetch_one(
            """
            SELECT a.id AS album_id, t.id AS track_id, pr.album_price_amount
            FROM audio_album a
            JOIN audio_track t
              ON t.album_id = a.id AND t.track_status = 'published'
            JOIN album_price_rule pr
              ON pr.album_id = a.id
             AND pr.yn = 1
             AND pr.price_type = 'album_paid'
             AND pr.effective_from <= NOW()
             AND (pr.effective_to IS NULL OR pr.effective_to > NOW())
            WHERE a.album_status = 'published'
            ORDER BY a.id DESC, t.track_no
            LIMIT 1
            """
        ),
        "测试库缺少可购买的已发布付费专辑和章节",
    )


def _create_paid_order(client: TestClient, user_id: int) -> dict[str, Any]:
    candidate = _paid_album_candidate()
    order_body = {
        "orderType": "album",
        "items": [{"itemType": "album", "albumId": candidate["album_id"]}],
    }
    preview = client.post(
        "/api/v1/orders/preview",
        json=order_body,
        headers={"X-User-Id": str(user_id)},
    )
    assert preview.status_code == 200
    created = client.post(
        "/api/v1/orders",
        json=order_body,
        headers={"X-User-Id": str(user_id)},
    )
    assert created.status_code == 200
    data = created.json()["data"]
    return {
        "album_id": int(candidate["album_id"]),
        "track_id": int(candidate["track_id"]),
        "amount": Decimal(str(data["order"]["payableAmount"])),
        "order_id": int(data["order"]["orderId"]),
        "order_item_id": int(data["items"][0]["itemId"]),
    }


def _create_payment(
    client: TestClient, user_id: int, order_id: int, payment_channel: str
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/payments",
        json={
            "paySubjectType": "content_order",
            "paySubjectId": order_id,
            "paymentChannel": payment_channel,
        },
        headers={"X-User-Id": str(user_id)},
    )
    assert response.status_code == 200
    payment = response.json()["data"]["payment"]
    return {"payment_id": int(payment["paymentId"]), "payment_no": payment["paymentNo"]}


def _notify_payment(payment_no: str) -> tuple[int, dict[str, Any]]:
    with TestClient(app) as thread_client:
        response = thread_client.post(
            "/api/v1/payment-notifications/mock",
            json={"paymentNo": payment_no, "paymentStatus": "success"},
            headers={"X-Demo-Payment-Signature": "mock-payment-signature"},
        )
    return response.status_code, response.json()


def test_database_connection_schema_constraints_and_seed_data() -> None:
    row = _require_row(fetch_one("SELECT DATABASE() AS db_name"), "无法连接测试数据库")
    assert row["db_name"] == "audio"

    required_tables = {
        "user_account",
        "audio_album",
        "audio_track",
        "album_price_rule",
        "content_order",
        "content_order_item",
        "payment_record",
        "refund_record",
        "refund_record_item",
        "entitlement_record",
        "wallet_account",
        "wallet_ledger",
        "play_session",
        "listening_progress",
    }
    tables = {
        row["TABLE_NAME"]
        for row in fetch_all(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = DATABASE()
            """
        )
    }
    assert required_tables <= tables

    columns = {
        (row["TABLE_NAME"], row["COLUMN_NAME"])
        for row in fetch_all(
            """
            SELECT TABLE_NAME, COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
            """
        )
    }
    for required in {
        ("content_order_item", "item_target_key"),
        ("entitlement_record", "source_key"),
        ("wallet_account", "available_amount"),
        ("payment_record", "payment_status"),
        ("refund_record", "refund_status"),
    }:
        assert required in columns

    indexes = {
        (row["TABLE_NAME"], row["INDEX_NAME"])
        for row in fetch_all(
            """
            SELECT TABLE_NAME, INDEX_NAME
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
            """
        )
    }
    for required in {
        ("user_account", "uk_user_account_no"),
        ("wallet_account", "uk_wallet_account_user_currency"),
        ("payment_record", "uk_payment_record_no"),
        ("refund_record_item", "uk_refund_record_item_order_item"),
        ("entitlement_record", "uk_entitlement_record_key"),
    }:
        assert required in indexes

    constraints = {
        (row["TABLE_NAME"], row["CONSTRAINT_NAME"])
        for row in fetch_all(
            """
            SELECT TABLE_NAME, CONSTRAINT_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
            WHERE TABLE_SCHEMA = DATABASE()
            """
        )
    }
    for required in {
        ("wallet_account", "ck_wallet_account_amount"),
        ("payment_record", "ck_payment_record_channel"),
        ("content_order_item", "ck_content_order_item_target"),
    }:
        assert required in constraints

    for table in ["user_account", "audio_album", "audio_track", "vip_plan", "dim_channel"]:
        count = _require_row(
            fetch_one(f"SELECT COUNT(*) AS total FROM {table}"),
            f"无法统计 {table}",
        )
        assert int(count["total"]) > 0


def test_openapi_routes_match_readme_contract() -> None:
    actual_routes = {
        (next(iter(route.methods - {"HEAD", "OPTIONS"})), route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
    }
    readme_text = Path("README.md").read_text(encoding="utf-8")
    documented_routes = set(re.findall(r"####\s+\d+(?:\.\d+)+\s+`(GET|POST|PATCH|PUT|DELETE)\s+([^`]+)`", readme_text))

    assert documented_routes == actual_routes


def test_public_read_apis_work_against_real_database(
    client: TestClient, test_user_factory: Callable[[], dict[str, Any]]
) -> None:
    user = test_user_factory()
    user_headers = {"X-User-Id": str(user["user_id"])}
    album = _require_row(
        fetch_one("SELECT id, album_title FROM audio_album WHERE album_status = 'published' LIMIT 1"),
        "测试库缺少已发布专辑",
    )
    track = _require_row(
        fetch_one(
            """
            SELECT t.id
            FROM audio_track t
            JOIN audio_album a ON a.id = t.album_id
            WHERE t.track_status = 'published'
              AND a.album_status = 'published'
            LIMIT 1
            """
        ),
        "测试库缺少已发布章节",
    )
    narrator = _require_row(
        fetch_one("SELECT id FROM content_narrator WHERE yn = 1 LIMIT 1"),
        "测试库缺少主播",
    )
    topic = _require_row(
        fetch_one("SELECT id FROM content_topic WHERE topic_status = 'published' LIMIT 1"),
        "测试库缺少已发布专题",
    )
    slot = _require_row(
        fetch_one("SELECT slot_code FROM recommend_slot WHERE yn = 1 LIMIT 1"),
        "测试库缺少启用推荐位",
    )
    channel = _require_row(
        fetch_one("SELECT id FROM dim_channel WHERE yn = 1 LIMIT 1"),
        "测试库缺少启用渠道",
    )

    requests = [
        client.get("/api/v1/categories"),
        client.get("/api/v1/tags"),
        client.get("/api/v1/albums", params={"pageNo": 1, "pageSize": 3}),
        client.get(f"/api/v1/albums/{album['id']}"),
        client.get(f"/api/v1/albums/{album['id']}/tracks", params={"pageSize": 3}),
        client.get(f"/api/v1/tracks/{track['id']}"),
        client.get(f"/api/v1/narrators/{narrator['id']}"),
        client.get("/api/v1/rankings"),
        client.get("/api/v1/topics", params={"pageSize": 3}),
        client.get(f"/api/v1/topics/{topic['id']}"),
        client.get(f"/api/v1/recommend-slots/{slot['slot_code']}/items"),
        client.get("/api/v1/vip-plans"),
        client.get(
            "/api/v1/search",
            params={
                "keyword": str(album["album_title"])[:6],
                "channelId": channel["id"],
                "searchType": "album",
                "pageSize": 3,
            },
            headers=user_headers,
        ),
        client.get("/api/v1/search/hot-keywords", params={"limit": 5}),
        client.get("/api/v1/search/suggestions", params={"keyword": str(album["album_title"])[:1]}),
    ]

    for response in requests:
        assert response.status_code == 200
        assert response.json()["code"] == 0


def test_user_trade_play_refund_wallet_flow_against_real_database(
    client: TestClient, test_user_factory: Callable[[], dict[str, Any]]
) -> None:
    user = test_user_factory()
    user_id = int(user["user_id"])

    me = client.get("/api/v1/me", headers={"X-User-Id": str(user_id)})
    assert me.status_code == 200
    assert me.json()["data"]["wallet"]["availableAmount"] == 10000.0

    order = _create_paid_order(client, user_id)
    payment = _create_payment(client, user_id, order["order_id"], "balance")

    paid = client.post(
        "/api/v1/payment-notifications/mock",
        json={"paymentNo": payment["payment_no"], "paymentStatus": "success"},
        headers={"X-Demo-Payment-Signature": "mock-payment-signature"},
    )
    assert paid.status_code == 200
    assert paid.json()["data"]["subject"]["subjectStatus"] == "paid"

    entitlements = client.get(
        "/api/v1/entitlements",
        params={"targetType": "album", "entitlementStatus": "active"},
        headers={"X-User-Id": str(user_id)},
    )
    assert entitlements.status_code == 200
    assert any(
        item["targetId"] == order["album_id"]
        for item in entitlements.json()["data"]["entitlements"]
    )

    session = client.post(
        "/api/v1/play-sessions",
        json={"trackId": order["track_id"], "startPositionSeconds": 0},
        headers={"X-User-Id": str(user_id)},
    )
    assert session.status_code == 200
    session_id = session.json()["data"]["sessionId"]
    finished = client.patch(
        f"/api/v1/play-sessions/{session_id}",
        json={"endPositionSeconds": 1, "playedSeconds": 1, "playStatus": "completed"},
        headers={"X-User-Id": str(user_id)},
    )
    assert finished.status_code == 200
    progress = client.get(
        "/api/v1/listening-progress",
        params={"trackId": order["track_id"]},
        headers={"X-User-Id": str(user_id)},
    )
    assert progress.status_code == 200
    assert progress.json()["data"]["total"] >= 1

    refund = client.post(
        "/api/v1/refunds",
        json={
            "paymentId": payment["payment_id"],
            "items": [
                {
                    "orderItemId": order["order_item_id"],
                    "refundQuantity": 1,
                    "refundAmount": str(order["amount"]),
                }
            ],
        },
        headers={"X-User-Id": str(user_id)},
    )
    assert refund.status_code == 200
    refund_no = refund.json()["data"]["refund"]["refundNo"]
    refunded = client.post(
        "/api/v1/refund-notifications/mock",
        json={"refundNo": refund_no, "refundStatus": "success"},
        headers={"X-Demo-Payment-Signature": "mock-payment-signature"},
    )
    assert refunded.status_code == 200
    assert refunded.json()["data"]["refund"]["refundStatus"] == "success"

    ledgers = client.get(
        "/api/v1/wallet/ledgers",
        params={"pageSize": 10},
        headers={"X-User-Id": str(user_id)},
    )
    assert ledgers.status_code == 200
    ledger_types = {item["ledgerType"] for item in ledgers.json()["data"]["list"]}
    assert {"consume", "refund"} <= ledger_types


def test_concurrent_payment_notification_debits_balance_once(
    client: TestClient, test_user_factory: Callable[[], dict[str, Any]]
) -> None:
    user = test_user_factory()
    user_id = int(user["user_id"])
    order = _create_paid_order(client, user_id)
    payment = _create_payment(client, user_id, order["order_id"], "balance")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _notify_payment(payment["payment_no"]), range(4)))

    assert {status for status, _ in results} == {200}
    ledger = _require_row(
        fetch_one(
            """
            SELECT COUNT(*) AS total, COALESCE(SUM(amount_delta), 0) AS delta
            FROM wallet_ledger
            WHERE user_id = %s
              AND ledger_type = 'consume'
              AND related_type = 'content_order'
              AND related_id = %s
            """,
            (user_id, order["order_id"]),
        ),
        "无法统计钱包扣款流水",
    )
    assert int(ledger["total"]) == 1
    assert Decimal(ledger["delta"]) == -order["amount"]


def test_concurrent_full_refund_requests_only_create_one_refund(
    client: TestClient, test_user_factory: Callable[[], dict[str, Any]]
) -> None:
    user = test_user_factory()
    user_id = int(user["user_id"])
    order = _create_paid_order(client, user_id)
    payment = _create_payment(client, user_id, order["order_id"], "alipay")
    assert _notify_payment(payment["payment_no"])[0] == 200

    def request_refund(_: int) -> tuple[int, dict[str, Any]]:
        with TestClient(app) as thread_client:
            response = thread_client.post(
                "/api/v1/refunds",
                json={
                    "paymentId": payment["payment_id"],
                    "items": [
                        {
                            "orderItemId": order["order_item_id"],
                            "refundQuantity": 1,
                            "refundAmount": str(order["amount"]),
                        }
                    ],
                },
                headers={"X-User-Id": str(user_id)},
            )
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request_refund, range(2)))

    assert sorted(status for status, _ in results) == [200, 400]
    refund_count = _require_row(
        fetch_one(
            """
            SELECT COUNT(*) AS total
            FROM refund_record
            WHERE payment_id = %s
              AND refund_status IN ('requested', 'approved', 'success')
            """,
            (payment["payment_id"],),
        ),
        "无法统计退款单",
    )
    assert int(refund_count["total"]) == 1


def test_cross_user_permission_matrix_against_real_database(
    client: TestClient, test_user_factory: Callable[[], dict[str, Any]]
) -> None:
    owner = test_user_factory()
    stranger = test_user_factory()
    owner_id = int(owner["user_id"])
    stranger_id = int(stranger["user_id"])
    order = _create_paid_order(client, owner_id)
    ticket = client.post(
        "/api/v1/support-tickets",
        json={
            "ticketType": "payment_issue",
            "relatedType": "content_order",
            "relatedId": order["order_id"],
            "ticketTitle": "支付问题",
            "ticketContent": "需要处理",
        },
        headers={"X-User-Id": str(owner_id)},
    )
    assert ticket.status_code == 200
    ticket_id = ticket.json()["data"]["ticketId"]

    cases = [
        client.get(f"/api/v1/orders/{order['order_id']}", headers={"X-User-Id": str(stranger_id)}),
        client.post(
            "/api/v1/payments",
            json={
                "paySubjectType": "content_order",
                "paySubjectId": order["order_id"],
                "paymentChannel": "alipay",
            },
            headers={"X-User-Id": str(stranger_id)},
        ),
        client.post(
            "/api/v1/recharge-orders",
            json={
                "walletId": owner["wallet_id"],
                "rechargeAmount": "10.00",
                "paymentChannel": "alipay",
            },
            headers={"X-User-Id": str(stranger_id)},
        ),
        client.get(f"/api/v1/support-tickets/{ticket_id}", headers={"X-User-Id": str(stranger_id)}),
    ]

    assert [response.status_code for response in cases] == [404, 404, 404, 404]

    creator_case = fetch_one(
        """
        SELECT owner_task.id AS upload_task_id, other_creator.user_id AS other_user_id
        FROM content_upload_task owner_task
        JOIN creator_profile owner_creator ON owner_creator.id = owner_task.creator_id
        JOIN creator_profile other_creator
          ON other_creator.id <> owner_creator.id
         AND other_creator.yn = 1
        WHERE owner_creator.yn = 1
        LIMIT 1
        """
    )
    if creator_case is not None:
        response = client.get(
            f"/api/v1/upload-tasks/{creator_case['upload_task_id']}",
            headers={"X-User-Id": str(creator_case["other_user_id"])},
        )
        assert response.status_code == 404
