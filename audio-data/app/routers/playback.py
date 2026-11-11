"""Playback APIs."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id, get_optional_current_user_id
from ..errors import bad_request, not_found
from ..response import ok
from ..utils import count_total, format_datetime, local_now, make_no, offset_limit
from .common import (
    can_play_track,
    current_price_rule,
    default_channel_id,
    fetch_track_base,
)

router = APIRouter(prefix="/api/v1", tags=["playback"])


class PlayUrlCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"fileFormat": "mp3", "bitrateKbps": 64}}
    )

    fileFormat: Literal["mp3", "m4a", "aac"] | None = Field(
        default=None, description="音频格式。可选值：mp3、m4a、aac；不传则自动选择可用文件。"
    )
    bitrateKbps: int | None = Field(
        default=None, ge=1, description="码率，单位 kbps；不传则自动选择可用文件。"
    )


class PlaySessionCreateRequest(BaseModel):
    trackId: int = Field(description="章节 ID，对应 audio_track.id；当前用户必须有播放权限。")
    startPositionSeconds: int = Field(
        default=0, ge=0, description="起播位置，单位秒，不能超过章节总时长。"
    )
    channelId: int | None = Field(
        default=None, description="渠道 ID，对应 dim_channel.id；不传则使用默认启用渠道。"
    )


class PlaySessionUpdateRequest(BaseModel):
    endPositionSeconds: int = Field(ge=0, description="结束位置，单位秒，不能超过章节总时长。")
    playedSeconds: int = Field(ge=0, description="本次播放时长，单位秒。")
    playStatus: str = Field(
        description="播放状态。可选值：completed、interrupted、failed。"
    )


class ListeningProgressUpsertRequest(BaseModel):
    trackId: int = Field(description="章节 ID，对应 audio_track.id；当前用户必须有播放权限。")
    positionSeconds: int = Field(ge=0, description="播放进度位置，单位秒。")
    durationSeconds: int | None = Field(
        default=None, ge=0, description="章节时长，单位秒；不传则使用章节表中的时长。"
    )
    finishedFlag: bool = Field(default=False, description="是否听完。")


def _load_published_track(track_id: int) -> dict[str, Any]:
    track = fetch_track_base(track_id)
    if (
        track is None
        or track["track_status"] != "published"
        or track["album_status"] != "published"
    ):
        raise not_found("TRACK_NOT_FOUND", "章节不存在或未发布")
    return track


def _ensure_playable(track_id: int, user_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    track = _load_published_track(track_id)
    auth = can_play_track(track, current_price_rule(int(track["album_id"])), user_id)
    if not auth["canPlay"]:
        raise bad_request("TRACK_NOT_PLAYABLE", "当前用户无播放权限")
    return track, auth


def _purchase_options(
    track: dict[str, Any], price_rule: dict[str, Any] | None
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    if price_rule and price_rule["price_type"] == "album_paid":
        options.append(
            {
                "itemType": "album",
                "albumId": track["album_id"],
                "trackId": None,
                "priceAmount": price_rule["album_price_amount"],
                "currencyCode": price_rule["currency_code"],
            }
        )
    if price_rule and price_rule["price_type"] == "track_paid":
        options.append(
            {
                "itemType": "track",
                "albumId": track["album_id"],
                "trackId": track["id"],
                "priceAmount": price_rule["track_price_amount"],
                "currencyCode": price_rule["currency_code"],
            }
        )
    plans = fetch_all(
        """
        SELECT id, plan_name, member_level, sale_price_amount, currency_code
        FROM vip_plan
        WHERE yn = 1
        ORDER BY sale_price_amount, duration_days
        LIMIT 3
        """
    )
    for plan in plans:
        options.append(
            {
                "itemType": "vip_plan",
                "vipPlanId": plan["id"],
                "planName": plan["plan_name"],
                "memberLevel": plan["member_level"],
                "priceAmount": plan["sale_price_amount"],
                "currencyCode": plan["currency_code"],
            }
        )
    return options


def _progress_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "trackId": row["track_id"],
        "albumId": row["album_id"],
        "albumTitle": row.get("album_title"),
        "trackTitle": row.get("track_title"),
        "positionSeconds": row["position_seconds"],
        "durationSeconds": row["duration_seconds"],
        "finishedFlag": bool(row["finished_flag"]),
        "lastPlayedAt": format_datetime(row["last_played_at"]),
        "updatedAt": format_datetime(row["updated_at"]),
    }


def _upsert_progress(
    user_id: int,
    album_id: int,
    track_id: int,
    position_seconds: int,
    duration_seconds: int,
    finished_flag: bool,
) -> None:
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO listening_progress (
                user_id, album_id, track_id, position_seconds,
                duration_seconds, finished_flag, last_played_at,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                album_id = VALUES(album_id),
                position_seconds = VALUES(position_seconds),
                duration_seconds = VALUES(duration_seconds),
                finished_flag = VALUES(finished_flag),
                last_played_at = VALUES(last_played_at),
                updated_at = VALUES(updated_at)
            """,
            (
                user_id,
                album_id,
                track_id,
                position_seconds,
                duration_seconds,
                int(finished_flag),
                now,
                now,
                now,
            ),
        )
        cursor.execute(
            """
            INSERT INTO user_bookshelf (
                user_id, album_id, shelf_status, last_track_id,
                last_position_seconds, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                shelf_status = IF(
                    VALUES(shelf_status) = 'finished',
                    'finished',
                    IF(shelf_status = 'removed', 'subscribed', shelf_status)
                ),
                last_track_id = VALUES(last_track_id),
                last_position_seconds = VALUES(last_position_seconds),
                updated_at = VALUES(updated_at)
            """,
            (
                user_id,
                album_id,
                "finished" if finished_flag else "subscribed",
                track_id,
                position_seconds,
                now,
                now,
            ),
        )


@router.post("/tracks/{trackId}/play-url", summary="获取播放地址")
def create_play_url(
    track_id: Annotated[int, Path(alias="trackId", description="章节 ID。")],
    body: Annotated[
        PlayUrlCreateRequest | None,
        Body(examples=[{"fileFormat": "mp3", "bitrateKbps": 64}]),
    ] = None,
    current_user_id: Annotated[
        int | None, Depends(get_optional_current_user_id)
    ] = None,
):
    track = _load_published_track(track_id)
    price_rule = current_price_rule(int(track["album_id"]))
    auth = can_play_track(track, price_rule, current_user_id)
    conditions = ["track_id = %s", "file_status = 'available'", "is_current = 1"]
    params: list[Any] = [track_id]
    if body and body.fileFormat:
        conditions.append("file_format = %s")
        params.append(body.fileFormat)
    if body and body.bitrateKbps is not None:
        conditions.append("bitrate_kbps = %s")
        params.append(body.bitrateKbps)
    file_row = fetch_one(
        f"""
        SELECT *
        FROM track_audio_file
        WHERE {" AND ".join(conditions)}
        ORDER BY bitrate_kbps DESC, id DESC
        LIMIT 1
        """,
        tuple(params),
    )
    if file_row is None:
        raise not_found("TRACK_NOT_FOUND", "可播放音频文件不存在")
    audio_file = None
    if auth["canPlay"]:
        audio_file = {
            "fileId": file_row["id"],
            "fileFormat": file_row["file_format"],
            "bitrateKbps": file_row["bitrate_kbps"],
            "sampleRateHz": file_row["sample_rate_hz"],
            "durationSeconds": file_row["duration_seconds"],
            "fileUrl": file_row["file_url"],
        }
    return ok(
        {
            "trackId": track["id"],
            "albumId": track["album_id"],
            "canPlay": auth["canPlay"],
            "canPlayFull": auth["canPlayFull"],
            "needPurchase": auth["needPurchase"],
            "entitlementType": auth["entitlementType"],
            "trialEndSeconds": auth["trialEndSeconds"],
            "audioFile": audio_file,
            "purchaseOptions": [] if not auth["needPurchase"] else _purchase_options(track, price_rule),
        }
    )


@router.post("/play-sessions", summary="创建播放会话")
def create_play_session(
    body: Annotated[PlaySessionCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    track, _ = _ensure_playable(body.trackId, current_user_id)
    duration = int(track["duration_seconds"] or 0)
    if body.startPositionSeconds > duration:
        raise bad_request("INVALID_START_POSITION", "起播位置不能超过章节时长")
    channel_id = body.channelId or default_channel_id()
    if fetch_one("SELECT id FROM dim_channel WHERE id = %s AND yn = 1", (channel_id,)) is None:
        raise not_found("CHANNEL_NOT_FOUND", "渠道不存在或已停用")
    now = local_now()
    session_no = make_no("PLY")
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO play_session (
                session_no, user_id, album_id, track_id, channel_id,
                start_position_seconds, end_position_seconds, played_seconds,
                play_start_at, play_status, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s, 'interrupted', %s)
            """,
            (
                session_no,
                current_user_id,
                track["album_id"],
                track["id"],
                channel_id,
                body.startPositionSeconds,
                body.startPositionSeconds,
                now,
                now,
            ),
        )
        session_id = cursor.lastrowid
    return ok(
        {
            "sessionId": session_id,
            "sessionNo": session_no,
            "trackId": track["id"],
            "albumId": track["album_id"],
            "channelId": channel_id,
            "startPositionSeconds": body.startPositionSeconds,
            "playStatus": "interrupted",
            "playStartAt": format_datetime(now),
        }
    )


@router.patch("/play-sessions/{sessionId}", summary="更新播放会话")
def finish_play_session(
    session_id: Annotated[int, Path(alias="sessionId", description="播放会话 ID。")],
    body: Annotated[PlaySessionUpdateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.playStatus not in {"completed", "interrupted", "failed"}:
        raise bad_request("INVALID_PLAY_STATUS", "播放状态不合法")
    row = fetch_one(
        "SELECT * FROM play_session WHERE id = %s AND user_id = %s",
        (session_id, current_user_id),
    )
    if row is None:
        raise not_found("PLAY_SESSION_NOT_FOUND", "播放会话不存在")
    track = fetch_track_base(int(row["track_id"]))
    if track is None:
        raise not_found("TRACK_NOT_FOUND", "章节不存在")
    duration = int(track["duration_seconds"] or 0)
    if body.endPositionSeconds > duration:
        raise bad_request("INVALID_END_POSITION", "结束位置不能超过章节时长")
    end_position = body.endPositionSeconds
    finished = body.playStatus == "completed" or (duration > 0 and end_position >= duration * 0.95)
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            UPDATE play_session
            SET end_position_seconds = %s,
                played_seconds = %s,
                play_end_at = %s,
                play_status = %s
            WHERE id = %s AND user_id = %s
            """,
            (
                end_position,
                body.playedSeconds,
                now,
                body.playStatus,
                session_id,
                current_user_id,
            ),
        )
    _upsert_progress(
        current_user_id,
        int(row["album_id"]),
        int(row["track_id"]),
        end_position,
        duration,
        finished,
    )
    return ok(
        {
            "sessionId": session_id,
            "playStatus": body.playStatus,
            "playDurationSeconds": body.playedSeconds,
            "endPositionSeconds": end_position,
            "playedSeconds": body.playedSeconds,
            "playEndAt": format_datetime(now),
            "finishedFlag": finished,
        }
    )


@router.put("/listening-progress", summary="写入收听进度")
def upsert_listening_progress(
    body: Annotated[ListeningProgressUpsertRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    track, _ = _ensure_playable(body.trackId, current_user_id)
    duration = int(body.durationSeconds or track["duration_seconds"] or 0)
    if duration and body.positionSeconds > duration:
        raise bad_request("INVALID_PROGRESS_POSITION", "播放进度不能超过章节时长")
    position = body.positionSeconds
    _upsert_progress(
        current_user_id,
        int(track["album_id"]),
        int(track["id"]),
        position,
        duration,
        body.finishedFlag,
    )
    row = fetch_one(
        """
        SELECT *
        FROM listening_progress
        WHERE user_id = %s AND track_id = %s
        """,
        (current_user_id, body.trackId),
    )
    return ok(_progress_payload(row)) if row else ok()


@router.get("/listening-progress", summary="查询收听进度")
def list_listening_progress(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    album_id: Annotated[int | None, Query(alias="albumId", description="专辑 ID。")] = None,
    track_id: Annotated[int | None, Query(alias="trackId", description="章节 ID。")] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    offset, limit = offset_limit(page_no, page_size)
    conditions = ["p.user_id = %s"]
    params: list[Any] = [current_user_id]
    if album_id is not None:
        conditions.append("p.album_id = %s")
        params.append(album_id)
    if track_id is not None:
        conditions.append("p.track_id = %s")
        params.append(track_id)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"SELECT COUNT(*) AS total FROM listening_progress p WHERE {where_sql}",
        tuple(params),
    )
    rows = fetch_all(
        f"""
        SELECT p.*, a.album_title, t.track_title
        FROM listening_progress p
        JOIN audio_album a ON a.id = p.album_id
        JOIN audio_track t ON t.id = p.track_id
        WHERE {where_sql}
        ORDER BY last_played_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [_progress_payload(row) for row in rows],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )
