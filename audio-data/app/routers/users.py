"""User profile and message APIs."""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id
from ..errors import bad_request, not_found
from ..response import ok
from ..utils import (
    count_total,
    format_date,
    format_datetime,
    json_value,
    local_now,
    money,
    offset_limit,
)

router = APIRouter(prefix="/api/v1", tags=["users"])


class ProfileUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, description="昵称；传入时不能为空字符串。")
    avatarUrl: str | None = Field(default=None, description="头像 URL。")
    gender: str | None = Field(
        default=None, description="性别。可选值：male、female、unknown。"
    )
    birthday: date | None = Field(default=None, description="生日。")
    province: str | None = Field(default=None, description="省份。")
    city: str | None = Field(default=None, description="城市。")
    occupation: str | None = Field(default=None, description="职业。")
    listeningScene: list[str] | None = Field(
        default=None, description="收听场景列表，写入用户画像 JSON。"
    )


def _message_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "messageId": row["id"],
        "messageNo": row["message_no"],
        "messageType": row["message_type"],
        "messageTitle": row["message_title"],
        "messageContent": row["message_content"],
        "targetType": row["target_type"],
        "targetId": row["target_id"],
        "readStatus": row["read_status"],
        "sentAt": format_datetime(row["sent_at"]),
        "readAt": format_datetime(row["read_at"]),
    }


@router.get("/me", summary="查询当前用户信息")
def get_me(current_user_id: Annotated[int, Depends(get_current_user_id)]):
    user = fetch_one("SELECT * FROM user_account WHERE id = %s", (current_user_id,))
    if user is None:
        raise not_found("USER_NOT_FOUND_OR_DISABLED", "当前用户不存在或不可用")
    profile = fetch_one("SELECT * FROM user_profile WHERE user_id = %s", (current_user_id,))
    member = fetch_one("SELECT * FROM member_account WHERE user_id = %s", (current_user_id,))
    wallet = fetch_one(
        """
        SELECT *
        FROM wallet_account
        WHERE user_id = %s
        ORDER BY FIELD(currency_code, 'CNY') DESC, id
        LIMIT 1
        """,
        (current_user_id,),
    )
    return ok(
        {
            "user": {
                "userId": user["id"],
                "userNo": user["user_no"],
                "nickname": user["nickname"],
                "avatarUrl": user["avatar_url"],
                "accountStatus": user["account_status"],
                "lastLoginAt": format_datetime(user["last_login_at"]),
            },
            "profile": None
            if profile is None
            else {
                "gender": profile["gender"],
                "birthday": format_date(profile["birthday"]),
                "province": profile["province"],
                "city": profile["city"],
                "occupation": profile["occupation"],
                "listeningScene": json_value(profile["listening_scene_payload"], []),
            },
            "member": None
            if member is None
            else {
                "memberLevel": member["member_level"],
                "memberStatus": member["member_status"],
                "pointsBalance": member["points_balance"],
                "growthValue": member["growth_value"],
                "validFrom": format_datetime(member["valid_from"]),
                "validTo": format_datetime(member["valid_to"]),
            },
            "wallet": None
            if wallet is None
            else {
                "walletId": wallet["id"],
                "availableAmount": money(wallet["available_amount"]),
                "currencyCode": wallet["currency_code"],
            },
        }
    )


@router.patch("/me/profile", summary="更新当前用户画像")
def update_profile(
    body: Annotated[ProfileUpdateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.gender is not None and body.gender not in {"male", "female", "unknown"}:
        raise bad_request("INVALID_GENDER", "性别不合法")
    now = local_now()
    with db_cursor() as (_, cursor):
        if body.nickname is not None or body.avatarUrl is not None:
            updates = []
            params: list[Any] = []
            if body.nickname is not None:
                if not body.nickname.strip():
                    raise bad_request("EMPTY_NICKNAME", "昵称不能为空")
                updates.append("nickname = %s")
                params.append(body.nickname.strip())
            if body.avatarUrl is not None:
                updates.append("avatar_url = %s")
                params.append(body.avatarUrl)
            updates.append("updated_at = %s")
            params.append(now)
            params.append(current_user_id)
            cursor.execute(
                f"UPDATE user_account SET {', '.join(updates)} WHERE id = %s",
                tuple(params),
            )
        profile = fetch_one("SELECT id FROM user_profile WHERE user_id = %s", (current_user_id,))
        payload = json.dumps(body.listeningScene, ensure_ascii=False) if body.listeningScene is not None else None
        if profile is None:
            cursor.execute(
                """
                INSERT INTO user_profile (
                    user_id, gender, birthday, province, city, occupation,
                    listening_scene_payload, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    current_user_id,
                    body.gender or "unknown",
                    body.birthday,
                    body.province,
                    body.city,
                    body.occupation,
                    payload,
                    now,
                    now,
                ),
            )
        else:
            updates = ["updated_at = %s"]
            params = [now]
            for column, value in (
                ("gender", body.gender),
                ("birthday", body.birthday),
                ("province", body.province),
                ("city", body.city),
                ("occupation", body.occupation),
                ("listening_scene_payload", payload),
            ):
                if value is not None:
                    updates.insert(-1, f"{column} = %s")
                    params.insert(-1, value)
            params.append(current_user_id)
            cursor.execute(
                f"UPDATE user_profile SET {', '.join(updates)} WHERE user_id = %s",
                tuple(params),
            )
    user = fetch_one("SELECT * FROM user_account WHERE id = %s", (current_user_id,))
    profile = fetch_one("SELECT * FROM user_profile WHERE user_id = %s", (current_user_id,))
    if user is None or profile is None:
        raise not_found("USER_PROFILE_NOT_FOUND", "用户资料不存在")
    return ok(
        {
            "user": {
                "userId": user["id"],
                "nickname": user["nickname"],
                "avatarUrl": user["avatar_url"],
            },
            "profile": {
                "gender": profile["gender"],
                "birthday": format_date(profile["birthday"]),
                "province": profile["province"],
                "city": profile["city"],
                "occupation": profile["occupation"],
                "listeningScene": json_value(profile["listening_scene_payload"], []),
            },
        }
    )


@router.get("/messages", summary="分页查询站内消息")
def list_messages(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    message_type: Annotated[
        str | None, Query(alias="messageType", description="消息类型筛选。当前数据值：system、trade。")
    ] = None,
    read_status: Annotated[
        str | None,
        Query(alias="readStatus", description="消息读取状态筛选。可选值：unread、read。"),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    offset, limit = offset_limit(page_no, page_size)
    conditions = ["receiver_user_id = %s"]
    params: list[Any] = [current_user_id]
    if message_type:
        conditions.append("message_type = %s")
        params.append(message_type)
    if read_status:
        conditions.append("read_status = %s")
        params.append(read_status)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"SELECT COUNT(*) AS total FROM user_message WHERE {where_sql}",
        tuple(params),
    )
    rows = fetch_all(
        f"""
        SELECT *
        FROM user_message
        WHERE {where_sql}
        ORDER BY sent_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [_message_payload(row) for row in rows],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.patch("/messages/{messageId}/read", summary="标记消息已读")
def read_message(
    message_id: Annotated[int, Path(alias="messageId", description="消息 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    row = fetch_one(
        """
        SELECT *
        FROM user_message
        WHERE id = %s AND receiver_user_id = %s
        """,
        (message_id, current_user_id),
    )
    if row is None:
        raise not_found("MESSAGE_NOT_FOUND", "消息不存在")
    if row["read_status"] == "read":
        return ok(
            {
                "messageId": message_id,
                "readStatus": "read",
                "readAt": format_datetime(row["read_at"]),
            }
        )
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            UPDATE user_message
            SET read_status = 'read',
                read_at = %s,
                updated_at = %s
            WHERE id = %s AND receiver_user_id = %s
            """,
            (now, now, message_id, current_user_id),
        )
    return ok({"messageId": message_id, "readStatus": "read", "readAt": format_datetime(now)})
