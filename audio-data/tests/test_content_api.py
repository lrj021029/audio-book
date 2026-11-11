from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from helpers import NOW

from app.routers import content


def test_categories_returns_tree(
    client: TestClient, monkeypatch: Any
) -> None:
    rows = [
        {
            "id": 1,
            "parent_id": None,
            "category_code": "book",
            "category_name": "有声书",
            "category_level": 1,
            "category_type": "audiobook",
            "sort_no": 1,
        },
        {
            "id": 2,
            "parent_id": 1,
            "category_code": "fiction",
            "category_name": "小说",
            "category_level": 2,
            "category_type": "audiobook",
            "sort_no": 1,
        },
    ]

    def fake_fetch_all(sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        assert "FROM dim_audio_category" in sql
        assert params == ()
        return rows

    monkeypatch.setattr(content, "fetch_all", fake_fetch_all)

    response = client.get("/api/v1/categories")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["categories"] == [
        {
            "categoryId": 1,
            "categoryCode": "book",
            "categoryName": "有声书",
            "categoryLevel": 1,
            "categoryType": "audiobook",
            "children": [
                {
                    "categoryId": 2,
                    "categoryCode": "fiction",
                    "categoryName": "小说",
                    "categoryLevel": 2,
                    "categoryType": "audiobook",
                    "children": [],
                }
            ],
        }
    ]


def test_tags_applies_type_filter(
    client: TestClient, monkeypatch: Any
) -> None:
    rows = [
        {
            "id": 10,
            "parent_id": None,
            "tag_code": "genre",
            "tag_name": "题材",
            "tag_type": "genre",
            "sort_no": 1,
        },
        {
            "id": 11,
            "parent_id": 10,
            "tag_code": "suspense",
            "tag_name": "悬疑",
            "tag_type": "genre",
            "sort_no": 1,
        },
    ]

    def fake_fetch_all(sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        assert "FROM dim_content_tag" in sql
        assert params == ("genre",)
        return rows

    monkeypatch.setattr(content, "fetch_all", fake_fetch_all)

    response = client.get("/api/v1/tags", params={"tagType": "genre"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["tags"][0]["tagCode"] == "genre"
    assert payload["data"]["tags"][0]["children"][0]["tagCode"] == "suspense"


def test_invalid_user_header(client: TestClient) -> None:
    response = client.get("/api/v1/me", headers={"X-User-Id": "abc"})

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_USER_ID"


def test_content_lists_cover_filters_pagination_and_empty(
    client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setattr(content, "count_total", lambda sql, params=None: 0)
    monkeypatch.setattr(content, "fetch_all", lambda sql, params=None: [])
    monkeypatch.setattr(
        content,
        "fetch_album_base",
        lambda album_id: {"id": album_id, "album_status": "published"},
    )
    monkeypatch.setattr(content, "current_price_rule", lambda album_id: None)

    albums = client.get(
        "/api/v1/albums",
        params={
            "categoryId": 1,
            "tagId": 2,
            "albumType": "audiobook",
            "priceType": "free",
            "publishStatus": "completed",
            "pageNo": 2,
            "pageSize": 5,
        },
    )
    tracks = client.get(
        "/api/v1/albums/7/tracks",
        params={"sort": "desc", "pageNo": 2, "pageSize": 5},
    )
    topics = client.get(
        "/api/v1/topics",
        params={"topicType": "editor_pick", "pageNo": 2, "pageSize": 5},
    )

    assert albums.status_code == 200
    assert albums.json()["data"] == {"list": [], "pageNo": 2, "pageSize": 5, "total": 0}
    assert tracks.status_code == 200
    assert tracks.json()["data"] == {"list": [], "pageNo": 2, "pageSize": 5, "total": 0}
    assert topics.status_code == 200
    assert topics.json()["data"] == {"list": [], "pageNo": 2, "pageSize": 5, "total": 0}


def test_recommend_items_success(client: TestClient, monkeypatch: Any) -> None:
    def fake_fetch_one(sql: str, params: tuple[Any, ...] | None = None) -> dict[str, Any] | None:
        if "FROM recommend_slot" in sql:
            return {
                "id": 1,
                "slot_code": "home",
                "slot_name": "首页推荐",
                "slot_type": "home",
                "max_item_count": 5,
            }
        if "FROM audio_album" in sql:
            return {"cover_url": "https://example.com/cover.jpg"}
        return None

    monkeypatch.setattr(content, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(content, "target_name", lambda target_type, target_id: "专辑")
    monkeypatch.setattr(
        content,
        "fetch_all",
        lambda sql, params=None: [
            {
                "id": 10,
                "target_type": "album",
                "target_id": 7,
                "title": None,
                "image_url": None,
                "jump_url": None,
                "sort_no": 1,
                "effective_from": NOW,
            }
        ],
    )

    response = client.get("/api/v1/recommend-slots/home/items")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["slot"]["slotCode"] == "home"
    assert data["items"][0]["title"] == "专辑"
