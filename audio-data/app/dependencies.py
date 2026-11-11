"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

from .database import fetch_one
from .errors import not_found, unauthorized

RequiredUserIdHeader = Annotated[
    str | None,
    Header(alias="X-User-Id", description="当前用户 ID；需要用户身份的接口必填。"),
]

OptionalUserIdHeader = Annotated[
    str | None,
    Header(
        alias="X-User-Id",
        description="当前用户 ID；公共查询接口可不传，传入时必须为合法且启用的用户 ID。",
    ),
]


def get_current_user_id(x_user_id: RequiredUserIdHeader) -> int:
    if x_user_id is None or not x_user_id.strip():
        raise unauthorized("MISSING_USER_ID", "缺少请求头 X-User-Id")
    if not x_user_id.isdigit():
        raise unauthorized("INVALID_USER_ID", "X-User-Id 必须为合法数字")
    user_id = int(x_user_id)
    user = fetch_one(
        """
        SELECT id
        FROM user_account
        WHERE id = %s AND account_status = 'normal'
        """,
        (user_id,),
    )
    if user is None:
        raise not_found("USER_NOT_FOUND_OR_DISABLED", "当前用户不存在或不可用")
    return user_id


def get_optional_current_user_id(
    x_user_id: OptionalUserIdHeader = None,
) -> int | None:
    if x_user_id is None or not x_user_id.strip():
        return None
    return get_current_user_id(x_user_id)
