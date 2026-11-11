from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from helpers import NOW, FakeCursor, fake_db_cursor, patch_auth_user

from app.routers import creator


def _creator_row() -> dict[str, Any]:
    return {
        "id": 3,
        "user_id": 1,
        "creator_no": "CRT001",
        "creator_name": "Alice Studio",
        "creator_type": "organization",
        "narrator_id": None,
        "organization_id": 5,
        "certification_status": "approved",
        "creator_intro": "介绍",
        "homepage_url": "https://example.com",
        "settled_at": NOW,
        "yn": 1,
    }


def _album_row(album_status: str = "draft") -> dict[str, Any]:
    return {
        "id": 7,
        "album_code": "ALB001",
        "album_title": "创作者专辑",
        "album_type": "audiobook",
        "category_id": 1,
        "language_id": 1,
        "organization_id": 5,
        "cover_url": "https://example.com/cover.jpg",
        "summary": "简介",
        "album_status": album_status,
        "publish_status": "serializing",
        "age_rating": "all",
        "created_at": NOW,
        "updated_at": NOW,
        "published_at": None,
    }


def _upload_task_row() -> dict[str, Any]:
    return {
        "id": 9,
        "upload_no": "UPL001",
        "creator_id": 3,
        "album_id": 7,
        "track_id": None,
        "file_id": None,
        "upload_type": "cover",
        "source_file_name": "cover.jpg",
        "source_file_url": "https://example.com/cover.jpg",
        "file_size_bytes": 100,
        "process_status": "submitted",
        "failure_reason": None,
        "submitted_at": NOW,
        "processed_at": None,
    }


def test_creator_success_paths(client: TestClient, monkeypatch: Any) -> None:
    patch_auth_user(monkeypatch)
    cursor = FakeCursor()

    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM creator_profile" in sql:
            return _creator_row()
        if "FROM content_organization" in sql:
            return {"id": 5}
        if "FROM dim_audio_category" in sql:
            return {"id": 1}
        if "FROM dim_language" in sql:
            return {"id": 1}
        if "FROM audio_album" in sql:
            return _album_row()
        if "FROM content_upload_task" in sql:
            return _upload_task_row()
        return None

    def fake_fetch_all(sql: str, params: Any | None = None) -> list[dict[str, Any]]:
        if "SELECT audit.*" in sql:
            return [
                {
                    "id": 11,
                    "audit_no": "AUD001",
                    "target_type": "upload_task",
                    "target_id": 9,
                    "audit_type": "manual",
                    "audit_status": "pending",
                    "audit_reason": None,
                    "audited_at": None,
                    "created_at": NOW,
                }
            ]
        if "FROM content_upload_task" in sql:
            return [_upload_task_row()]
        if "FROM creator_apply_record" in sql:
            return [
                {
                    "id": 2,
                    "apply_no": "CAP001",
                    "apply_type": "creator_settle",
                    "apply_status": "submitted",
                    "reject_reason": None,
                    "submitted_at": NOW,
                    "reviewed_at": None,
                }
            ]
        return []

    monkeypatch.setattr(creator, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(creator, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(creator, "count_total", lambda sql, params=None: 1)
    monkeypatch.setattr(creator, "db_cursor", lambda: fake_db_cursor(cursor))
    monkeypatch.setattr(creator, "make_no", lambda prefix: f"{prefix}TEST")

    profile = client.get("/api/v1/creator-profile", headers={"X-User-Id": "1"})
    application = client.post(
        "/api/v1/creator-applications",
        json={"applyType": "creator_settle", "organizationId": 5, "applyPayload": {"name": "Alice"}},
        headers={"X-User-Id": "1"},
    )
    applications = client.get(
        "/api/v1/creator-applications",
        params={"applyStatus": "submitted", "pageNo": 1, "pageSize": 5},
        headers={"X-User-Id": "1"},
    )
    album = client.post(
        "/api/v1/creator/albums",
        json={"albumTitle": "创作者专辑", "albumType": "audiobook", "categoryId": 1, "languageId": 1},
        headers={"X-User-Id": "1"},
    )
    updated = client.patch(
        "/api/v1/creator/albums/7",
        json={"albumTitle": "创作者专辑 2"},
        headers={"X-User-Id": "1"},
    )
    upload = client.post(
        "/api/v1/upload-tasks",
        json={"albumId": 7, "uploadType": "cover", "sourceFileName": "cover.jpg"},
        headers={"X-User-Id": "1"},
    )
    uploads = client.get(
        "/api/v1/upload-tasks",
        params={"processStatus": "submitted", "pageNo": 1, "pageSize": 5},
        headers={"X-User-Id": "1"},
    )
    upload_detail = client.get("/api/v1/upload-tasks/9", headers={"X-User-Id": "1"})
    audit = client.post(
        "/api/v1/content-audits",
        json={"uploadTaskId": 9, "targetType": "upload_task", "targetId": 9, "auditPayload": {"source": "test"}},
        headers={"X-User-Id": "1"},
    )
    audits = client.get(
        "/api/v1/content-audits",
        params={"auditStatus": "pending", "pageNo": 1, "pageSize": 5},
        headers={"X-User-Id": "1"},
    )
    publish = client.post(
        "/api/v1/creator/albums/7/publish-actions",
        json={"action": "submit_review", "reason": "准备发布"},
        headers={"X-User-Id": "1"},
    )

    assert profile.status_code == 200
    assert profile.json()["data"]["creator"]["creatorId"] == 3
    assert application.status_code == 200
    assert application.json()["data"]["applyStatus"] == "submitted"
    assert applications.status_code == 200
    assert applications.json()["data"]["total"] == 1
    assert album.status_code == 200
    assert album.json()["data"]["album"]["albumStatus"] == "draft"
    assert updated.status_code == 200
    assert upload.status_code == 200
    assert upload_detail.status_code == 200
    assert uploads.status_code == 200
    assert audit.status_code == 200
    assert audits.status_code == 200
    assert publish.status_code == 200
    assert publish.json()["data"]["action"] == "submit_review"
    assert any("creator_apply_record" in sql for sql, _ in cursor.executed)


def test_creator_application_rejects_invalid_type(
    client: TestClient, monkeypatch: Any
) -> None:
    patch_auth_user(monkeypatch)

    response = client.post(
        "/api/v1/creator-applications",
        json={"applyType": "bad"},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_APPLY_TYPE"


def test_creator_album_rejects_non_creator(client: TestClient, monkeypatch: Any) -> None:
    patch_auth_user(monkeypatch)
    monkeypatch.setattr(creator, "fetch_one", lambda sql, params=None: None)

    response = client.post(
        "/api/v1/creator/albums",
        json={"albumTitle": "创作者专辑", "albumType": "audiobook", "categoryId": 1, "languageId": 1},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "CREATOR_PROFILE_NOT_FOUND"


def test_creator_album_rejects_non_editable_status(
    client: TestClient, monkeypatch: Any
) -> None:
    patch_auth_user(monkeypatch)

    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM creator_profile" in sql:
            return _creator_row()
        if "FROM audio_album" in sql:
            return _album_row(album_status="published")
        return None

    monkeypatch.setattr(creator, "fetch_one", fake_fetch_one)

    response = client.patch(
        "/api/v1/creator/albums/7",
        json={"albumTitle": "不可编辑"},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "ALBUM_NOT_EDITABLE"


def test_upload_task_rejects_target_mismatch(
    client: TestClient, monkeypatch: Any
) -> None:
    patch_auth_user(monkeypatch)
    monkeypatch.setattr(creator, "fetch_one", lambda sql, params=None: _creator_row() if "creator_profile" in sql else None)

    response = client.post(
        "/api/v1/upload-tasks",
        json={"uploadType": "audio_file", "albumId": 7, "fileId": 99},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "MISSING_UPLOAD_TRACK"


def test_content_audit_rejects_mismatched_upload_task(
    client: TestClient, monkeypatch: Any
) -> None:
    patch_auth_user(monkeypatch)

    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM creator_profile" in sql:
            return _creator_row()
        if "FROM content_upload_task" in sql:
            return _upload_task_row() if params and int(params[0]) == 9 else None
        return None

    monkeypatch.setattr(creator, "fetch_one", fake_fetch_one)

    response = client.post(
        "/api/v1/content-audits",
        json={"uploadTaskId": 9, "targetType": "upload_task", "targetId": 10},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "UPLOAD_TASK_NOT_FOUND"


def test_publish_action_rejects_invalid_action(
    client: TestClient, monkeypatch: Any
) -> None:
    patch_auth_user(monkeypatch)

    def fake_fetch_one(sql: str, params: Any | None = None) -> dict[str, Any] | None:
        if "FROM creator_profile" in sql:
            return _creator_row()
        if "FROM audio_album" in sql:
            return _album_row()
        return None

    monkeypatch.setattr(creator, "fetch_one", fake_fetch_one)

    response = client.post(
        "/api/v1/creator/albums/7/publish-actions",
        json={"action": "bad"},
        headers={"X-User-Id": "1"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_PUBLISH_ACTION"
