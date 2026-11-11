"""Wallet APIs."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id
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
from .trade import RECHARGE_PAYMENT_CHANNELS, _payment_payload

router = APIRouter(prefix="/api/v1", tags=["wallet"])


class RechargeOrderCreateRequest(BaseModel):
    walletId: int = Field(description="钱包 ID，对应 wallet_account.id，且必须属于当前用户。")
    channelId: int | None = Field(
        default=None, description="渠道 ID，对应 dim_channel.id；不传则使用默认启用渠道。"
    )
    rechargeAmount: Decimal = Field(description="充值金额，必须大于 0。")
    paymentChannel: str = Field(
        description="充值支付渠道。可选值：wechat_pay、alipay、apple_pay。"
    )


def _wallet_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "walletId": row["id"],
        "currencyCode": row["currency_code"],
        "walletStatus": row["wallet_status"],
        "balanceAmount": money(row["balance_amount"]),
        "frozenAmount": money(row["frozen_amount"]),
        "availableAmount": money(row["available_amount"]),
        "openedAt": format_datetime(row["opened_at"]),
    }


def _ledger_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ledgerId": row["id"],
        "ledgerNo": row["ledger_no"],
        "ledgerType": row["ledger_type"],
        "relatedType": row["related_type"],
        "relatedId": row["related_id"],
        "currencyCode": row["currency_code"],
        "amountDelta": money(row["amount_delta"]),
        "frozenDelta": money(row["frozen_delta"]),
        "balanceAfter": money(row["balance_after"]),
        "frozenAfter": money(row["frozen_after"]),
        "availableAfter": money(row["available_after"]),
        "createdAt": format_datetime(row["created_at"]),
    }


def _channel_id(channel_id: int | None) -> int:
    if channel_id is not None:
        row = fetch_one("SELECT id FROM dim_channel WHERE id = %s AND yn = 1", (channel_id,))
        if row is None:
            raise not_found("CHANNEL_NOT_FOUND", "渠道不存在")
        return channel_id
    row = fetch_one("SELECT id FROM dim_channel WHERE yn = 1 ORDER BY id LIMIT 1")
    return int(row["id"]) if row else 1


@router.get("/wallet", summary="查询钱包")
def get_wallet(current_user_id: Annotated[int, Depends(get_current_user_id)]):
    row = fetch_one(
        """
        SELECT *
        FROM wallet_account
        WHERE user_id = %s
        ORDER BY FIELD(currency_code, 'CNY') DESC, id
        LIMIT 1
        """,
        (current_user_id,),
    )
    if row is None:
        raise not_found("WALLET_NOT_FOUND", "钱包不存在")
    return ok({"wallet": _wallet_payload(row)})


@router.get("/wallet/ledgers", summary="分页查询钱包流水")
def list_wallet_ledgers(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    ledger_type: Annotated[
        str | None,
        Query(
            alias="ledgerType",
            description="钱包流水类型筛选。当前数据值：recharge、consume、refund。",
        ),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    offset, limit = offset_limit(page_no, page_size)
    conditions = ["user_id = %s"]
    params: list[Any] = [current_user_id]
    if ledger_type:
        conditions.append("ledger_type = %s")
        params.append(ledger_type)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"SELECT COUNT(*) AS total FROM wallet_ledger WHERE {where_sql}",
        tuple(params),
    )
    rows = fetch_all(
        f"""
        SELECT *
        FROM wallet_ledger
        WHERE {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [_ledger_payload(row) for row in rows],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.post("/recharge-orders", summary="创建充值订单")
def create_recharge_order(
    body: Annotated[RechargeOrderCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.rechargeAmount <= 0:
        raise bad_request("INVALID_RECHARGE_AMOUNT", "充值金额必须大于 0")
    if body.paymentChannel not in RECHARGE_PAYMENT_CHANNELS:
        raise bad_request("INVALID_PAYMENT_CHANNEL", "充值支付渠道不合法")
    wallet = fetch_one(
        """
        SELECT *
        FROM wallet_account
        WHERE id = %s AND user_id = %s AND wallet_status = 'active'
        """,
        (body.walletId, current_user_id),
    )
    if wallet is None:
        raise not_found("WALLET_NOT_FOUND", "钱包不存在")
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO recharge_order (
                recharge_no, user_id, wallet_id, channel_id, currency_code,
                recharge_amount, gift_amount, payable_amount,
                recharge_status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 0, %s, 'created', %s, %s)
            """,
            (
                make_no("RCH"),
                current_user_id,
                body.walletId,
                _channel_id(body.channelId),
                wallet["currency_code"],
                body.rechargeAmount,
                body.rechargeAmount,
                now,
                now,
            ),
        )
        recharge_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO payment_record (
                payment_no, pay_subject_type, pay_subject_id,
                payment_channel, currency_code, payment_amount,
                payment_status, created_at, updated_at
            ) VALUES (%s, 'recharge_order', %s, %s, %s, %s, 'created', %s, %s)
            """,
            (
                make_no("PAY"),
                recharge_id,
                body.paymentChannel,
                wallet["currency_code"],
                body.rechargeAmount,
                now,
                now,
            ),
        )
        payment_id = cursor.lastrowid
    recharge = fetch_one("SELECT * FROM recharge_order WHERE id = %s", (recharge_id,))
    payment = fetch_one("SELECT * FROM payment_record WHERE id = %s", (payment_id,))
    if recharge is None:
        raise not_found("RECHARGE_ORDER_NOT_FOUND", "充值订单创建后回查失败")
    if payment is None:
        raise not_found("PAYMENT_NOT_FOUND", "支付流水创建后回查失败")
    return ok(
        {
            "rechargeOrder": {
                "rechargeOrderId": recharge["id"],
                "rechargeNo": recharge["recharge_no"],
                "payableAmount": money(recharge["payable_amount"]),
                "rechargeStatus": recharge["recharge_status"],
            },
            "payment": _payment_payload(payment),
        }
    )
