from __future__ import annotations

from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import app

API_ROUTE_CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("GET", "/api/v1/categories", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/tags", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/albums", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/albums/1", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/albums/1/tracks", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/tracks/1", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/narrators/1", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/rankings", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/topics", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/topics/1", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/recommend-slots/home/items", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/search", {}),
    ("POST", "/api/v1/search/clicks", {"json": {}}),
    ("GET", "/api/v1/search/hot-keywords", {"params": {"days": 0}}),
    ("GET", "/api/v1/search/suggestions", {}),
    ("POST", "/api/v1/tracks/1/play-url", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/play-sessions", {"headers": {"X-User-Id": "abc"}}),
    ("PATCH", "/api/v1/play-sessions/1", {"headers": {"X-User-Id": "abc"}}),
    ("PUT", "/api/v1/listening-progress", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/listening-progress", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/bookshelf", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/bookshelf", {"headers": {"X-User-Id": "abc"}}),
    ("DELETE", "/api/v1/bookshelf/1", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/follows", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/follows", {"headers": {"X-User-Id": "abc"}}),
    ("DELETE", "/api/v1/follows", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/comments", {}),
    ("POST", "/api/v1/comments", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/ratings", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/reactions", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/reports", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/vip-plans", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/entitlements", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/orders/preview", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/orders", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/orders", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/orders/1", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/payments", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/payment-notifications/mock", {"json": {}}),
    ("POST", "/api/v1/refunds", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/refund-notifications/mock", {"json": {}}),
    ("GET", "/api/v1/refunds", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/wallet", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/wallet/ledgers", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/recharge-orders", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/me", {"headers": {"X-User-Id": "abc"}}),
    ("PATCH", "/api/v1/me/profile", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/messages", {"headers": {"X-User-Id": "abc"}}),
    ("PATCH", "/api/v1/messages/1/read", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/support-tickets", {"json": {}}),
    ("GET", "/api/v1/support-tickets", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/support-tickets/1", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/creator-profile", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/creator-applications", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/creator-applications", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/creator/albums", {"headers": {"X-User-Id": "abc"}}),
    ("PATCH", "/api/v1/creator/albums/1", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/upload-tasks", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/upload-tasks", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/upload-tasks/1", {"headers": {"X-User-Id": "abc"}}),
    ("POST", "/api/v1/content-audits", {"headers": {"X-User-Id": "abc"}}),
    ("GET", "/api/v1/content-audits", {"headers": {"X-User-Id": "abc"}}),
    (
        "POST",
        "/api/v1/creator/albums/1/publish-actions",
        {"headers": {"X-User-Id": "abc"}},
    ),
]


def test_all_api_routes_have_coverage_cases() -> None:
    actual_routes = {
        (next(iter(route.methods - {"HEAD", "OPTIONS"})), route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
    }
    covered_routes = {
        (method, _normalize_path(path)) for method, path, _ in API_ROUTE_CASES
    }

    assert covered_routes == actual_routes


@pytest.mark.parametrize(("method", "path", "kwargs"), API_ROUTE_CASES)
def test_api_route_is_reachable(
    client: TestClient, method: str, path: str, kwargs: dict[str, Any]
) -> None:
    response = client.request(method, path, **kwargs)

    assert response.status_code in {400, 401, 422}
    assert response.status_code not in {404, 405, 500}


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("POST", "/api/v1/play-sessions", {"trackId": 1}),
        ("PATCH", "/api/v1/play-sessions/1", {"endPositionSeconds": 1, "playedSeconds": 1, "playStatus": "completed"}),
        ("PUT", "/api/v1/listening-progress", {"trackId": 1, "positionSeconds": 1}),
        ("POST", "/api/v1/bookshelf", {"albumId": 1}),
        ("DELETE", "/api/v1/bookshelf/1", None),
        ("POST", "/api/v1/follows", {"targetType": "narrator", "targetId": 1}),
        ("DELETE", "/api/v1/follows", {"targetType": "narrator", "targetId": 1}),
        ("POST", "/api/v1/comments", {"targetType": "album", "targetId": 1, "commentText": "ok"}),
        ("POST", "/api/v1/ratings", {"albumId": 1, "ratingScore": "8"}),
        ("POST", "/api/v1/reactions", {"targetType": "album", "targetId": 1, "reactionType": "like"}),
        ("POST", "/api/v1/reports", {"targetType": "album", "targetId": 1, "reportReason": "spam"}),
        ("POST", "/api/v1/orders/preview", {"orderType": "album", "items": [{"itemType": "album", "albumId": 1}]}),
        ("POST", "/api/v1/orders", {"orderType": "album", "items": [{"itemType": "album", "albumId": 1}]}),
        ("POST", "/api/v1/payments", {"paySubjectType": "content_order", "paySubjectId": 1, "paymentChannel": "alipay"}),
        ("POST", "/api/v1/refunds", {"paymentId": 1, "items": [{"orderItemId": 1, "refundAmount": "1"}]}),
        ("POST", "/api/v1/recharge-orders", {"walletId": 1, "rechargeAmount": "1", "paymentChannel": "alipay"}),
        ("PATCH", "/api/v1/me/profile", {"nickname": "Alice"}),
        ("PATCH", "/api/v1/messages/1/read", None),
        ("POST", "/api/v1/creator-applications", {"applyType": "creator_settle"}),
        ("POST", "/api/v1/creator/albums", {"albumTitle": "A", "albumType": "audiobook", "categoryId": 1, "languageId": 1}),
        ("PATCH", "/api/v1/creator/albums/1", {"albumTitle": "A"}),
        ("POST", "/api/v1/upload-tasks", {"uploadType": "album"}),
        ("POST", "/api/v1/content-audits", {"targetType": "album", "targetId": 1}),
        ("POST", "/api/v1/creator/albums/1/publish-actions", {"action": "submit_review"}),
    ],
)
def test_protected_write_routes_require_auth(
    client: TestClient, method: str, path: str, json_body: dict[str, Any] | None
) -> None:
    response = client.request(method, path, json=json_body, headers={"X-User-Id": ""})

    assert response.status_code == 401
    assert response.json()["code"] == "MISSING_USER_ID"


def _normalize_path(path: str) -> str:
    parts = path.split("/")
    normalized = []
    for index, part in enumerate(parts):
        if part in {"1", "home"}:
            previous = parts[index - 1] if index else ""
            if previous in {
                "albums",
                "tracks",
                "narrators",
                "topics",
                "bookshelf",
                "orders",
                "play-sessions",
                "messages",
                "support-tickets",
                "upload-tasks",
            }:
                normalized.append("{" + _param_name(previous) + "}")
            elif previous == "recommend-slots":
                normalized.append("{slotCode}")
            else:
                normalized.append(part)
        else:
            normalized.append(part)
    return "/".join(normalized)


def _param_name(path_part: str) -> str:
    return {
        "albums": "albumId",
        "tracks": "trackId",
        "narrators": "narratorId",
        "topics": "topicId",
        "bookshelf": "albumId",
        "orders": "orderId",
        "play-sessions": "sessionId",
        "messages": "messageId",
        "support-tickets": "ticketId",
        "upload-tasks": "uploadTaskId",
    }[path_part]
