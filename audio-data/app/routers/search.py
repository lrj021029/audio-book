"""Search APIs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_optional_current_user_id
from ..errors import bad_request, not_found
from ..response import ok
from ..utils import count_total, format_date, local_now, make_no, offset_limit
from .common import album_summary, target_exists

router = APIRouter(prefix="/api/v1", tags=["search"])

SEARCH_TYPES = {
    "all",
    "album",
    "book",
    "program",
    "track",
    "narrator",
    "organization",
    "topic",
}
CLICK_TYPES = {"album", "track", "narrator", "organization", "topic"}


class SearchClickCreateRequest(BaseModel):
    requestNo: str = Field(description="搜索流水号，对应 search_query_log.query_no。")
    clickedTargetType: str = Field(
        description="点击对象类型。可选值：album、track、narrator、organization、topic。"
    )
    clickedTargetId: int = Field(description="点击对象 ID；必须与 clickedTargetType 匹配。")


def _album_where(
    keyword: str, search_type: str, category_id: int | None
) -> tuple[str, list[Any]]:
    conditions = [
        "a.album_status = 'published'",
        "(a.album_title LIKE %s OR a.summary LIKE %s)",
    ]
    params: list[Any] = [f"%{keyword}%", f"%{keyword}%"]
    if search_type == "book":
        conditions.append("a.album_type = 'audiobook'")
    elif search_type == "program":
        conditions.append("a.album_type <> 'audiobook'")
    if category_id is not None:
        conditions.append("a.category_id = %s")
        params.append(category_id)
    return " AND ".join(conditions), params


def _search_albums(
    keyword: str,
    search_type: str,
    category_id: int | None,
    user_id: int | None,
    limit: int,
    offset: int,
    sort_by: str,
) -> tuple[list[dict[str, Any]], int]:
    where_sql, params = _album_where(keyword, search_type, category_id)
    total = count_total(
        f"SELECT COUNT(*) AS total FROM audio_album a WHERE {where_sql}",
        tuple(params),
    )
    order_sql = {
        "newest": "a.published_at DESC, a.id DESC",
        "popular": "a.play_count DESC, a.id DESC",
    }.get(sort_by, "a.play_count DESC, a.id DESC")
    rows = fetch_all(
        f"""
        SELECT a.*, c.category_name, l.language_code
        FROM audio_album a
        JOIN dim_audio_category c ON c.id = a.category_id
        JOIN dim_language l ON l.id = a.language_id
        WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return [
        {
            "targetType": "album",
            "targetId": row["id"],
            "title": row["album_title"],
            "coverUrl": row["cover_url"],
            "summary": row["summary"],
            "album": album_summary(row, user_id),
        }
        for row in rows
    ], total


def _search_tracks(
    keyword: str, limit: int, offset: int, sort_by: str
) -> tuple[list[dict[str, Any]], int]:
    total = count_total(
        """
        SELECT COUNT(*) AS total
        FROM audio_track t
        JOIN audio_album a ON a.id = t.album_id
        WHERE t.track_status = 'published'
          AND a.album_status = 'published'
          AND t.track_title LIKE %s
        """,
        (f"%{keyword}%",),
    )
    order_sql = (
        "t.published_at DESC, t.id DESC"
        if sort_by == "newest"
        else "t.play_count DESC, t.id DESC"
    )
    rows = fetch_all(
        f"""
        SELECT t.*, a.album_title, a.cover_url
        FROM audio_track t
        JOIN audio_album a ON a.id = t.album_id
        WHERE t.track_status = 'published'
          AND a.album_status = 'published'
          AND t.track_title LIKE %s
        ORDER BY {order_sql}
        LIMIT %s OFFSET %s
        """,
        (f"%{keyword}%", limit, offset),
    )
    return [
        {
            "targetType": "track",
            "targetId": row["id"],
            "title": row["track_title"],
            "coverUrl": row["cover_url"],
            "summary": row["album_title"],
            "track": {
                "trackId": row["id"],
                "albumId": row["album_id"],
                "albumTitle": row["album_title"],
                "trackNo": row["track_no"],
                "durationSeconds": row["duration_seconds"],
            },
        }
        for row in rows
    ], total


def _search_narrators(
    keyword: str, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    params = (f"%{keyword}%", f"%{keyword}%")
    total = count_total(
        """
        SELECT COUNT(*) AS total
        FROM content_narrator
        WHERE yn = 1 AND (narrator_name LIKE %s OR intro LIKE %s)
        """,
        params,
    )
    rows = fetch_all(
        """
        SELECT id, narrator_name, avatar_url, intro, follower_count, album_count
        FROM content_narrator
        WHERE yn = 1 AND (narrator_name LIKE %s OR intro LIKE %s)
        ORDER BY follower_count DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        (*params, limit, offset),
    )
    return [
        {
            "targetType": "narrator",
            "targetId": row["id"],
            "title": row["narrator_name"],
            "coverUrl": row["avatar_url"],
            "summary": row["intro"],
            "narrator": {
                "narratorId": row["id"],
                "narratorName": row["narrator_name"],
                "avatarUrl": row["avatar_url"],
                "followerCount": row["follower_count"],
                "albumCount": row["album_count"],
            },
        }
        for row in rows
    ], total


def _search_organizations(
    keyword: str, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    params = (f"%{keyword}%", f"%{keyword}%")
    total = count_total(
        """
        SELECT COUNT(*) AS total
        FROM content_organization
        WHERE yn = 1 AND (organization_name LIKE %s OR intro LIKE %s)
        """,
        params,
    )
    rows = fetch_all(
        """
        SELECT *
        FROM content_organization
        WHERE yn = 1 AND (organization_name LIKE %s OR intro LIKE %s)
        ORDER BY id DESC
        LIMIT %s OFFSET %s
        """,
        (*params, limit, offset),
    )
    return [
        {
            "targetType": "organization",
            "targetId": row["id"],
            "title": row["organization_name"],
            "coverUrl": None,
            "summary": row["intro"],
            "organization": {
                "organizationId": row["id"],
                "organizationName": row["organization_name"],
                "organizationType": row["organization_type"],
            },
        }
        for row in rows
    ], total


def _search_topics(
    keyword: str, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    params = (f"%{keyword}%", f"%{keyword}%")
    total = count_total(
        """
        SELECT COUNT(*) AS total
        FROM content_topic
        WHERE topic_status = 'published'
          AND (topic_title LIKE %s OR summary LIKE %s)
        """,
        params,
    )
    rows = fetch_all(
        """
        SELECT *
        FROM content_topic
        WHERE topic_status = 'published'
          AND (topic_title LIKE %s OR summary LIKE %s)
        ORDER BY published_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        (*params, limit, offset),
    )
    return [
        {
            "targetType": "topic",
            "targetId": row["id"],
            "title": row["topic_title"],
            "coverUrl": row["cover_url"],
            "summary": row["summary"],
            "topic": {"topicId": row["id"], "topicType": row["topic_type"]},
        }
        for row in rows
    ], total


@router.get("/search", summary="综合搜索")
def search(
    keyword: Annotated[
        str,
        Query(min_length=1, description="搜索词，按专辑、章节、主播、机构或专题名称匹配。"),
    ],
    channel_id: Annotated[int, Query(alias="channelId", description="渠道 ID，对应 dim_channel.id。")],
    current_user_id: Annotated[
        int | None, Depends(get_optional_current_user_id)
    ] = None,
    search_type: Annotated[
        str,
        Query(
            alias="searchType",
            description=(
                "搜索类型。可选值：all、album、book、program、track、narrator、"
                "organization、topic。"
            ),
        ),
    ] = "all",
    category_id: Annotated[
        int | None, Query(alias="categoryId", description="分类 ID。")
    ] = None,
    sort_by: Annotated[
        str,
        Query(alias="sortBy", description="排序方式。可选值：relevance、popular、newest。"),
    ] = "relevance",
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    if search_type not in SEARCH_TYPES:
        raise bad_request("INVALID_SEARCH_TYPE", "搜索类型不合法")
    if sort_by not in {"relevance", "popular", "newest"}:
        raise bad_request("INVALID_SORT_BY", "排序方式不合法")
    if fetch_one("SELECT id FROM dim_channel WHERE id = %s AND yn = 1", (channel_id,)) is None:
        raise not_found("CHANNEL_NOT_FOUND", "渠道不存在或已停用")
    offset, limit = offset_limit(page_no, page_size)
    result_items: list[dict[str, Any]] = []
    total = 0
    if search_type in {"all", "album", "book", "program"}:
        items, item_total = _search_albums(
            keyword, search_type, category_id, current_user_id, limit, offset, sort_by
        )
        result_items.extend(items)
        total += item_total
    if search_type in {"all", "track"}:
        items, item_total = _search_tracks(keyword, limit, offset, sort_by)
        result_items.extend(items)
        total += item_total
    if search_type in {"all", "narrator"}:
        items, item_total = _search_narrators(keyword, limit, offset)
        result_items.extend(items)
        total += item_total
    if search_type in {"all", "organization"}:
        items, item_total = _search_organizations(keyword, limit, offset)
        result_items.extend(items)
        total += item_total
    if search_type in {"all", "topic"}:
        items, item_total = _search_topics(keyword, limit, offset)
        result_items.extend(items)
        total += item_total
    request_no = make_no("SRCH")
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO search_query_log (
                query_no, user_id, channel_id, keyword, search_type,
                result_count, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                request_no,
                current_user_id,
                channel_id,
                keyword,
                search_type,
                total,
                local_now(),
            ),
        )
    return ok(
        {
            "requestNo": request_no,
            "keyword": keyword,
            "searchType": search_type,
            "resultCount": total,
            "list": result_items[:limit],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.post("/search/clicks", summary="记录搜索点击")
def record_search_click(
    body: Annotated[SearchClickCreateRequest, Body()],
    current_user_id: Annotated[
        int | None, Depends(get_optional_current_user_id)
    ] = None,
):
    if body.clickedTargetType not in CLICK_TYPES:
        raise bad_request("INVALID_TARGET_TYPE", "点击对象类型不合法")
    if not target_exists(body.clickedTargetType, body.clickedTargetId):
        raise not_found("TARGET_NOT_FOUND", "点击对象不存在")
    row = fetch_one(
        "SELECT * FROM search_query_log WHERE query_no = %s",
        (body.requestNo,),
    )
    if row is None:
        raise not_found("SEARCH_QUERY_NOT_FOUND", "搜索记录不存在")
    if row["user_id"] != current_user_id:
        raise bad_request("SEARCH_QUERY_USER_MISMATCH", "搜索记录不属于当前用户")
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            UPDATE search_query_log
            SET clicked_flag = 1,
                clicked_target_type = %s,
                clicked_target_id = %s
            WHERE query_no = %s
            """,
            (body.clickedTargetType, body.clickedTargetId, body.requestNo),
        )
    return ok(
        {
            "requestNo": body.requestNo,
            "clickedFlag": 1,
            "clickedTargetType": body.clickedTargetType,
            "clickedTargetId": body.clickedTargetId,
        }
    )


@router.get("/search/hot-keywords", summary="查询热门搜索词")
def list_hot_keywords(
    channel_id: Annotated[
        int | None, Query(alias="channelId", description="渠道 ID。")
    ] = None,
    days: Annotated[int, Query(ge=1, le=90, description="统计天数。")] = 7,
    limit: Annotated[int, Query(ge=1, le=50, description="返回数量上限。")] = 20,
):
    conditions = ["stat_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"]
    params: list[Any] = [days]
    if channel_id is not None:
        conditions.append("channel_id = %s")
        params.append(channel_id)
    rows = fetch_all(
        f"""
        SELECT keyword,
               SUM(search_count) AS search_count,
               SUM(result_click_count) AS result_click_count,
               SUM(album_click_count) AS album_click_count,
               SUM(narrator_click_count) AS narrator_click_count,
               MAX(stat_date) AS latest_stat_date
        FROM search_keyword_stat
        WHERE {" AND ".join(conditions)}
        GROUP BY keyword
        ORDER BY search_count DESC, result_click_count DESC, keyword
        LIMIT %s
        """,
        tuple(params + [limit]),
    )
    return ok(
        {
            "keywords": [
                {
                    "keyword": row["keyword"],
                    "searchCount": int(row["search_count"] or 0),
                    "resultClickCount": int(row["result_click_count"] or 0),
                    "albumClickCount": int(row["album_click_count"] or 0),
                    "narratorClickCount": int(row["narrator_click_count"] or 0),
                    "latestStatDate": format_date(row["latest_stat_date"]),
                }
                for row in rows
            ]
        }
    )


@router.get("/search/suggestions", summary="查询搜索联想词")
def list_search_suggestions(
    keyword: Annotated[str, Query(min_length=1, description="搜索词或搜索前缀。")],
    limit: Annotated[int, Query(ge=1, le=20, description="返回数量上限。")] = 10,
):
    rows = fetch_all(
        """
        SELECT keyword, SUM(search_count) AS search_count
        FROM search_keyword_stat
        WHERE keyword LIKE %s
        GROUP BY keyword
        ORDER BY search_count DESC, keyword
        LIMIT %s
        """,
        (f"{keyword}%", limit),
    )
    if len(rows) < limit:
        extra = fetch_all(
            """
            SELECT album_title AS keyword, play_count AS search_count
            FROM audio_album
            WHERE album_status = 'published' AND album_title LIKE %s
            ORDER BY play_count DESC, id DESC
            LIMIT %s
            """,
            (f"%{keyword}%", limit - len(rows)),
        )
        rows.extend(extra)
    return ok(
        {
            "suggestions": [
                {
                    "keyword": row["keyword"],
                    "displayText": row["keyword"],
                    "searchCount": int(row.get("search_count") or 0),
                }
                for row in rows
            ]
        }
    )
