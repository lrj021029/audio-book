"""Bookshelf and follow APIs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import bad_request, not_found
from ..response import ok
from ..utils import count_total, format_datetime, local_now, offset_limit
from .common import album_summary, fetch_album_base, target_exists, target_name

router = APIRouter(prefix="/api/v1", tags=["library"])

FOLLOW_TYPES = {"narrator", "author", "organization"}


class BookshelfCreateRequest(BaseModel):
    albumId: int = Field(description="专辑 ID，对应 audio_album.id；专辑必须已发布。")
    shelfStatus: str = Field(
        default="favorited",
        description="书架状态。可选值：favorited、subscribed、finished。",
    )


class FollowCreateRequest(BaseModel):
    targetType: str = Field(
        description="关注对象类型。可选值：narrator、author、organization。"
    )
    targetId: int = Field(description="关注对象 ID；必须与 targetType 对应表存在。")


def _bookshelf_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "bookshelfId": row["bookshelf_id"],
        "shelfStatus": row["shelf_status"],
        "lastTrackId": row["last_track_id"],
        "lastTrackTitle": row.get("last_track_title"),
        "lastPositionSeconds": row["last_position_seconds"],
        "createdAt": format_datetime(row["created_at"]),
        "updatedAt": format_datetime(row["updated_at"]),
        "album": album_summary(row, None),
    }


@router.get("/bookshelf", summary="查询书架")
def list_bookshelf(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    shelf_status: Annotated[
        str | None,
        Query(
            alias="shelfStatus",
            description="书架状态筛选。可选值：favorited、subscribed、finished。",
        ),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    offset, limit = offset_limit(page_no, page_size)
    conditions = ["b.user_id = %s", "b.shelf_status <> 'removed'"]
    params: list[Any] = [current_user_id]
    if shelf_status:
        conditions.append("b.shelf_status = %s")
        params.append(shelf_status)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"SELECT COUNT(*) AS total FROM user_bookshelf b WHERE {where_sql}",
        tuple(params),
    )
    rows = fetch_all(
        f"""
        SELECT
            b.id AS bookshelf_id,
            b.shelf_status,
            b.last_track_id,
            b.last_position_seconds,
            b.created_at,
            b.updated_at,
            t.track_title AS last_track_title,
            a.*,
            c.category_name,
            l.language_code
        FROM user_bookshelf b
        JOIN audio_album a ON a.id = b.album_id
        JOIN dim_audio_category c ON c.id = a.category_id
        JOIN dim_language l ON l.id = a.language_id
        LEFT JOIN audio_track t ON t.id = b.last_track_id
        WHERE {where_sql}
        ORDER BY b.updated_at DESC, b.id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [_bookshelf_payload(row) for row in rows],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.post("/bookshelf", summary="加入书架")
def add_bookshelf(
    body: Annotated[BookshelfCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.shelfStatus not in {"favorited", "subscribed", "finished"}:
        raise bad_request("INVALID_SHELF_STATUS", "书架状态不合法")
    album = fetch_album_base(body.albumId)
    if album is None or album["album_status"] != "published":
        raise not_found("ALBUM_NOT_FOUND", "专辑不存在或未发布")
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO user_bookshelf (
                user_id, album_id, shelf_status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                shelf_status = VALUES(shelf_status),
                updated_at = VALUES(updated_at)
            """,
            (current_user_id, body.albumId, body.shelfStatus, now, now),
        )
    row = fetch_one(
        "SELECT * FROM user_bookshelf WHERE user_id = %s AND album_id = %s",
        (current_user_id, body.albumId),
    )
    return ok(
        {
            "bookshelfId": row["id"] if row else None,
            "albumId": body.albumId,
            "shelfStatus": body.shelfStatus,
            "updatedAt": format_datetime(now),
        }
    )


@router.delete("/bookshelf/{albumId}", summary="移除书架专辑")
def remove_bookshelf(
    album_id: Annotated[int, Path(alias="albumId", description="专辑 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    row = fetch_one(
        "SELECT id FROM user_bookshelf WHERE user_id = %s AND album_id = %s",
        (current_user_id, album_id),
    )
    if row is None:
        return ok(
            {
                "albumId": album_id,
                "shelfStatus": "removed",
                "updatedAt": format_datetime(local_now()),
            }
        )
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            UPDATE user_bookshelf
            SET shelf_status = 'removed', updated_at = %s
            WHERE user_id = %s AND album_id = %s
            """,
            (now, current_user_id, album_id),
        )
    return ok({"albumId": album_id, "shelfStatus": "removed"})


@router.get("/follows", summary="查询关注列表")
def list_follows(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    target_type: Annotated[
        str | None,
        Query(
            alias="targetType",
            description="关注对象类型筛选。可选值：narrator、author、organization。",
        ),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    offset, limit = offset_limit(page_no, page_size)
    conditions = ["user_id = %s", "follow_status = 'following'"]
    params: list[Any] = [current_user_id]
    if target_type:
        conditions.append("target_type = %s")
        params.append(target_type)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"SELECT COUNT(*) AS total FROM user_follow WHERE {where_sql}",
        tuple(params),
    )
    rows = fetch_all(
        f"""
        SELECT *
        FROM user_follow
        WHERE {where_sql}
        ORDER BY followed_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [
                {
                    "followId": row["id"],
                    "targetType": row["target_type"],
                    "targetId": row["target_id"],
                    "targetName": target_name(row["target_type"], int(row["target_id"])),
                    "followStatus": row["follow_status"],
                    "followedAt": format_datetime(row["followed_at"]),
                }
                for row in rows
            ],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.post("/follows", summary="关注对象")
def follow_target(
    body: Annotated[FollowCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.targetType not in FOLLOW_TYPES:
        raise bad_request("INVALID_TARGET_TYPE", "关注对象类型不合法")
    if not target_exists(body.targetType, body.targetId):
        raise not_found("TARGET_NOT_FOUND", "关注对象不存在")
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO user_follow (
                user_id, target_type, target_id, follow_status,
                followed_at, created_at, updated_at
            ) VALUES (%s, %s, %s, 'following', %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                follow_status = 'following',
                followed_at = VALUES(followed_at),
                cancelled_at = NULL,
                updated_at = VALUES(updated_at)
            """,
            (current_user_id, body.targetType, body.targetId, now, now, now),
        )
    return ok(
        {
            "targetType": body.targetType,
            "targetId": body.targetId,
            "followStatus": "following",
            "followedAt": format_datetime(now),
        }
    )


@router.delete("/follows", summary="取消关注")
def unfollow_target(
    body: Annotated[FollowCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    target_type = body.targetType
    target_id = body.targetId
    row = fetch_one(
        """
        SELECT id
        FROM user_follow
        WHERE user_id = %s AND target_type = %s AND target_id = %s
        """,
        (current_user_id, target_type, target_id),
    )
    if row is None:
        return ok(
            {
                "targetType": target_type,
                "targetId": target_id,
                "followStatus": "cancelled",
                "cancelledAt": format_datetime(local_now()),
            }
        )
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            UPDATE user_follow
            SET follow_status = 'cancelled',
                cancelled_at = %s,
                updated_at = %s
            WHERE user_id = %s AND target_type = %s AND target_id = %s
            """,
            (now, now, current_user_id, target_type, target_id),
        )
    return ok(
        {
            "targetType": target_type,
            "targetId": target_id,
            "followStatus": "cancelled",
            "cancelledAt": format_datetime(now),
        }
    )
