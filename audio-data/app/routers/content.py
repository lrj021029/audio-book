"""Public content browsing APIs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from ..database import fetch_all, fetch_one
from ..dependencies import get_optional_current_user_id
from ..errors import not_found
from ..response import ok
from ..utils import count_total, format_datetime, money, offset_limit
from .common import (
    album_summary,
    album_user_state,
    can_play_track,
    current_price_rule,
    fetch_album_base,
    fetch_authors,
    fetch_narrators,
    fetch_tags,
    fetch_track_base,
    format_price_rule,
    latest_topic_item_count,
    target_name,
    track_progress,
)

router = APIRouter(prefix="/api/v1", tags=["content"])


@router.get("/categories", summary="查询音频分类树")
def list_categories(
    category_type: Annotated[
        str | None,
        Query(alias="categoryType", description="分类类型筛选，对应 dim_audio_category.category_type。"),
    ] = None,
    _: Annotated[int | None, Depends(get_optional_current_user_id)] = None,
):
    conditions = ["yn = 1"]
    params: list[Any] = []
    if category_type:
        conditions.append("category_type = %s")
        params.append(category_type)
    rows = fetch_all(
        f"""
        SELECT id, parent_id, category_code, category_name, category_level,
               category_type, sort_no
        FROM dim_audio_category
        WHERE {" AND ".join(conditions)}
        ORDER BY category_level, sort_no, id
        """,
        tuple(params),
    )
    node_by_id = {
        row["id"]: {
            "categoryId": row["id"],
            "categoryCode": row["category_code"],
            "categoryName": row["category_name"],
            "categoryLevel": row["category_level"],
            "categoryType": row["category_type"],
            "children": [],
        }
        for row in rows
    }
    roots: list[dict[str, Any]] = []
    for row in rows:
        node = node_by_id[row["id"]]
        parent_id = row["parent_id"]
        if parent_id and parent_id in node_by_id:
            node_by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return ok({"categories": roots})


@router.get("/tags", summary="查询内容标签树")
def list_tags(
    tag_type: Annotated[
        str | None, Query(alias="tagType", description="标签类型筛选，对应 dim_content_tag.tag_type。")
    ] = None,
    _: Annotated[int | None, Depends(get_optional_current_user_id)] = None,
):
    conditions = ["yn = 1"]
    params: list[Any] = []
    if tag_type:
        conditions.append("tag_type = %s")
        params.append(tag_type)
    rows = fetch_all(
        f"""
        SELECT id, parent_id, tag_code, tag_name, tag_type, sort_no
        FROM dim_content_tag
        WHERE {" AND ".join(conditions)}
        ORDER BY sort_no, id
        """,
        tuple(params),
    )
    node_by_id = {
        row["id"]: {
            "tagId": row["id"],
            "tagCode": row["tag_code"],
            "tagName": row["tag_name"],
            "tagType": row["tag_type"],
            "children": [],
        }
        for row in rows
    }
    roots: list[dict[str, Any]] = []
    for row in rows:
        node = node_by_id[row["id"]]
        parent_id = row["parent_id"]
        if parent_id and parent_id in node_by_id:
            node_by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)
    return ok({"tags": roots})


@router.get("/albums", summary="分页查询专辑")
def list_albums(
    current_user_id: Annotated[
        int | None, Depends(get_optional_current_user_id)
    ] = None,
    category_id: Annotated[
        int | None, Query(alias="categoryId", description="分类 ID，对应 dim_audio_category.id。")
    ] = None,
    tag_id: Annotated[int | None, Query(alias="tagId", description="标签 ID，对应 dim_content_tag.id。")] = None,
    album_type: Annotated[
        str | None, Query(alias="albumType", description="专辑类型。可选值：audiobook、program。")
    ] = None,
    price_type: Annotated[
        str | None,
        Query(
            alias="priceType",
            description="价格类型。可选值：free、vip_free、album_paid、track_paid。",
        ),
    ] = None,
    publish_status: Annotated[
        str | None,
        Query(alias="publishStatus", description="专辑发布进度状态。可选值：serializing、completed。"),
    ] = None,
    sort_by: Annotated[
        str,
        Query(alias="sortBy", description="排序方式。可选值：popular、newest、rating、favorite。"),
    ] = "popular",
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    offset, limit = offset_limit(page_no, page_size)
    conditions = ["a.album_status = 'published'"]
    params: list[Any] = []
    if category_id is not None:
        conditions.append("a.category_id = %s")
        params.append(category_id)
    if tag_id is not None:
        conditions.append(
            """
            EXISTS (
                SELECT 1 FROM album_tag_rel tr
                WHERE tr.album_id = a.id AND tr.tag_id = %s
            )
            """
        )
        params.append(tag_id)
    if album_type:
        conditions.append("a.album_type = %s")
        params.append(album_type)
    if publish_status:
        conditions.append("a.publish_status = %s")
        params.append(publish_status)
    if price_type:
        conditions.append(
            """
            EXISTS (
                SELECT 1 FROM album_price_rule pr
                WHERE pr.album_id = a.id
                  AND pr.yn = 1
                  AND pr.price_type = %s
                  AND pr.effective_from <= NOW()
                  AND (pr.effective_to IS NULL OR pr.effective_to > NOW())
            )
            """
        )
        params.append(price_type)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"SELECT COUNT(*) AS total FROM audio_album a WHERE {where_sql}",
        tuple(params),
    )
    order_sql = {
        "newest": "a.published_at DESC, a.id DESC",
        "rating": "a.rating_score DESC, a.id DESC",
        "favorite": "a.favorite_count DESC, a.id DESC",
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
    return ok(
        {
            "list": [album_summary(row, current_user_id) for row in rows],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.get("/albums/{albumId}", summary="查询专辑详情")
def get_album_detail(
    album_id: Annotated[int, Path(alias="albumId", description="专辑 ID。")],
    current_user_id: Annotated[
        int | None, Depends(get_optional_current_user_id)
    ] = None,
):
    row = fetch_album_base(album_id)
    if row is None or row["album_status"] != "published":
        raise not_found("ALBUM_NOT_FOUND", "专辑不存在或未发布")
    rule = current_price_rule(album_id)
    state = album_user_state(album_id, current_user_id)
    return ok(
        {
            "album": {
                "albumId": row["id"],
                "albumCode": row["album_code"],
                "albumTitle": row["album_title"],
                "albumType": row["album_type"],
                "coverUrl": row["cover_url"],
                "summary": row["summary"],
                "category": {
                    "categoryId": row["category_id"],
                    "categoryName": row["category_name"],
                },
                "languageCode": row["language_code"],
                "publishStatus": row["publish_status"],
                "publishedAt": format_datetime(row["published_at"]),
                "trackCount": row["track_count"],
                "totalDurationSeconds": row["total_duration_seconds"],
                "playCount": row["play_count"],
                "favoriteCount": row["favorite_count"],
                "ratingScore": money(row["rating_score"]),
            },
            "authors": fetch_authors(album_id),
            "narrators": fetch_narrators(album_id),
            "tags": fetch_tags(album_id),
            "priceRule": format_price_rule(rule),
            "userState": state,
        }
    )


@router.get("/albums/{albumId}/tracks", summary="分页查询专辑章节")
def list_album_tracks(
    album_id: Annotated[int, Path(alias="albumId", description="专辑 ID。")],
    current_user_id: Annotated[
        int | None, Depends(get_optional_current_user_id)
    ] = None,
    sort: Annotated[str, Query(description="排序方向。可选值：asc、desc。")] = "asc",
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    album = fetch_album_base(album_id)
    if album is None or album["album_status"] != "published":
        raise not_found("ALBUM_NOT_FOUND", "专辑不存在或未发布")
    offset, limit = offset_limit(page_no, page_size)
    total = count_total(
        """
        SELECT COUNT(*) AS total
        FROM audio_track
        WHERE album_id = %s AND track_status = 'published'
        """,
        (album_id,),
    )
    direction = "DESC" if sort == "desc" else "ASC"
    rows = fetch_all(
        f"""
        SELECT *
        FROM audio_track
        WHERE album_id = %s AND track_status = 'published'
        ORDER BY track_no {direction}, id {direction}
        LIMIT %s OFFSET %s
        """,
        (album_id, limit, offset),
    )
    rule = current_price_rule(album_id)
    items = []
    for row in rows:
        auth = can_play_track(row, rule, current_user_id)
        progress = track_progress(current_user_id, int(row["id"]))
        items.append(
            {
                "trackId": row["id"],
                "trackNo": row["track_no"],
                "trackTitle": row["track_title"],
                "durationSeconds": row["duration_seconds"],
                "freeFlag": row["free_flag"],
                "trackStatus": row["track_status"],
                "publishedAt": format_datetime(row["published_at"]),
                "playCount": row["play_count"],
                "needPurchase": auth["needPurchase"],
                "canPlayFull": auth["canPlayFull"],
                "trialEndSeconds": auth["trialEndSeconds"],
                **progress,
            }
        )
    return ok({"list": items, "pageNo": page_no, "pageSize": page_size, "total": total})


@router.get("/tracks/{trackId}", summary="查询章节详情")
def get_track_detail(
    track_id: Annotated[int, Path(alias="trackId", description="章节 ID。")],
    current_user_id: Annotated[
        int | None, Depends(get_optional_current_user_id)
    ] = None,
):
    row = fetch_track_base(track_id)
    if (
        row is None
        or row["track_status"] != "published"
        or row["album_status"] != "published"
    ):
        raise not_found("TRACK_NOT_FOUND", "章节不存在或未发布")
    rule = current_price_rule(int(row["album_id"]))
    auth = can_play_track(row, rule, current_user_id)
    return ok(
        {
            "track": {
                "trackId": row["id"],
                "albumId": row["album_id"],
                "trackNo": row["track_no"],
                "trackTitle": row["track_title"],
                "durationSeconds": row["duration_seconds"],
                "freeFlag": row["free_flag"],
                "trialSeconds": row["trial_seconds"],
                "publishedAt": format_datetime(row["published_at"]),
                "playCount": row["play_count"],
            },
            "album": {
                "albumId": row["album_id"],
                "albumTitle": row["album_title"],
                "coverUrl": row["cover_url"],
            },
            "userState": {**auth, **track_progress(current_user_id, track_id)},
        }
    )


@router.get("/narrators/{narratorId}", summary="查询主播主页")
def get_narrator_detail(
    narrator_id: Annotated[int, Path(alias="narratorId", description="主播 ID。")],
    current_user_id: Annotated[
        int | None, Depends(get_optional_current_user_id)
    ] = None,
):
    row = fetch_one("SELECT * FROM content_narrator WHERE id = %s", (narrator_id,))
    if row is None or int(row["yn"]) != 1:
        raise not_found("NARRATOR_NOT_FOUND", "主播不存在")
    albums = fetch_all(
        """
        SELECT a.id, a.album_title, a.cover_url, a.play_count, a.rating_score
        FROM album_narrator_rel r
        JOIN audio_album a ON a.id = r.album_id
        WHERE r.narrator_id = %s AND a.album_status = 'published'
        ORDER BY a.play_count DESC, a.id DESC
        LIMIT 10
        """,
        (narrator_id,),
    )
    activities = fetch_all(
        """
        SELECT id, feed_type, feed_title, feed_content, target_type, target_id, published_at
        FROM user_activity_feed
        WHERE target_type = 'narrator'
          AND target_id = %s
          AND visibility <> 'deleted'
        ORDER BY published_at DESC
        LIMIT 10
        """,
        (narrator_id,),
    )
    following = False
    if current_user_id is not None:
        following = (
            fetch_one(
                """
                SELECT id FROM user_follow
                WHERE user_id = %s AND target_type = 'narrator'
                  AND target_id = %s AND follow_status = 'following'
                """,
                (current_user_id, narrator_id),
            )
            is not None
        )
    return ok(
        {
            "narrator": {
                "narratorId": row["id"],
                "narratorName": row["narrator_name"],
                "avatarUrl": row["avatar_url"],
                "intro": row["intro"],
                "contractType": row["contract_type"],
                "followerCount": row["follower_count"],
                "albumCount": row["album_count"],
            },
            "albums": [
                {
                    "albumId": album["id"],
                    "albumTitle": album["album_title"],
                    "coverUrl": album["cover_url"],
                    "playCount": album["play_count"],
                    "ratingScore": money(album["rating_score"]),
                }
                for album in albums
            ],
            "activities": [
                {
                    "feedId": item["id"],
                    "feedType": item["feed_type"],
                    "feedTitle": item["feed_title"],
                    "feedContent": item["feed_content"],
                    "targetType": item["target_type"],
                    "targetId": item["target_id"],
                    "publishedAt": format_datetime(item["published_at"]),
                }
                for item in activities
            ],
            "userState": {"following": following},
        }
    )


@router.get("/rankings", summary="查询榜单")
def list_rankings(
    _: Annotated[int | None, Depends(get_optional_current_user_id)] = None,
    ranking_type: Annotated[
        str | None,
        Query(
            alias="rankingType",
            description=(
                "榜单类型。当前数据值：hot_album、paid_album、free_album、completed_album、"
                "commented_album、searched_album。"
            ),
        ),
    ] = None,
    category_id: Annotated[
        int | None, Query(alias="categoryId", description="分类 ID，对应 dim_audio_category.id。")
    ] = None,
    period_type: Annotated[
        str | None, Query(alias="periodType", description="榜单周期类型。可选值：weekly、monthly、total。")
    ] = None,
):
    conditions = ["yn = 1"]
    params: list[Any] = []
    if ranking_type:
        conditions.append("ranking_type = %s")
        params.append(ranking_type)
    if category_id is not None:
        conditions.append("category_id = %s")
        params.append(category_id)
    if period_type:
        conditions.append("period_type = %s")
        params.append(period_type)
    rankings = fetch_all(
        f"""
        SELECT *
        FROM ranking_list
        WHERE {" AND ".join(conditions)}
        ORDER BY id
        """,
        tuple(params),
    )
    payload = []
    for ranking in rankings:
        items = fetch_all(
            """
            SELECT *
            FROM ranking_item
            WHERE ranking_id = %s
              AND stat_date = (
                  SELECT MAX(stat_date) FROM ranking_item WHERE ranking_id = %s
              )
            ORDER BY rank_no
            LIMIT 50
            """,
            (ranking["id"], ranking["id"]),
        )
        payload.append(
            {
                "rankingId": ranking["id"],
                "rankingCode": ranking["ranking_code"],
                "rankingName": ranking["ranking_name"],
                "rankingType": ranking["ranking_type"],
                "periodType": ranking["period_type"],
                "items": [
                    {
                        "rankNo": item["rank_no"],
                        "targetType": item["target_type"],
                        "targetId": item["target_id"],
                        "targetName": target_name(
                            item["target_type"], int(item["target_id"])
                        ),
                        "coverUrl": _target_cover(item["target_type"], int(item["target_id"])),
                        "metricValue": money(item["score_value"]),
                    }
                    for item in items
                ],
            }
        )
    return ok({"rankings": payload})


@router.get("/topics", summary="分页查询专题")
def list_topics(
    _: Annotated[int | None, Depends(get_optional_current_user_id)] = None,
    topic_type: Annotated[
        str | None, Query(alias="topicType", description="专题类型筛选，对应 content_topic.topic_type。")
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    offset, limit = offset_limit(page_no, page_size)
    conditions = ["topic_status = 'published'"]
    params: list[Any] = []
    if topic_type:
        conditions.append("topic_type = %s")
        params.append(topic_type)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"SELECT COUNT(*) AS total FROM content_topic WHERE {where_sql}",
        tuple(params),
    )
    rows = fetch_all(
        f"""
        SELECT *
        FROM content_topic
        WHERE {where_sql}
        ORDER BY published_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [
                {
                    "topicId": row["id"],
                    "topicCode": row["topic_code"],
                    "topicTitle": row["topic_title"],
                    "topicType": row["topic_type"],
                    "coverUrl": row["cover_url"],
                    "summary": row["summary"],
                    "publishedAt": format_datetime(row["published_at"]),
                    "itemCount": latest_topic_item_count(int(row["id"])),
                }
                for row in rows
            ],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.get("/topics/{topicId}", summary="查询专题详情")
def get_topic_detail(
    topic_id: Annotated[int, Path(alias="topicId", description="专题 ID。")],
    _: Annotated[int | None, Depends(get_optional_current_user_id)] = None,
):
    row = fetch_one("SELECT * FROM content_topic WHERE id = %s", (topic_id,))
    if row is None or row["topic_status"] != "published":
        raise not_found("TOPIC_NOT_FOUND", "专题不存在或未发布")
    items = fetch_all(
        """
        SELECT *
        FROM content_topic_item
        WHERE topic_id = %s AND yn = 1
        ORDER BY sort_no, id
        """,
        (topic_id,),
    )
    return ok(
        {
            "topic": {
                "topicId": row["id"],
                "topicCode": row["topic_code"],
                "topicTitle": row["topic_title"],
                "topicType": row["topic_type"],
                "coverUrl": row["cover_url"],
                "summary": row["summary"],
                "publishedAt": format_datetime(row["published_at"]),
            },
            "items": [
                {
                    "itemId": item["id"],
                    "targetType": item["target_type"],
                    "targetId": item["target_id"],
                    "title": item["title"] or target_name(item["target_type"], item["target_id"]),
                    "summary": item["summary"],
                    "imageUrl": item["image_url"] or _target_cover(item["target_type"], item["target_id"]),
                    "sortNo": item["sort_no"],
                }
                for item in items
            ],
        }
    )


@router.get("/recommend-slots/{slotCode}/items", summary="查询推荐位明细")
def list_recommend_items(
    slot_code: Annotated[str, Path(alias="slotCode", description="推荐位编码。")],
    _: Annotated[int | None, Depends(get_optional_current_user_id)] = None,
):
    slot = fetch_one(
        "SELECT * FROM recommend_slot WHERE slot_code = %s AND yn = 1",
        (slot_code,),
    )
    if slot is None:
        raise not_found("RECOMMEND_SLOT_NOT_FOUND", "推荐位不存在或已停用")
    items = fetch_all(
        """
        SELECT *
        FROM recommend_item
        WHERE slot_id = %s
          AND yn = 1
          AND effective_from <= NOW()
          AND (effective_to IS NULL OR effective_to > NOW())
        ORDER BY sort_no, id
        LIMIT %s
        """,
        (slot["id"], slot["max_item_count"]),
    )
    return ok(
        {
            "slot": {
                "slotId": slot["id"],
                "slotCode": slot["slot_code"],
                "slotName": slot["slot_name"],
                "slotType": slot["slot_type"],
                "maxItemCount": slot["max_item_count"],
            },
            "items": [
                {
                    "itemId": item["id"],
                    "targetType": item["target_type"],
                    "targetId": item["target_id"],
                    "title": item["title"]
                    or (
                        target_name(item["target_type"], item["target_id"])
                        if item["target_id"]
                        else None
                    ),
                    "imageUrl": item["image_url"]
                    or (
                        _target_cover(item["target_type"], item["target_id"])
                        if item["target_id"]
                        else None
                    ),
                    "jumpUrl": item["jump_url"],
                    "sortNo": item["sort_no"],
                }
                for item in items
            ],
        }
    )


def _target_cover(target_type: str, target_id: int) -> str | None:
    if target_type == "album":
        row = fetch_one("SELECT cover_url FROM audio_album WHERE id = %s", (target_id,))
        return None if row is None else row["cover_url"]
    if target_type == "topic":
        row = fetch_one("SELECT cover_url FROM content_topic WHERE id = %s", (target_id,))
        return None if row is None else row["cover_url"]
    if target_type == "narrator":
        row = fetch_one(
            "SELECT avatar_url FROM content_narrator WHERE id = %s", (target_id,)
        )
        return None if row is None else row["avatar_url"]
    return None
