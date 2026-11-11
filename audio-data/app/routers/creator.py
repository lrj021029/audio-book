"""Creator and content-supply APIs."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import bad_request, forbidden, not_found
from ..response import ok
from ..utils import count_total, format_datetime, local_now, make_no, offset_limit

router = APIRouter(prefix="/api/v1", tags=["creator"])


class CreatorApplicationCreateRequest(BaseModel):
    applyType: str = Field(
        description=(
            "申请类型。可选值：creator_settle、narrator_certification、"
            "organization_certification、contract_upgrade。"
        )
    )
    organizationId: int | None = Field(
        default=None,
        description="机构 ID，对应 content_organization.id；机构认证或机构关联申请时传入。",
    )
    applyPayload: dict[str, Any] | None = Field(
        default=None,
        description="申请材料 JSON；可存放证件、资质、简介、联系人等业务扩展信息。",
    )


class CreatorAlbumCreateRequest(BaseModel):
    albumTitle: str = Field(description="专辑标题；创建草稿时不能为空。")
    albumType: str = Field(description="专辑类型；写入 audio_album.album_type。")
    categoryId: int = Field(description="分类 ID，对应 dim_audio_category.id。")
    languageId: int = Field(description="语言 ID，对应 dim_language.id。")
    coverUrl: str | None = Field(default=None, description="封面 URL。")
    summary: str | None = Field(default=None, description="专辑简介。")
    publishStatus: str = Field(
        default="unknown", description="发布进度，写入 audio_album.publish_status。"
    )
    ageRating: str = Field(
        default="all", description="适听年龄分级，写入 audio_album.age_rating。"
    )


class CreatorAlbumUpdateRequest(BaseModel):
    albumTitle: str | None = Field(default=None, description="专辑标题；传入时不能为空。")
    categoryId: int | None = Field(
        default=None, description="分类 ID，对应 dim_audio_category.id。"
    )
    languageId: int | None = Field(default=None, description="语言 ID，对应 dim_language.id。")
    coverUrl: str | None = Field(default=None, description="封面 URL。")
    summary: str | None = Field(default=None, description="专辑简介。")
    publishStatus: str | None = Field(
        default=None, description="发布进度，写入 audio_album.publish_status。"
    )
    ageRating: str | None = Field(
        default=None, description="适听年龄分级，写入 audio_album.age_rating。"
    )


class UploadTaskCreateRequest(BaseModel):
    albumId: int | None = Field(default=None, description="专辑 ID，对应 audio_album.id。")
    trackId: int | None = Field(default=None, description="章节 ID，对应 audio_track.id。")
    fileId: int | None = Field(
        default=None, description="音频文件 ID，对应 track_audio_file.id。"
    )
    uploadType: str = Field(
        description="上传类型。可选值：album、track、audio_file、cover、batch_tracks。"
    )
    sourceFileName: str | None = Field(default=None, description="源文件名。")
    sourceFileUrl: str | None = Field(default=None, description="源文件 URL。")
    fileSizeBytes: int | None = Field(default=None, ge=0, description="文件大小，单位字节。")


class ContentAuditCreateRequest(BaseModel):
    uploadTaskId: int | None = Field(
        default=None, description="上传任务 ID，对应 content_upload_task.id。"
    )
    targetType: str = Field(
        description=(
            "审核对象类型。可选值：album、track、audio_file、upload_task、comment、"
            "creator_profile。"
        )
    )
    targetId: int = Field(description="审核对象 ID。")
    auditType: str = Field(default="manual", description="审核类型，默认 manual。")
    auditPayload: dict[str, Any] | None = Field(default=None, description="审核上下文。")


class AlbumPublishActionRequest(BaseModel):
    action: str = Field(
        description="发布动作。可选值：submit_review、publish、pause、offline。"
    )
    reason: str | None = Field(default=None, description="动作说明或审核备注。")


def _creator(current_user_id: int) -> dict[str, Any]:
    row = fetch_one(
        "SELECT * FROM creator_profile WHERE user_id = %s AND yn = 1",
        (current_user_id,),
    )
    if row is None:
        raise not_found("CREATOR_PROFILE_NOT_FOUND", "当前用户尚未入驻创作者")
    return row


def _creator_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "creatorId": row["id"],
        "creatorNo": row["creator_no"],
        "creatorName": row["creator_name"],
        "creatorType": row["creator_type"],
        "narratorId": row["narrator_id"],
        "organizationId": row["organization_id"],
        "certificationStatus": row["certification_status"],
        "creatorIntro": row["creator_intro"],
        "homepageUrl": row["homepage_url"],
        "settledAt": format_datetime(row["settled_at"]),
    }


def _album_owned(album_id: int, creator: dict[str, Any]) -> dict[str, Any]:
    row = fetch_one("SELECT * FROM audio_album WHERE id = %s", (album_id,))
    if row is None:
        raise not_found("ALBUM_NOT_FOUND", "专辑不存在")
    if row["organization_id"] and row["organization_id"] == creator["organization_id"]:
        return row
    task = fetch_one(
        """
        SELECT id
        FROM content_upload_task
        WHERE creator_id = %s AND album_id = %s
        LIMIT 1
        """,
        (creator["id"], album_id),
    )
    if task is None:
        raise forbidden("ALBUM_NOT_OWNED", "当前创作者无权操作该专辑")
    return row


def _track_owned(track_id: int, creator: dict[str, Any]) -> dict[str, Any]:
    row = fetch_one("SELECT * FROM audio_track WHERE id = %s", (track_id,))
    if row is None:
        raise not_found("TRACK_NOT_FOUND", "章节不存在")
    _album_owned(int(row["album_id"]), creator)
    return row


def _audio_file_owned(file_id: int, creator: dict[str, Any]) -> dict[str, Any]:
    row = fetch_one(
        """
        SELECT f.*, t.album_id
        FROM track_audio_file f
        JOIN audio_track t ON t.id = f.track_id
        WHERE f.id = %s
        """,
        (file_id,),
    )
    if row is None:
        raise not_found("AUDIO_FILE_NOT_FOUND", "音频文件不存在")
    _album_owned(int(row["album_id"]), creator)
    return row


def _upload_task_owned(upload_task_id: int, creator: dict[str, Any]) -> dict[str, Any]:
    row = fetch_one(
        "SELECT * FROM content_upload_task WHERE id = %s AND creator_id = %s",
        (upload_task_id, creator["id"]),
    )
    if row is None:
        raise not_found("UPLOAD_TASK_NOT_FOUND", "上传任务不存在")
    return row


def _comment_owned(comment_id: int, creator: dict[str, Any]) -> dict[str, Any]:
    row = fetch_one("SELECT * FROM content_comment WHERE id = %s", (comment_id,))
    if row is None:
        raise not_found("COMMENT_NOT_FOUND", "评论不存在")
    if row["target_type"] == "album":
        _album_owned(int(row["target_id"]), creator)
    elif row["target_type"] == "track":
        _track_owned(int(row["target_id"]), creator)
    else:
        raise bad_request("INVALID_COMMENT_TARGET", "评论对象类型不合法")
    return row


def _audit_target_owned(target_type: str, target_id: int, creator: dict[str, Any]) -> None:
    if target_type == "album":
        _album_owned(target_id, creator)
    elif target_type == "track":
        _track_owned(target_id, creator)
    elif target_type == "audio_file":
        _audio_file_owned(target_id, creator)
    elif target_type == "upload_task":
        _upload_task_owned(target_id, creator)
    elif target_type == "comment":
        _comment_owned(target_id, creator)
    elif target_type == "creator_profile":
        if target_id != creator["id"]:
            raise forbidden("CREATOR_PROFILE_NOT_OWNED", "当前创作者无权操作该创作者档案")
    else:
        raise bad_request("INVALID_AUDIT_TARGET_TYPE", "审核对象类型不合法")


def _album_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "albumId": row["id"],
        "albumCode": row["album_code"],
        "albumTitle": row["album_title"],
        "albumType": row["album_type"],
        "categoryId": row["category_id"],
        "languageId": row["language_id"],
        "coverUrl": row["cover_url"],
        "summary": row["summary"],
        "albumStatus": row["album_status"],
        "publishStatus": row["publish_status"],
        "ageRating": row["age_rating"],
        "createdAt": format_datetime(row["created_at"]),
        "updatedAt": format_datetime(row["updated_at"]),
    }


def _upload_task_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "uploadTaskId": row["id"],
        "uploadNo": row["upload_no"],
        "albumId": row["album_id"],
        "trackId": row["track_id"],
        "fileId": row["file_id"],
        "uploadType": row["upload_type"],
        "sourceFileName": row["source_file_name"],
        "sourceFileUrl": row["source_file_url"],
        "fileSizeBytes": row["file_size_bytes"],
        "processStatus": row["process_status"],
        "failureReason": row["failure_reason"],
        "submittedAt": format_datetime(row["submitted_at"]),
        "processedAt": format_datetime(row["processed_at"]),
    }


@router.get("/creator-profile", summary="查询创作者档案")
def get_creator_profile(current_user_id: Annotated[int, Depends(get_current_user_id)]):
    return ok({"creator": _creator_payload(_creator(current_user_id))})


@router.post("/creator-applications", summary="提交创作者申请")
def create_creator_application(
    body: Annotated[CreatorApplicationCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.applyType not in {
        "creator_settle",
        "narrator_certification",
        "organization_certification",
        "contract_upgrade",
    }:
        raise bad_request("INVALID_APPLY_TYPE", "申请类型不合法")
    if body.organizationId is not None and fetch_one(
        "SELECT id FROM content_organization WHERE id = %s AND yn = 1",
        (body.organizationId,),
    ) is None:
        raise not_found("ORGANIZATION_NOT_FOUND", "机构不存在")
    creator = fetch_one("SELECT id FROM creator_profile WHERE user_id = %s", (current_user_id,))
    now = local_now()
    apply_no = make_no("CAP")
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO creator_apply_record (
                apply_no, user_id, creator_id, organization_id,
                apply_type, apply_payload, apply_status,
                submitted_at, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'submitted', %s, %s, %s)
            """,
            (
                apply_no,
                current_user_id,
                creator["id"] if creator else None,
                body.organizationId,
                body.applyType,
                json.dumps(body.applyPayload or {}, ensure_ascii=False),
                now,
                now,
                now,
            ),
        )
        apply_id = cursor.lastrowid
    return ok(
        {
            "applicationId": apply_id,
            "applyNo": apply_no,
            "applyStatus": "submitted",
            "submittedAt": format_datetime(now),
        }
    )


@router.get("/creator-applications", summary="分页查询创作者申请")
def list_creator_applications(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    apply_status: Annotated[
        str | None, Query(alias="applyStatus", description="申请状态。")
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    offset, limit = offset_limit(page_no, page_size)
    conditions = ["user_id = %s"]
    params: list[Any] = [current_user_id]
    if apply_status:
        conditions.append("apply_status = %s")
        params.append(apply_status)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"SELECT COUNT(*) AS total FROM creator_apply_record WHERE {where_sql}",
        tuple(params),
    )
    rows = fetch_all(
        f"""
        SELECT *
        FROM creator_apply_record
        WHERE {where_sql}
        ORDER BY submitted_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [
                {
                    "applicationId": row["id"],
                    "applyNo": row["apply_no"],
                    "applyType": row["apply_type"],
                    "applyStatus": row["apply_status"],
                    "rejectReason": row["reject_reason"],
                    "submittedAt": format_datetime(row["submitted_at"]),
                    "reviewedAt": format_datetime(row["reviewed_at"]),
                }
                for row in rows
            ],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.post("/creator/albums", summary="创建创作者专辑草稿")
def create_creator_album(
    body: Annotated[CreatorAlbumCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    creator = _creator(current_user_id)
    if not body.albumTitle.strip():
        raise bad_request("EMPTY_ALBUM_TITLE", "专辑标题不能为空")
    if fetch_one("SELECT id FROM dim_audio_category WHERE id = %s AND yn = 1", (body.categoryId,)) is None:
        raise not_found("CATEGORY_NOT_FOUND", "分类不存在")
    if fetch_one("SELECT id FROM dim_language WHERE id = %s AND yn = 1", (body.languageId,)) is None:
        raise not_found("LANGUAGE_NOT_FOUND", "语言不存在")
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO audio_album (
                album_code, album_title, album_type, category_id, language_id,
                organization_id, cover_url, summary, album_status,
                publish_status, age_rating, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s, %s, %s)
            """,
            (
                make_no("ALB"),
                body.albumTitle.strip(),
                body.albumType,
                body.categoryId,
                body.languageId,
                creator["organization_id"],
                body.coverUrl,
                body.summary,
                body.publishStatus,
                body.ageRating,
                now,
                now,
            ),
        )
        album_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO content_upload_task (
                upload_no, creator_id, album_id, upload_type,
                process_status, submitted_at, created_at, updated_at
            ) VALUES (%s, %s, %s, 'album', 'processed', %s, %s, %s)
            """,
            (make_no("UPL"), creator["id"], album_id, now, now, now),
        )
    album = fetch_one("SELECT * FROM audio_album WHERE id = %s", (album_id,))
    if album is None:
        raise not_found("ALBUM_NOT_FOUND", "专辑创建后回查失败")
    return ok({"album": _album_payload(album)})


@router.patch("/creator/albums/{albumId}", summary="更新创作者专辑")
def update_creator_album(
    album_id: Annotated[int, Path(alias="albumId", description="专辑 ID。")],
    body: Annotated[CreatorAlbumUpdateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    creator = _creator(current_user_id)
    album = _album_owned(album_id, creator)
    if album["album_status"] not in {"draft", "reviewing", "paused"}:
        raise bad_request("ALBUM_NOT_EDITABLE", "当前专辑状态不可编辑")
    updates = ["updated_at = %s"]
    params: list[Any] = [local_now()]
    for column, value in (
        ("album_title", body.albumTitle.strip() if body.albumTitle else None),
        ("category_id", body.categoryId),
        ("language_id", body.languageId),
        ("cover_url", body.coverUrl),
        ("summary", body.summary),
        ("publish_status", body.publishStatus),
        ("age_rating", body.ageRating),
    ):
        if value is not None:
            updates.insert(-1, f"{column} = %s")
            params.insert(-1, value)
    params.append(album_id)
    with db_cursor() as (_, cursor):
        cursor.execute(
            f"UPDATE audio_album SET {', '.join(updates)} WHERE id = %s",
            tuple(params),
        )
    updated = fetch_one("SELECT * FROM audio_album WHERE id = %s", (album_id,))
    if updated is None:
        raise not_found("ALBUM_NOT_FOUND", "专辑不存在")
    return ok({"album": _album_payload(updated)})


@router.post("/upload-tasks", summary="提交上传任务")
def create_upload_task(
    body: Annotated[UploadTaskCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    creator = _creator(current_user_id)
    if body.uploadType not in {"album", "track", "audio_file", "cover", "batch_tracks"}:
        raise bad_request("INVALID_UPLOAD_TYPE", "上传类型不合法")
    if body.uploadType in {"track", "audio_file", "cover", "batch_tracks"} and body.albumId is None:
        raise bad_request("MISSING_UPLOAD_ALBUM", "该上传类型必须关联专辑")
    if body.uploadType == "album" and (body.trackId is not None or body.fileId is not None):
        raise bad_request("UPLOAD_TARGET_MISMATCH", "专辑上传任务不得关联章节或音频文件")
    if body.uploadType == "cover" and (body.trackId is not None or body.fileId is not None):
        raise bad_request("UPLOAD_TARGET_MISMATCH", "封面上传任务不得关联章节或音频文件")
    if body.uploadType == "batch_tracks" and (body.trackId is not None or body.fileId is not None):
        raise bad_request("UPLOAD_TARGET_MISMATCH", "批量章节上传任务不得关联单个章节或音频文件")
    if body.uploadType == "audio_file" and body.fileId is not None and body.trackId is None:
        raise bad_request("MISSING_UPLOAD_TRACK", "已关联音频文件时必须同时关联章节")
    album = None
    track = None
    audio_file = None
    if body.albumId is not None:
        album = _album_owned(body.albumId, creator)
    if body.trackId is not None:
        track = _track_owned(body.trackId, creator)
        if album is not None and int(track["album_id"]) != int(album["id"]):
            raise bad_request("UPLOAD_TARGET_MISMATCH", "章节不属于指定专辑")
    if body.fileId is not None:
        audio_file = _audio_file_owned(body.fileId, creator)
        if track is not None and int(audio_file["track_id"]) != int(track["id"]):
            raise bad_request("UPLOAD_TARGET_MISMATCH", "音频文件不属于指定章节")
        if album is not None and int(audio_file["album_id"]) != int(album["id"]):
            raise bad_request("UPLOAD_TARGET_MISMATCH", "音频文件不属于指定专辑")
    now = local_now()
    upload_no = make_no("UPL")
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO content_upload_task (
                upload_no, creator_id, album_id, track_id, file_id,
                upload_type, source_file_name, source_file_url,
                file_size_bytes, process_status, submitted_at,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'submitted', %s, %s, %s)
            """,
            (
                upload_no,
                creator["id"],
                body.albumId,
                body.trackId,
                body.fileId,
                body.uploadType,
                body.sourceFileName,
                body.sourceFileUrl,
                body.fileSizeBytes,
                now,
                now,
                now,
            ),
        )
        upload_id = cursor.lastrowid
    row = fetch_one("SELECT * FROM content_upload_task WHERE id = %s", (upload_id,))
    if row is None:
        raise not_found("UPLOAD_TASK_NOT_FOUND", "上传任务创建后回查失败")
    return ok({"uploadTask": _upload_task_payload(row)})


@router.get("/upload-tasks", summary="分页查询上传任务")
def list_upload_tasks(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    process_status: Annotated[
        str | None, Query(alias="processStatus", description="上传任务处理状态。")
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    creator = _creator(current_user_id)
    offset, limit = offset_limit(page_no, page_size)
    conditions = ["creator_id = %s"]
    params: list[Any] = [creator["id"]]
    if process_status:
        conditions.append("process_status = %s")
        params.append(process_status)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"SELECT COUNT(*) AS total FROM content_upload_task WHERE {where_sql}",
        tuple(params),
    )
    rows = fetch_all(
        f"""
        SELECT *
        FROM content_upload_task
        WHERE {where_sql}
        ORDER BY submitted_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [_upload_task_payload(row) for row in rows],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.get("/upload-tasks/{uploadTaskId}", summary="查询上传任务详情")
def get_upload_task(
    upload_task_id: Annotated[
        int, Path(alias="uploadTaskId", description="上传任务 ID。")
    ],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    creator = _creator(current_user_id)
    row = fetch_one(
        "SELECT * FROM content_upload_task WHERE id = %s AND creator_id = %s",
        (upload_task_id, creator["id"]),
    )
    if row is None:
        raise not_found("UPLOAD_TASK_NOT_FOUND", "上传任务不存在")
    return ok({"uploadTask": _upload_task_payload(row)})


@router.post("/content-audits", summary="提交内容审核记录")
def create_content_audit(
    body: Annotated[ContentAuditCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    creator = _creator(current_user_id)
    upload_task = None
    if body.uploadTaskId is not None:
        upload_task = _upload_task_owned(body.uploadTaskId, creator)
    _audit_target_owned(body.targetType, body.targetId, creator)
    if upload_task is not None and body.targetType == "upload_task" and body.targetId != upload_task["id"]:
        raise bad_request("AUDIT_TARGET_MISMATCH", "审核对象与上传任务不一致")
    now = local_now()
    audit_no = make_no("AUD")
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO content_audit_record (
                audit_no, upload_task_id, target_type, target_id,
                audit_type, audit_status, audit_payload,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s)
            """,
            (
                audit_no,
                body.uploadTaskId,
                body.targetType,
                body.targetId,
                body.auditType,
                json.dumps(body.auditPayload or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        audit_id = cursor.lastrowid
    return ok({"auditId": audit_id, "auditNo": audit_no, "auditStatus": "pending"})


@router.get("/content-audits", summary="分页查询内容审核记录")
def list_content_audits(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    audit_status: Annotated[
        str | None, Query(alias="auditStatus", description="审核状态。")
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    creator = _creator(current_user_id)
    offset, limit = offset_limit(page_no, page_size)
    audit_from_sql = """
        FROM content_audit_record audit
        LEFT JOIN content_upload_task task ON task.id = audit.upload_task_id
        LEFT JOIN audio_album target_album
          ON audit.target_type = 'album' AND target_album.id = audit.target_id
        LEFT JOIN audio_track target_track
          ON audit.target_type = 'track' AND target_track.id = audit.target_id
        LEFT JOIN audio_album target_track_album ON target_track_album.id = target_track.album_id
        LEFT JOIN track_audio_file target_file
          ON audit.target_type = 'audio_file' AND target_file.id = audit.target_id
        LEFT JOIN audio_track target_file_track ON target_file_track.id = target_file.track_id
        LEFT JOIN audio_album target_file_album ON target_file_album.id = target_file_track.album_id
        LEFT JOIN content_upload_task target_task
          ON audit.target_type = 'upload_task' AND target_task.id = audit.target_id
        LEFT JOIN content_comment target_comment
          ON audit.target_type = 'comment' AND target_comment.id = audit.target_id
        LEFT JOIN audio_album target_comment_album
          ON target_comment.target_type = 'album'
         AND target_comment_album.id = target_comment.target_id
        LEFT JOIN audio_track target_comment_track
          ON target_comment.target_type = 'track'
         AND target_comment_track.id = target_comment.target_id
        LEFT JOIN audio_album target_comment_track_album
          ON target_comment_track_album.id = target_comment_track.album_id
    """
    ownership_sql = """
        (
            task.creator_id = %s
            OR (
                audit.target_type = 'album'
                AND (
                    target_album.organization_id = %s
                    OR EXISTS (
                        SELECT 1
                        FROM content_upload_task owned_task
                        WHERE owned_task.creator_id = %s
                          AND owned_task.album_id = target_album.id
                    )
                )
            )
            OR (
                audit.target_type = 'track'
                AND (
                    target_track_album.organization_id = %s
                    OR EXISTS (
                        SELECT 1
                        FROM content_upload_task owned_task
                        WHERE owned_task.creator_id = %s
                          AND owned_task.album_id = target_track_album.id
                    )
                )
            )
            OR (
                audit.target_type = 'audio_file'
                AND (
                    target_file_album.organization_id = %s
                    OR EXISTS (
                        SELECT 1
                        FROM content_upload_task owned_task
                        WHERE owned_task.creator_id = %s
                          AND owned_task.album_id = target_file_album.id
                    )
                )
            )
            OR (audit.target_type = 'upload_task' AND target_task.creator_id = %s)
            OR (audit.target_type = 'creator_profile' AND audit.target_id = %s)
            OR (
                audit.target_type = 'comment'
                AND (
                    (
                        target_comment.target_type = 'album'
                        AND (
                            target_comment_album.organization_id = %s
                            OR EXISTS (
                                SELECT 1
                                FROM content_upload_task owned_task
                                WHERE owned_task.creator_id = %s
                                  AND owned_task.album_id = target_comment_album.id
                            )
                        )
                    )
                    OR (
                        target_comment.target_type = 'track'
                        AND (
                            target_comment_track_album.organization_id = %s
                            OR EXISTS (
                                SELECT 1
                                FROM content_upload_task owned_task
                                WHERE owned_task.creator_id = %s
                                  AND owned_task.album_id = target_comment_track_album.id
                            )
                        )
                    )
                )
            )
        )
    """
    conditions = [ownership_sql]
    params: list[Any] = [
        creator["id"],
        creator["organization_id"],
        creator["id"],
        creator["organization_id"],
        creator["id"],
        creator["organization_id"],
        creator["id"],
        creator["id"],
        creator["id"],
        creator["organization_id"],
        creator["id"],
        creator["organization_id"],
        creator["id"],
    ]
    if audit_status:
        conditions.append("audit.audit_status = %s")
        params.append(audit_status)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"""
        SELECT COUNT(*) AS total
        {audit_from_sql}
        WHERE {where_sql}
        """,
        tuple(params),
    )
    rows = fetch_all(
        f"""
        SELECT audit.*
        {audit_from_sql}
        WHERE {where_sql}
        ORDER BY audit.created_at DESC, audit.id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [
                {
                    "auditId": row["id"],
                    "auditNo": row["audit_no"],
                    "targetType": row["target_type"],
                    "targetId": row["target_id"],
                    "auditType": row["audit_type"],
                    "auditStatus": row["audit_status"],
                    "auditReason": row["audit_reason"],
                    "auditedAt": format_datetime(row["audited_at"]),
                    "createdAt": format_datetime(row["created_at"]),
                }
                for row in rows
            ],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.post("/creator/albums/{albumId}/publish-actions", summary="提交专辑发布动作")
def create_album_publish_action(
    album_id: Annotated[int, Path(alias="albumId", description="专辑 ID。")],
    body: Annotated[AlbumPublishActionRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    creator = _creator(current_user_id)
    album = _album_owned(album_id, creator)
    action_map = {
        "submit_review": "reviewing",
        "publish": "published",
        "pause": "paused",
        "offline": "offline",
    }
    if body.action not in action_map:
        raise bad_request("INVALID_PUBLISH_ACTION", "发布动作不合法")
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            UPDATE audio_album
            SET album_status = %s,
                published_at = IF(%s = 'published' AND published_at IS NULL, %s, published_at),
                updated_at = %s
            WHERE id = %s
            """,
            (action_map[body.action], action_map[body.action], now, now, album_id),
        )
        cursor.execute(
            """
            INSERT INTO album_update_record (
                album_id, creator_id, update_type, update_title,
                update_summary, updated_at_event, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                album_id,
                creator["id"],
                "album_published" if body.action == "publish" else body.action,
                f"{album['album_title']} {body.action}",
                body.reason,
                now,
                now,
            ),
        )
    updated = fetch_one("SELECT * FROM audio_album WHERE id = %s", (album_id,))
    if updated is None:
        raise not_found("ALBUM_NOT_FOUND", "专辑不存在")
    return ok({"album": _album_payload(updated), "action": body.action})
