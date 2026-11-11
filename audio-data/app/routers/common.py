"""Shared API payload helpers."""

from __future__ import annotations

from typing import Any

from ..database import fetch_all, fetch_one
from ..utils import money


def first_or_none(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None


def current_price_rule(album_id: int) -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT *
        FROM album_price_rule
        WHERE album_id = %s
          AND yn = 1
          AND effective_from <= NOW()
          AND (effective_to IS NULL OR effective_to > NOW())
        ORDER BY effective_from DESC, id DESC
        LIMIT 1
        """,
        (album_id,),
    )


def primary_narrator(album_id: int) -> dict[str, Any] | None:
    row = fetch_one(
        """
        SELECT n.id, n.narrator_name, r.narrator_role
        FROM album_narrator_rel AS r
        JOIN content_narrator AS n ON n.id = r.narrator_id
        WHERE r.album_id = %s
        ORDER BY r.sort_no, r.id
        LIMIT 1
        """,
        (album_id,),
    )
    if row is None:
        return None
    return {
        "narratorId": row["id"],
        "narratorName": row["narrator_name"],
        "narratorRole": row["narrator_role"],
    }


def primary_author(album_id: int) -> dict[str, Any] | None:
    row = fetch_one(
        """
        SELECT a.id, a.author_name, r.author_role
        FROM album_author_rel AS r
        JOIN content_author AS a ON a.id = r.author_id
        WHERE r.album_id = %s
        ORDER BY r.sort_no, r.id
        LIMIT 1
        """,
        (album_id,),
    )
    if row is None:
        return None
    return {
        "authorId": row["id"],
        "authorName": row["author_name"],
        "authorRole": row["author_role"],
    }


def album_user_state(album_id: int, user_id: int | None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "favorited": False,
        "subscribed": False,
        "rated": False,
        "ratingScore": None,
        "entitled": False,
        "entitlementType": None,
        "lastTrackId": None,
        "lastPositionSeconds": None,
    }
    if user_id is None:
        return state
    shelf = fetch_one(
        """
        SELECT shelf_status, last_track_id, last_position_seconds
        FROM user_bookshelf
        WHERE user_id = %s AND album_id = %s
        """,
        (user_id, album_id),
    )
    if shelf:
        state["favorited"] = shelf["shelf_status"] in {
            "favorited",
            "subscribed",
            "finished",
        }
        state["subscribed"] = shelf["shelf_status"] == "subscribed"
        state["lastTrackId"] = shelf["last_track_id"]
        state["lastPositionSeconds"] = shelf["last_position_seconds"]
    rating = fetch_one(
        "SELECT rating_score FROM content_rating WHERE user_id = %s AND album_id = %s",
        (user_id, album_id),
    )
    if rating:
        state["rated"] = True
        state["ratingScore"] = money(rating["rating_score"])
    entitlement = fetch_one(
        """
        SELECT source_type
        FROM entitlement_record
        WHERE user_id = %s
          AND target_type = 'album'
          AND target_id = %s
          AND entitlement_status = 'active'
          AND valid_from <= NOW()
          AND (valid_to IS NULL OR valid_to >= NOW())
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id, album_id),
    )
    if entitlement:
        state["entitled"] = True
        state["entitlementType"] = "album"
    return state


def has_active_member(user_id: int | None) -> bool:
    if user_id is None:
        return False
    row = fetch_one(
        """
        SELECT id
        FROM member_account
        WHERE user_id = %s
          AND member_status = 'active'
          AND valid_from <= NOW()
          AND valid_to >= NOW()
        """,
        (user_id,),
    )
    return row is not None


def can_play_track(
    track: dict[str, Any], price_rule: dict[str, Any] | None, user_id: int | None
) -> dict[str, Any]:
    trial_end = int(track.get("trial_seconds") or 0)
    if price_rule is None:
        return {
            "canPlay": False,
            "canPlayFull": False,
            "needPurchase": True,
            "entitlementType": "trial" if trial_end else None,
            "trialEndSeconds": trial_end,
        }
    if (
        price_rule["price_type"] == "free"
        or int(track.get("free_flag") or 0) == 1
        or int(track.get("track_no") or 0) <= int(price_rule.get("free_track_count") or 0)
    ):
        return {
            "canPlay": True,
            "canPlayFull": True,
            "needPurchase": False,
            "entitlementType": "free",
            "trialEndSeconds": 0,
        }
    if price_rule["price_type"] == "vip_free" and has_active_member(user_id):
        return {
            "canPlay": True,
            "canPlayFull": True,
            "needPurchase": False,
            "entitlementType": "vip",
            "trialEndSeconds": 0,
        }
    if user_id is not None:
        row = fetch_one(
            """
            SELECT target_type
            FROM entitlement_record
            WHERE user_id = %s
              AND entitlement_status = 'active'
              AND valid_from <= NOW()
              AND (valid_to IS NULL OR valid_to >= NOW())
              AND (
                  (target_type = 'album' AND target_id = %s)
                  OR (target_type = 'track' AND target_id = %s)
              )
            ORDER BY FIELD(target_type, 'track', 'album'), id DESC
            LIMIT 1
            """,
            (user_id, track["album_id"], track["id"]),
        )
        if row:
            entitlement_type = "track" if row["target_type"] == "track" else "album"
            return {
                "canPlay": True,
                "canPlayFull": True,
                "needPurchase": False,
                "entitlementType": entitlement_type,
                "trialEndSeconds": 0,
            }
    return {
        "canPlay": trial_end > 0,
        "canPlayFull": False,
        "needPurchase": True,
        "entitlementType": "trial" if trial_end else None,
        "trialEndSeconds": trial_end,
    }


def album_summary(row: dict[str, Any], user_id: int | None = None) -> dict[str, Any]:
    rule = current_price_rule(int(row["id"]))
    state = album_user_state(int(row["id"]), user_id)
    state["entitled"] = bool(
        state["entitled"]
        or (rule and rule["price_type"] == "free")
        or (rule and rule["price_type"] == "vip_free" and has_active_member(user_id))
    )
    if state["entitled"] and state["entitlementType"] is None:
        state["entitlementType"] = (
            "free" if rule and rule["price_type"] == "free" else "vip"
        )
    return {
        "albumId": row["id"],
        "albumCode": row.get("album_code"),
        "albumTitle": row.get("album_title"),
        "albumType": row.get("album_type"),
        "coverUrl": row.get("cover_url"),
        "categoryName": row.get("category_name"),
        "languageCode": row.get("language_code"),
        "publishStatus": row.get("publish_status"),
        "trackCount": row.get("track_count"),
        "freeTrackCount": int(rule.get("free_track_count") or 0) if rule else 0,
        "playCount": row.get("play_count"),
        "favoriteCount": row.get("favorite_count"),
        "ratingScore": money(row.get("rating_score")),
        "priceType": rule.get("price_type") if rule else None,
        "albumPriceAmount": money(rule.get("album_price_amount")) if rule else None,
        "primaryNarrator": primary_narrator(int(row["id"])),
        "primaryAuthor": primary_author(int(row["id"])),
        **{
            key: state[key]
            for key in (
                "favorited",
                "subscribed",
                "entitled",
                "lastTrackId",
                "lastPositionSeconds",
            )
        },
    }


def track_progress(user_id: int | None, track_id: int) -> dict[str, Any]:
    if user_id is None:
        return {"lastPositionSeconds": None, "finishedFlag": None}
    row = fetch_one(
        """
        SELECT position_seconds, finished_flag
        FROM listening_progress
        WHERE user_id = %s AND track_id = %s
        """,
        (user_id, track_id),
    )
    if row is None:
        return {"lastPositionSeconds": None, "finishedFlag": None}
    return {
        "lastPositionSeconds": row["position_seconds"],
        "finishedFlag": row["finished_flag"],
    }


def target_name(target_type: str, target_id: int) -> str | None:
    table_map = {
        "vip": ("vip_plan", "plan_name"),
        "album": ("audio_album", "album_title"),
        "track": ("audio_track", "track_title"),
        "narrator": ("content_narrator", "narrator_name"),
        "organization": ("content_organization", "organization_name"),
        "topic": ("content_topic", "topic_title"),
    }
    mapping = table_map.get(target_type)
    if mapping is None:
        return None
    table, column = mapping
    row = fetch_one(f"SELECT {column} AS name FROM {table} WHERE id = %s", (target_id,))
    return None if row is None else row["name"]


def latest_topic_item_count(topic_id: int) -> int:
    row = fetch_one(
        "SELECT COUNT(*) AS total FROM content_topic_item WHERE topic_id = %s AND yn = 1",
        (topic_id,),
    )
    return int((row or {}).get("total") or 0)


def fetch_album_base(album_id: int) -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT
            a.*,
            c.category_name,
            l.language_code
        FROM audio_album AS a
        JOIN dim_audio_category AS c ON c.id = a.category_id
        JOIN dim_language AS l ON l.id = a.language_id
        WHERE a.id = %s
        """,
        (album_id,),
    )


def fetch_track_base(track_id: int) -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT
            t.*,
            a.album_title,
            a.cover_url,
            a.album_status,
            a.published_at AS album_published_at
        FROM audio_track AS t
        JOIN audio_album AS a ON a.id = t.album_id
        WHERE t.id = %s
        """,
        (track_id,),
    )


def fetch_authors(album_id: int) -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT a.id, a.author_name, r.author_role
        FROM album_author_rel AS r
        JOIN content_author AS a ON a.id = r.author_id
        WHERE r.album_id = %s
        ORDER BY r.sort_no, r.id
        """,
        (album_id,),
    )
    return [
        {
            "authorId": row["id"],
            "authorName": row["author_name"],
            "authorRole": row["author_role"],
        }
        for row in rows
    ]


def fetch_narrators(album_id: int) -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT n.id, n.narrator_name, r.narrator_role
        FROM album_narrator_rel AS r
        JOIN content_narrator AS n ON n.id = r.narrator_id
        WHERE r.album_id = %s
        ORDER BY r.sort_no, r.id
        """,
        (album_id,),
    )
    return [
        {
            "narratorId": row["id"],
            "narratorName": row["narrator_name"],
            "narratorRole": row["narrator_role"],
        }
        for row in rows
    ]


def fetch_tags(album_id: int) -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT t.id, t.tag_name
        FROM album_tag_rel AS r
        JOIN dim_content_tag AS t ON t.id = r.tag_id
        WHERE r.album_id = %s
        ORDER BY r.sort_no, r.id
        """,
        (album_id,),
    )
    return [{"tagId": row["id"], "tagName": row["tag_name"]} for row in rows]


def format_price_rule(rule: dict[str, Any] | None) -> dict[str, Any] | None:
    if rule is None:
        return None
    return {
        "priceType": rule["price_type"],
        "freeTrackCount": rule["free_track_count"],
        "albumPriceAmount": money(rule["album_price_amount"]),
        "trackPriceAmount": money(rule["track_price_amount"]),
        "vipFreeFlag": rule["price_type"] == "vip_free",
    }


def default_channel_id() -> int:
    row = fetch_one(
        """
        SELECT id
        FROM dim_channel
        WHERE yn = 1
        ORDER BY FIELD(channel_code, 'app', 'web'), id
        LIMIT 1
        """
    )
    return int(row["id"]) if row else 1


def target_exists(target_type: str, target_id: int | None) -> bool:
    if target_type == "none":
        return target_id is None
    if target_id is None:
        return False
    if target_type == "album":
        return fetch_one(
            """
            SELECT id
            FROM audio_album
            WHERE id = %s AND album_status IN ('published', 'paused')
            """,
            (target_id,),
        ) is not None
    if target_type == "track":
        return fetch_one(
            """
            SELECT t.id
            FROM audio_track t
            JOIN audio_album a ON a.id = t.album_id
            WHERE t.id = %s
              AND t.track_status = 'published'
              AND a.album_status IN ('published', 'paused')
            """,
            (target_id,),
        ) is not None
    if target_type == "topic":
        return fetch_one(
            """
            SELECT id
            FROM content_topic
            WHERE id = %s AND topic_status = 'published'
            """,
            (target_id,),
        ) is not None
    table_map = {
        "narrator": ("content_narrator", "yn = 1"),
        "author": ("content_author", "yn = 1"),
        "organization": ("content_organization", "yn = 1"),
        "comment": ("content_comment", "audit_status <> 'rejected'"),
        "content_order": ("content_order", "1 = 1"),
        "recharge_order": ("recharge_order", "1 = 1"),
        "payment": ("payment_record", "1 = 1"),
        "refund": ("refund_record", "1 = 1"),
        "report": ("content_report", "1 = 1"),
        "upload_task": ("content_upload_task", "1 = 1"),
    }
    mapping = table_map.get(target_type)
    if mapping is None:
        return False
    table, condition = mapping
    return fetch_one(
        f"SELECT id FROM {table} WHERE id = %s AND {condition}",
        (target_id,),
    ) is not None
