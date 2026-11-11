from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import NOW, FakeCursor, fake_db_cursor, patch_auth_user

from app.routers import library, playback, search


def test_search_success_logs_request(client: TestClient, monkeypatch: Any) -> None:
    inserted: list[tuple[str, tuple[Any, ...]]] = []

    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM dim_channel" in sql:
            return {"id": 1}
        return None

    def fake_fetch_all(sql: str, params: Any | None = None) -> list[dict[str, Any]]:
        if "FROM audio_album" in sql:
            return [
                {
                    "id": 7,
                    "album_code": "ALB7",
                    "album_title": "Python 入门",
                    "album_type": "audiobook",
                    "cover_url": "https://example.com/cover.jpg",
                    "summary": "课程",
                    "category_name": "教育",
                    "language_code": "zh-CN",
                    "publish_status": "completed",
                    "track_count": 8,
                    "play_count": 100,
                    "favorite_count": 10,
                    "rating_score": 9.5,
                }
            ]
        return []

    def on_execute(sql: str, params: tuple[Any, ...], cursor: FakeCursor) -> None:
        inserted.append((sql, params))

    monkeypatch.setattr(search, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(search, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(search, "count_total", lambda sql, params=None: 1)
    monkeypatch.setattr(search, "db_cursor", lambda: fake_db_cursor(FakeCursor(on_execute)))
    monkeypatch.setattr(search, "make_no", lambda prefix: f"{prefix}TEST")
    monkeypatch.setattr(search, "current_price_rule", lambda album_id: None, raising=False)

    response = client.get(
        "/api/v1/search",
        params={"keyword": "Python", "channelId": 1, "searchType": "album", "pageNo": 2, "pageSize": 1},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["requestNo"] == "SRCHTEST"
    assert payload["pageNo"] == 2
    assert payload["pageSize"] == 1
    assert payload["total"] == 1
    assert payload["list"][0]["targetType"] == "album"
    assert inserted


def test_search_rejects_invalid_sort(client: TestClient, monkeypatch: Any) -> None:
    response = client.get(
        "/api/v1/search",
        params={"keyword": "Python", "channelId": 1, "sortBy": "bad"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_SORT_BY"


def test_search_click_success(client: TestClient, monkeypatch: Any) -> None:
    patch_auth_user(monkeypatch)
    cursor = FakeCursor()
    monkeypatch.setattr(search, "target_exists", lambda target_type, target_id: True)
    monkeypatch.setattr(
        search,
        "fetch_one",
        lambda sql, params=None: {"query_no": "SRCH001", "user_id": 1}
        if "FROM search_query_log" in sql
        else None,
    )
    monkeypatch.setattr(search, "db_cursor", lambda: fake_db_cursor(cursor))

    response = client.post(
        "/api/v1/search/clicks",
        json={
            "requestNo": "SRCH001",
            "clickedTargetType": "album",
            "clickedTargetId": 7,
        },
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["clickedFlag"] == 1
    assert cursor.executed


def test_search_click_rejects_user_mismatch(client: TestClient, monkeypatch: Any) -> None:
    patch_auth_user(monkeypatch)
    monkeypatch.setattr(search, "target_exists", lambda target_type, target_id: True)
    monkeypatch.setattr(
        search,
        "fetch_one",
        lambda sql, params=None: {"query_no": "SRCH001", "user_id": 2},
    )

    response = client.post(
        "/api/v1/search/clicks",
        json={
            "requestNo": "SRCH001",
            "clickedTargetType": "album",
            "clickedTargetId": 7,
        },
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "SEARCH_QUERY_USER_MISMATCH"


def test_hot_keywords_and_suggestions_cover_empty_and_filter(
    client: TestClient, monkeypatch: Any
) -> None:
    calls: list[tuple[str, tuple[Any, ...] | None]] = []

    def fake_fetch_all(sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        calls.append((sql, params))
        if "FROM search_keyword_stat" in sql and "GROUP BY keyword" in sql and params == (7, 1, 3):
            return [
                {
                    "keyword": "Python",
                    "search_count": 10,
                    "result_click_count": 4,
                    "album_click_count": 3,
                    "narrator_click_count": 1,
                    "latest_stat_date": datetime(2026, 6, 13).date(),
                }
            ]
        return []

    monkeypatch.setattr(search, "fetch_all", fake_fetch_all)

    hot = client.get("/api/v1/search/hot-keywords", params={"channelId": 1, "limit": 3})
    suggestions = client.get("/api/v1/search/suggestions", params={"keyword": "none"})

    assert hot.status_code == 200
    assert hot.json()["data"]["keywords"][0]["keyword"] == "Python"
    assert suggestions.status_code == 200
    assert suggestions.json()["data"]["suggestions"] == []
    assert len(calls) >= 3


def test_play_url_success_for_free_track(client: TestClient, monkeypatch: Any) -> None:
    track = {
        "id": 11,
        "album_id": 7,
        "track_status": "published",
        "album_status": "published",
        "free_flag": 1,
        "track_no": 1,
        "trial_seconds": 0,
    }
    monkeypatch.setattr(playback, "fetch_track_base", lambda track_id: track)
    monkeypatch.setattr(playback, "current_price_rule", lambda album_id: {"price_type": "free"})
    monkeypatch.setattr(
        playback,
        "fetch_one",
        lambda sql, params=None: {
            "id": 99,
            "file_format": "mp3",
            "bitrate_kbps": 64,
            "sample_rate_hz": 44100,
            "duration_seconds": 300,
            "file_url": "https://example.com/track.mp3",
        },
    )

    response = client.post(
        "/api/v1/tracks/11/play-url",
        json={"fileFormat": "mp3", "bitrateKbps": 64},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["canPlay"] is True
    assert data["audioFile"]["fileUrl"].endswith(".mp3")


def test_play_session_create_update_and_progress(
    client: TestClient, monkeypatch: Any
) -> None:
    patch_auth_user(monkeypatch)
    track = {
        "id": 11,
        "album_id": 7,
        "track_status": "published",
        "album_status": "published",
        "duration_seconds": 100,
        "free_flag": 1,
        "track_no": 1,
        "trial_seconds": 0,
    }
    progress_row = {
        "track_id": 11,
        "album_id": 7,
        "album_title": "Python 入门",
        "track_title": "第一章",
        "position_seconds": 90,
        "duration_seconds": 100,
        "finished_flag": 1,
        "last_played_at": NOW,
        "updated_at": NOW,
    }

    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM dim_channel" in sql:
            return {"id": 1}
        if "FROM play_session" in sql:
            return {"id": 1, "user_id": 1, "album_id": 7, "track_id": 11}
        if "FROM listening_progress" in sql:
            return progress_row
        return None

    monkeypatch.setattr(playback, "fetch_track_base", lambda track_id: track)
    monkeypatch.setattr(playback, "current_price_rule", lambda album_id: {"price_type": "free"})
    monkeypatch.setattr(playback, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(playback, "db_cursor", lambda: fake_db_cursor(FakeCursor()))
    monkeypatch.setattr(playback, "make_no", lambda prefix: f"{prefix}TEST")

    created = client.post(
        "/api/v1/play-sessions",
        json={"trackId": 11, "startPositionSeconds": 5},
        headers={"X-User-Id": "1"},
    )
    updated = client.patch(
        "/api/v1/play-sessions/1",
        json={"endPositionSeconds": 90, "playedSeconds": 85, "playStatus": "completed"},
        headers={"X-User-Id": "1"},
    )
    progress = client.put(
        "/api/v1/listening-progress",
        json={"trackId": 11, "positionSeconds": 90, "durationSeconds": 100, "finishedFlag": True},
        headers={"X-User-Id": "1"},
    )

    assert created.status_code == 200
    assert created.json()["data"]["sessionNo"] == "PLYTEST"
    assert updated.status_code == 200
    assert updated.json()["data"]["finishedFlag"] is True
    assert progress.status_code == 200
    assert progress.json()["data"]["finishedFlag"] is True


def test_play_session_rejects_position_after_duration(
    client: TestClient, monkeypatch: Any
) -> None:
    patch_auth_user(monkeypatch)
    monkeypatch.setattr(
        playback,
        "fetch_track_base",
        lambda track_id: {
            "id": 11,
            "album_id": 7,
            "track_status": "published",
            "album_status": "published",
            "duration_seconds": 100,
            "free_flag": 1,
            "track_no": 1,
            "trial_seconds": 0,
        },
    )
    monkeypatch.setattr(playback, "current_price_rule", lambda album_id: {"price_type": "free"})

    response = client.post(
        "/api/v1/play-sessions",
        json={"trackId": 11, "startPositionSeconds": 101},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_START_POSITION"


def test_listening_progress_list_filters_and_empty(
    client: TestClient, monkeypatch: Any
) -> None:
    patch_auth_user(monkeypatch)
    monkeypatch.setattr(playback, "count_total", lambda sql, params=None: 0)
    monkeypatch.setattr(playback, "fetch_all", lambda sql, params=None: [])

    response = client.get(
        "/api/v1/listening-progress",
        params={"albumId": 7, "trackId": 11, "pageNo": 2, "pageSize": 5},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"list": [], "pageNo": 2, "pageSize": 5, "total": 0}


def test_bookshelf_and_follow_success_paths(client: TestClient, monkeypatch: Any) -> None:
    patch_auth_user(monkeypatch)
    monkeypatch.setattr(
        library,
        "fetch_album_base",
        lambda album_id: {"id": album_id, "album_status": "published"},
    )
    monkeypatch.setattr(library, "target_exists", lambda target_type, target_id: True)
    monkeypatch.setattr(library, "target_name", lambda target_type, target_id: "主播")
    monkeypatch.setattr(library, "db_cursor", lambda: fake_db_cursor(FakeCursor()))

    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM user_bookshelf" in sql:
            return {"id": 5}
        if "FROM user_follow" in sql:
            return {"id": 9}
        return None

    monkeypatch.setattr(library, "fetch_one", fake_fetch_one)

    add = client.post(
        "/api/v1/bookshelf",
        json={"albumId": 7, "shelfStatus": "favorited"},
        headers={"X-User-Id": "1"},
    )
    remove = client.delete("/api/v1/bookshelf/7", headers={"X-User-Id": "1"})
    follow = client.post(
        "/api/v1/follows",
        json={"targetType": "narrator", "targetId": 3},
        headers={"X-User-Id": "1"},
    )
    unfollow = client.request(
        "DELETE",
        "/api/v1/follows",
        json={"targetType": "narrator", "targetId": 3},
        headers={"X-User-Id": "1"},
    )

    assert add.status_code == 200
    assert add.json()["data"]["bookshelfId"] == 5
    assert remove.status_code == 200
    assert remove.json()["data"]["shelfStatus"] == "removed"
    assert follow.status_code == 200
    assert follow.json()["data"]["followStatus"] == "following"
    assert unfollow.status_code == 200
    assert unfollow.json()["data"]["followStatus"] == "cancelled"


def test_bookshelf_and_follow_list_filters_empty(
    client: TestClient, monkeypatch: Any
) -> None:
    patch_auth_user(monkeypatch)
    monkeypatch.setattr(library, "count_total", lambda sql, params=None: 0)
    monkeypatch.setattr(library, "fetch_all", lambda sql, params=None: [])

    bookshelf = client.get(
        "/api/v1/bookshelf",
        params={"shelfStatus": "favorited", "pageNo": 2, "pageSize": 5},
        headers={"X-User-Id": "1"},
    )
    follows = client.get(
        "/api/v1/follows",
        params={"targetType": "narrator", "pageNo": 2, "pageSize": 5},
        headers={"X-User-Id": "1"},
    )

    assert bookshelf.status_code == 200
    assert bookshelf.json()["data"]["total"] == 0
    assert follows.status_code == 200
    assert follows.json()["data"]["total"] == 0


@pytest.mark.parametrize(
    ("path", "body", "expected_code"),
    [
        ("/api/v1/bookshelf", {"albumId": 7, "shelfStatus": "bad"}, "INVALID_SHELF_STATUS"),
        ("/api/v1/follows", {"targetType": "bad", "targetId": 3}, "INVALID_TARGET_TYPE"),
    ],
)
def test_library_writes_reject_invalid_state(
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
