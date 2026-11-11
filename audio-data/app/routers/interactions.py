"""Interaction and feedback APIs."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id, get_optional_current_user_id
from ..errors import bad_request, not_found
from ..response import ok
from ..utils import (
    count_total,
    format_datetime,
    local_now,
    make_no,
    money,
    offset_limit,
)
from .common import target_exists

router = APIRouter(prefix="/api/v1", tags=["interactions"])

COMMENT_TYPES = {"album", "track"}
REACTION_TYPES = {"like", "dislike", "share", "forward"}
REACTION_TARGET_TYPES = {"album", "track", "comment", "narrator"}
REPORT_REASONS = {"copyright", "illegal", "violent", "pornographic", "spam", "other"}


class CommentCreateRequest(BaseModel):
    targetType: str = Field(description="评论对象类型。可选值：album、track。")
    targetId: int = Field(description="评论对象 ID；必须与 targetType 对应对象存在。")
    parentCommentId: int | None = Field(
        default=None, description="父评论 ID；回复评论时传入 content_comment.id。"
    )
    commentText: str = Field(description="评论内容；提交后进入待审核状态。")


class RatingCreateRequest(BaseModel):
    albumId: int = Field(description="专辑 ID，对应 audio_album.id。")
    ratingScore: Decimal = Field(description="评分，1 到 10 分。")
    ratingText: str | None = Field(default=None, description="评分文本，可为空。")


class ReactionCreateRequest(BaseModel):
    targetType: str = Field(
        description="互动对象类型。可选值：album、track、comment、narrator。"
    )
    targetId: int = Field(description="互动对象 ID；必须与 targetType 对应对象存在。")
    reactionType: str = Field(
        description="互动类型。可选值：like、dislike、share、forward。"
    )
    reactionStatus: str = Field(
        default="active", description="互动状态。可选值：active、cancelled。"
    )


class ReportCreateRequest(BaseModel):
    targetType: str = Field(
        description="举报对象类型。可选值：album、track、comment、narrator。"
    )
    targetId: int = Field(description="举报对象 ID；必须与 targetType 对应对象存在。")
    reportReason: str = Field(
        description="举报原因。可选值：copyright、illegal、violent、pornographic、spam、other。"
    )
    reportText: str | None = Field(default=None, description="举报补充说明。")


def _comment_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "commentId": row["id"],
        "targetType": row["target_type"],
        "targetId": row["target_id"],
        "parentCommentId": row["parent_comment_id"],
        "commentText": row["comment_text"],
        "auditStatus": row["audit_status"],
        "likeCount": row["like_count"],
        "createdAt": format_datetime(row["created_at"]),
        "liked": bool(row.get("liked")),
        "user": {
            "userId": row["user_id"],
            "nickname": row.get("nickname"),
            "avatarUrl": row.get("avatar_url"),
        },
    }


@router.get("/comments", summary="分页查询评论")
def list_comments(
    target_type: Annotated[
        str, Query(alias="targetType", description="评论对象类型。可选值：album、track。")
    ],
    target_id: Annotated[
        int, Query(alias="targetId", description="评论对象 ID；必须与 targetType 匹配。")
    ],
    current_user_id: Annotated[
        int | None, Depends(get_optional_current_user_id)
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    if target_type not in COMMENT_TYPES:
        raise bad_request("INVALID_TARGET_TYPE", "评论对象类型不合法")
    if not target_exists(target_type, target_id):
        raise not_found("TARGET_NOT_FOUND", "评论对象不存在")
    offset, limit = offset_limit(page_no, page_size)
    total = count_total(
        """
        SELECT COUNT(*) AS total
        FROM content_comment
        WHERE target_type = %s AND target_id = %s AND audit_status = 'approved'
        """,
        (target_type, target_id),
    )
    liked_select = (
        """
        EXISTS (
            SELECT 1 FROM user_reaction ur
            WHERE ur.user_id = %s
              AND ur.target_type = 'comment'
              AND ur.target_id = c.id
              AND ur.reaction_type = 'like'
              AND ur.reaction_status = 'active'
        ) AS liked,
        """
        if current_user_id is not None
        else "0 AS liked,"
    )
    params: tuple[Any, ...] = (
        (current_user_id, target_type, target_id, limit, offset)
        if current_user_id is not None
        else (target_type, target_id, limit, offset)
    )
    rows = fetch_all(
        f"""
        SELECT c.*, {liked_select} u.nickname, u.avatar_url
        FROM content_comment c
        JOIN user_account u ON u.id = c.user_id
        WHERE c.target_type = %s
          AND c.target_id = %s
          AND c.audit_status = 'approved'
        ORDER BY c.like_count DESC, c.created_at DESC, c.id DESC
        LIMIT %s OFFSET %s
        """,
        params,
    )
    return ok(
        {
            "list": [_comment_payload(row) for row in rows],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.post("/comments", summary="提交评论")
def create_comment(
    body: Annotated[CommentCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.targetType not in COMMENT_TYPES:
        raise bad_request("INVALID_TARGET_TYPE", "评论对象类型不合法")
    if not body.commentText.strip():
        raise bad_request("EMPTY_COMMENT", "评论内容不能为空")
    if not target_exists(body.targetType, body.targetId):
        raise not_found("TARGET_NOT_FOUND", "评论对象不存在")
    if body.parentCommentId is not None:
        parent_comment = fetch_one(
            """
            SELECT id
            FROM content_comment
            WHERE id = %s
              AND target_type = %s
              AND target_id = %s
            """,
            (body.parentCommentId, body.targetType, body.targetId),
        )
        if parent_comment is None:
            raise not_found("PARENT_COMMENT_NOT_FOUND", "父评论不存在")
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO content_comment (
                user_id, target_type, target_id, parent_comment_id,
                comment_text, audit_status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s)
            """,
            (
                current_user_id,
                body.targetType,
                body.targetId,
                body.parentCommentId,
                body.commentText.strip(),
                now,
                now,
            ),
        )
        comment_id = cursor.lastrowid
    return ok(
        {
            "commentId": comment_id,
            "targetType": body.targetType,
            "targetId": body.targetId,
            "auditStatus": "pending",
            "createdAt": format_datetime(now),
        }
    )


@router.post("/ratings", summary="提交或更新评分")
def create_or_update_rating(
    body: Annotated[RatingCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.ratingScore < 1 or body.ratingScore > 10:
        raise bad_request("INVALID_RATING_SCORE", "评分必须在 1 到 10 之间")
    if not target_exists("album", body.albumId):
        raise not_found("ALBUM_NOT_FOUND", "专辑不存在")
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO content_rating (
                user_id, album_id, rating_score, rating_text,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                rating_score = VALUES(rating_score),
                rating_text = VALUES(rating_text),
                updated_at = VALUES(updated_at)
            """,
            (
                current_user_id,
                body.albumId,
                body.ratingScore,
                body.ratingText,
                now,
                now,
            ),
        )
        cursor.execute(
            """
            UPDATE audio_album a
            SET rating_score = (
                SELECT ROUND(AVG(rating_score), 2)
                FROM content_rating
                WHERE album_id = %s
            )
            WHERE a.id = %s
            """,
            (body.albumId, body.albumId),
        )
    return ok(
        {
            "albumId": body.albumId,
            "ratingScore": money(body.ratingScore),
            "ratingText": body.ratingText,
            "createdAt": format_datetime(now),
            "updatedAt": format_datetime(now),
        }
    )


@router.post("/reactions", summary="提交互动行为")
def create_or_update_reaction(
    body: Annotated[ReactionCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.targetType not in REACTION_TARGET_TYPES:
        raise bad_request("INVALID_TARGET_TYPE", "互动对象类型不合法")
    if body.reactionType not in REACTION_TYPES:
        raise bad_request("INVALID_REACTION_TYPE", "互动类型不合法")
    if body.reactionStatus not in {"active", "cancelled"}:
        raise bad_request("INVALID_REACTION_STATUS", "互动状态不合法")
    if not target_exists(body.targetType, body.targetId):
        raise not_found("TARGET_NOT_FOUND", "互动对象不存在")
    existing = fetch_one(
        """
        SELECT reaction_status
        FROM user_reaction
        WHERE user_id = %s
          AND target_type = %s
          AND target_id = %s
          AND reaction_type = %s
        """,
        (current_user_id, body.targetType, body.targetId, body.reactionType),
    )
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO user_reaction (
                user_id, target_type, target_id, reaction_type,
                reaction_status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                reaction_status = VALUES(reaction_status),
                updated_at = VALUES(updated_at)
            """,
            (
                current_user_id,
                body.targetType,
                body.targetId,
                body.reactionType,
                body.reactionStatus,
                now,
                now,
            ),
        )
        if body.targetType == "comment" and body.reactionType == "like":
            previous_active = existing is not None and existing["reaction_status"] == "active"
            current_active = body.reactionStatus == "active"
            delta = int(current_active) - int(previous_active)
            if delta:
                cursor.execute(
                    """
                    UPDATE content_comment
                    SET like_count = GREATEST(like_count + %s, 0)
                    WHERE id = %s
                    """,
                    (delta, body.targetId),
                )
    return ok(
        {
            "targetType": body.targetType,
            "targetId": body.targetId,
            "reactionType": body.reactionType,
            "reactionStatus": body.reactionStatus,
            "updatedAt": format_datetime(now),
        }
    )


@router.post("/reports", summary="提交举报")
def create_report(
    body: Annotated[ReportCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.targetType not in REACTION_TARGET_TYPES:
        raise bad_request("INVALID_TARGET_TYPE", "举报对象类型不合法")
    if body.reportReason not in REPORT_REASONS:
        raise bad_request("INVALID_REPORT_REASON", "举报原因不合法")
    if not target_exists(body.targetType, body.targetId):
        raise not_found("TARGET_NOT_FOUND", "举报对象不存在")
    now = local_now()
    report_no = make_no("RPT")
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO content_report (
                report_no, user_id, target_type, target_id,
                report_reason, report_text, handle_status,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s)
            """,
            (
                report_no,
                current_user_id,
                body.targetType,
                body.targetId,
                body.reportReason,
                body.reportText,
                now,
                now,
            ),
        )
        report_id = cursor.lastrowid
    return ok(
        {
            "reportId": report_id,
            "reportNo": report_no,
            "handleStatus": "pending",
            "createdAt": format_datetime(now),
        }
    )
