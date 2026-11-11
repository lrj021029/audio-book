"""Membership, order, payment and refund APIs."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, Path, Query
from pydantic import BaseModel, Field

from ..config import DEMO_PAYMENT_SIGNATURE
from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id, get_optional_current_user_id
from ..errors import bad_request, conflict, forbidden, not_found, unauthorized
from ..response import ok
from ..utils import (
    count_total,
    format_datetime,
    json_value,
    local_now,
    make_no,
    money,
    offset_limit,
)
from .common import current_price_rule, target_name

router = APIRouter(prefix="/api/v1", tags=["trade"])

CONTENT_PAYMENT_CHANNELS = {"wechat_pay", "alipay", "apple_pay", "balance", "coupon"}
RECHARGE_PAYMENT_CHANNELS = {"wechat_pay", "alipay", "apple_pay"}
PAYMENT_TERMINAL_STATUSES = {"success", "failed", "closed"}
REFUND_TERMINAL_STATUSES = {"rejected", "success", "failed"}


class OrderItemCreateRequest(BaseModel):
    itemType: str = Field(description="商品类型。可选值：vip_plan、album、track。")
    vipPlanId: int | None = Field(
        default=None, description="会员套餐 ID；itemType=vip_plan 时必填，对应 vip_plan.id。"
    )
    albumId: int | None = Field(
        default=None, description="专辑 ID；itemType=album 时必填，对应 audio_album.id。"
    )
    trackId: int | None = Field(
        default=None, description="章节 ID；itemType=track 时必填，对应 audio_track.id。"
    )
    quantity: int = Field(default=1, ge=1, description="购买数量，必须大于等于 1。")


class OrderCreateRequest(BaseModel):
    orderType: str = Field(description="订单类型。可选值：vip、album、track、bundle。")
    channelId: int | None = Field(
        default=None, description="渠道 ID，对应 dim_channel.id；不传则使用默认启用渠道。"
    )
    items: list[OrderItemCreateRequest] = Field(description="订单商品列表，不能为空。")


class PaymentCreateRequest(BaseModel):
    paySubjectType: str = Field(
        description="支付对象类型。可选值：content_order、recharge_order。"
    )
    paySubjectId: int = Field(description="支付对象 ID；必须与 paySubjectType 对应订单存在。")
    paymentChannel: str = Field(
        description=(
            "支付渠道。内容订单可选值：wechat_pay、alipay、apple_pay、balance、coupon；"
            "充值订单可选值：wechat_pay、alipay、apple_pay。"
        )
    )


class PaymentNotificationRequest(BaseModel):
    paymentNo: str = Field(description="支付流水号，对应 payment_record.payment_no。")
    paymentStatus: str = Field(description="支付状态。可选值：success、failed、closed。")
    paidAt: str | None = Field(default=None, description="支付时间；模拟回调中可为空。")


class RefundItemCreateRequest(BaseModel):
    orderItemId: int = Field(description="订单明细 ID，对应 content_order_item.id。")
    refundQuantity: int = Field(default=1, ge=1, description="退款数量，必须大于等于 1。")
    refundAmount: Decimal = Field(description="退款金额；累计退款不能超过支付金额。")


class RefundCreateRequest(BaseModel):
    paymentId: int = Field(description="支付流水 ID，对应 payment_record.id，且必须支付成功。")
    refundReason: str | None = Field(default=None, description="退款原因。")
    items: list[RefundItemCreateRequest] = Field(
        default_factory=list, description="退款明细；内容订单退款必填，充值退款不传。"
    )


class RefundNotificationRequest(BaseModel):
    refundNo: str = Field(description="退款单号，对应 refund_record.refund_no。")
    refundStatus: str = Field(
        description="退款处理状态。可选值：approved、rejected、success、failed。"
    )
    handleResult: str | None = Field(default=None, description="处理说明。")


def _channel_id(channel_id: int | None) -> int:
    if channel_id is not None:
        row = fetch_one("SELECT id FROM dim_channel WHERE id = %s AND yn = 1", (channel_id,))
        if row is None:
            raise not_found("CHANNEL_NOT_FOUND", "渠道不存在")
        return channel_id
    row = fetch_one("SELECT id FROM dim_channel WHERE yn = 1 ORDER BY id LIMIT 1")
    return int(row["id"]) if row else 1


def _order_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "orderId": row["id"],
        "orderNo": row["order_no"],
        "orderType": row["order_type"],
        "orderStatus": row["order_status"],
        "currencyCode": row["currency_code"],
        "totalAmount": money(row["total_amount"]),
        "discountAmount": money(row["discount_amount"]),
        "payableAmount": money(row["payable_amount"]),
        "paidAt": format_datetime(row["paid_at"]),
        "createdAt": format_datetime(row["created_at"]),
    }


def _order_item_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "itemId": row["id"],
        "itemType": row["item_type"],
        "vipPlanId": row["vip_plan_id"],
        "albumId": row["album_id"],
        "trackId": row["track_id"],
        "itemName": row["item_name"],
        "quantity": row["quantity"],
        "unitPriceAmount": money(row["unit_price_amount"]),
        "discountAmount": money(row["discount_amount"]),
        "payableAmount": money(row["payable_amount"]),
    }


def _payment_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "paymentId": row["id"],
        "paymentNo": row["payment_no"],
        "paySubjectType": row["pay_subject_type"],
        "paySubjectId": row["pay_subject_id"],
        "paymentChannel": row["payment_channel"],
        "paymentStatus": row["payment_status"],
        "paymentAmount": money(row["payment_amount"]),
        "currencyCode": row["currency_code"],
        "paidAt": format_datetime(row["paid_at"]),
        "createdAt": format_datetime(row["created_at"]),
    }


def _refund_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "refundId": row["id"],
        "refundNo": row["refund_no"],
        "refundStatus": row["refund_status"],
        "refundAmount": money(row["refund_amount"]),
        "refundReason": row["refund_reason"],
        "requestedAt": format_datetime(row["requested_at"]),
        "handledAt": format_datetime(row["handled_at"]),
        "refundedAt": format_datetime(row["refunded_at"]),
    }


def _price_order_item(body: OrderItemCreateRequest) -> dict[str, Any]:
    if body.itemType == "vip_plan":
        row = fetch_one("SELECT * FROM vip_plan WHERE id = %s AND yn = 1", (body.vipPlanId,))
        if row is None:
            raise not_found("ORDER_ITEM_NOT_AVAILABLE", "会员套餐不可购买")
        return {
            "item_type": "vip_plan",
            "vip_plan_id": row["id"],
            "album_id": None,
            "track_id": None,
            "item_name": row["plan_name"],
            "unit_price": Decimal(row["sale_price_amount"]),
            "currency_code": row["currency_code"],
        }
    if body.itemType == "album":
        album = fetch_one("SELECT * FROM audio_album WHERE id = %s AND album_status = 'published'", (body.albumId,))
        rule = current_price_rule(int(body.albumId or 0)) if album else None
        if album is None or rule is None or rule["price_type"] not in {"album_paid", "limited_free"}:
            raise not_found("ORDER_ITEM_NOT_AVAILABLE", "专辑不可购买")
        return {
            "item_type": "album",
            "vip_plan_id": None,
            "album_id": album["id"],
            "track_id": None,
            "item_name": album["album_title"],
            "unit_price": Decimal(rule["album_price_amount"]),
            "currency_code": rule["currency_code"],
        }
    if body.itemType == "track":
        track = fetch_one(
            """
            SELECT t.*, a.album_title
            FROM audio_track t
            JOIN audio_album a ON a.id = t.album_id
            WHERE t.id = %s AND t.track_status = 'published' AND a.album_status = 'published'
            """,
            (body.trackId,),
        )
        rule = current_price_rule(int(track["album_id"])) if track else None
        if track is None or rule is None or rule["price_type"] != "track_paid":
            raise not_found("ORDER_ITEM_NOT_AVAILABLE", "章节不可购买")
        return {
            "item_type": "track",
            "vip_plan_id": None,
            "album_id": None,
            "track_id": track["id"],
            "item_name": track["track_title"],
            "unit_price": Decimal(rule["track_price_amount"]),
            "currency_code": rule["currency_code"],
        }
    raise bad_request("INVALID_ITEM_TYPE", "商品类型不合法")


def _has_active_entitlement(user_id: int, item: dict[str, Any]) -> bool:
    if item["item_type"] == "vip_plan":
        plan = fetch_one(
            "SELECT member_level FROM vip_plan WHERE id = %s",
            (item["vip_plan_id"],),
        )
        member = fetch_one(
            """
            SELECT id
            FROM member_account
            WHERE user_id = %s
              AND member_status = 'active'
              AND member_level = %s
              AND valid_to >= NOW()
            """,
            (user_id, plan["member_level"] if plan else None),
        )
        return member is not None
    if item["item_type"] == "album":
        row = fetch_one(
            """
            SELECT id
            FROM entitlement_record
            WHERE user_id = %s
              AND target_type = 'album'
              AND target_id = %s
              AND entitlement_status = 'active'
              AND valid_from <= NOW()
              AND (valid_to IS NULL OR valid_to >= NOW())
            """,
            (user_id, item["album_id"]),
        )
        return row is not None
    if item["item_type"] == "track":
        row = fetch_one(
            """
            SELECT id
            FROM entitlement_record
            WHERE user_id = %s
              AND entitlement_status = 'active'
              AND valid_from <= NOW()
              AND (valid_to IS NULL OR valid_to >= NOW())
              AND (
                  (target_type = 'track' AND target_id = %s)
                  OR (target_type = 'album' AND target_id = (
                      SELECT album_id FROM audio_track WHERE id = %s
                  ))
              )
            """,
            (user_id, item["track_id"], item["track_id"]),
        )
        return row is not None
    return False


def _quote_order_items(
    items: list[OrderItemCreateRequest], user_id: int
) -> list[dict[str, Any]]:
    priced_items = [_price_order_item(item) | {"quantity": item.quantity} for item in items]
    for item in priced_items:
        if _has_active_entitlement(user_id, item):
            raise conflict("ORDER_ITEM_ALREADY_OWNED", "用户已拥有该商品权益")
    return priced_items


def _ensure_payment_subject(
    subject_type: str, subject_id: int, user_id: int
) -> dict[str, Any]:
    if subject_type == "content_order":
        row = fetch_one(
            "SELECT * FROM content_order WHERE id = %s AND user_id = %s",
            (subject_id, user_id),
        )
    elif subject_type == "recharge_order":
        row = fetch_one(
            "SELECT * FROM recharge_order WHERE id = %s AND user_id = %s",
            (subject_id, user_id),
        )
    else:
        raise bad_request("INVALID_PAY_SUBJECT_TYPE", "支付对象类型不合法")
    if row is None:
        raise not_found("PAY_SUBJECT_NOT_FOUND", "支付对象不存在")
    return row


def _cursor_fetch_one(
    cursor: Any, sql: str, params: tuple[Any, ...] | None = None
) -> dict[str, Any] | None:
    cursor.execute(sql, params)
    return cursor.fetchone()


def _cursor_fetch_all(
    cursor: Any, sql: str, params: tuple[Any, ...] | None = None
) -> list[dict[str, Any]]:
    cursor.execute(sql, params)
    return list(cursor.fetchall())


def _payment_subject_for_update(
    cursor: Any, subject_type: str, subject_id: int, user_id: int | None = None
) -> dict[str, Any]:
    user_condition = "" if user_id is None else " AND user_id = %s"
    params: tuple[Any, ...] = (
        (subject_id,) if user_id is None else (subject_id, user_id)
    )
    if subject_type == "content_order":
        row = _cursor_fetch_one(
            cursor,
            f"SELECT * FROM content_order WHERE id = %s{user_condition} FOR UPDATE",
            params,
        )
    elif subject_type == "recharge_order":
        row = _cursor_fetch_one(
            cursor,
            f"SELECT * FROM recharge_order WHERE id = %s{user_condition} FOR UPDATE",
            params,
        )
    else:
        raise bad_request("INVALID_PAY_SUBJECT_TYPE", "支付对象类型不合法")
    if row is None:
        raise not_found("PAY_SUBJECT_NOT_FOUND", "支付对象不存在")
    return row


@router.get("/vip-plans", summary="查询会员套餐")
def list_vip_plans(
    current_user_id: Annotated[
        int | None, Depends(get_optional_current_user_id)
    ] = None,
):
    rows = fetch_all(
        """
        SELECT *
        FROM vip_plan
        WHERE yn = 1
        ORDER BY FIELD(member_level, 'vip', 'svip'), duration_days, id
        """
    )
    member = None
    if current_user_id is not None:
        member = fetch_one("SELECT * FROM member_account WHERE user_id = %s", (current_user_id,))
    return ok(
        {
            "plans": [
                {
                    "planId": row["id"],
                    "planCode": row["plan_code"],
                    "planName": row["plan_name"],
                    "memberLevel": row["member_level"],
                    "durationDays": row["duration_days"],
                    "currencyCode": row["currency_code"],
                    "salePriceAmount": money(row["sale_price_amount"]),
                    "originalPriceAmount": money(row["original_price_amount"]),
                    "benefitPayload": json_value(row["benefit_payload"], {}),
                }
                for row in rows
            ],
            "currentMember": None
            if member is None
            else {
                "memberLevel": member["member_level"],
                "memberStatus": member["member_status"],
                "validFrom": format_datetime(member["valid_from"]),
                "validTo": format_datetime(member["valid_to"]),
            },
        }
    )


@router.get("/entitlements", summary="查询用户权益")
def list_entitlements(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    target_type: Annotated[
        str | None,
        Query(alias="targetType", description="权益目标对象类型。可选值：album、track、vip。"),
    ] = None,
    entitlement_status: Annotated[
        str | None,
        Query(alias="entitlementStatus", description="权益状态。可选值：active、revoked。"),
    ] = None,
):
    conditions = ["user_id = %s"]
    params: list[Any] = [current_user_id]
    if target_type:
        conditions.append("target_type = %s")
        params.append(target_type)
    if entitlement_status:
        conditions.append("entitlement_status = %s")
        params.append(entitlement_status)
    rows = fetch_all(
        f"""
        SELECT *
        FROM entitlement_record
        WHERE {" AND ".join(conditions)}
        ORDER BY valid_from DESC, id DESC
        """,
        tuple(params),
    )
    return ok(
        {
            "entitlements": [
                {
                    "entitlementId": row["id"],
                    "sourceType": row["source_type"],
                    "orderId": row["order_id"],
                    "targetType": row["target_type"],
                    "targetId": row["target_id"],
                    "targetName": target_name(row["target_type"], int(row["target_id"])),
                    "validFrom": format_datetime(row["valid_from"]),
                    "validTo": format_datetime(row["valid_to"]),
                    "entitlementStatus": row["entitlement_status"],
                }
                for row in rows
            ]
        }
    )


@router.post("/orders/preview", summary="预览订单金额")
def preview_order(
    body: Annotated[OrderCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.orderType not in {"vip", "album", "track", "bundle"}:
        raise bad_request("INVALID_ORDER_TYPE", "订单类型不合法")
    if not body.items:
        raise bad_request("EMPTY_ORDER_ITEMS", "订单商品不能为空")
    items = _quote_order_items(body.items, current_user_id)
    currency_codes = {item["currency_code"] for item in items}
    if len(currency_codes) != 1:
        raise bad_request("MIXED_CURRENCY_ORDER", "订单商品币种不一致")
    total_amount = sum(item["unit_price"] * item["quantity"] for item in items)
    return ok(
        {
            "orderType": body.orderType,
            "currencyCode": next(iter(currency_codes)),
            "totalAmount": money(total_amount),
            "discountAmount": 0.0,
            "payableAmount": money(total_amount),
            "items": [
                {
                    "itemType": item["item_type"],
                    "vipPlanId": item["vip_plan_id"],
                    "albumId": item["album_id"],
                    "trackId": item["track_id"],
                    "itemName": item["item_name"],
                    "quantity": item["quantity"],
                    "unitPriceAmount": money(item["unit_price"]),
                    "discountAmount": 0.0,
                    "payableAmount": money(item["unit_price"] * item["quantity"]),
                }
                for item in items
            ],
        }
    )


@router.post("/orders", summary="创建订单")
def create_order(
    body: Annotated[OrderCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    if body.orderType not in {"vip", "album", "track", "bundle"}:
        raise bad_request("INVALID_ORDER_TYPE", "订单类型不合法")
    if not body.items:
        raise bad_request("EMPTY_ORDER_ITEMS", "订单商品不能为空")
    items = _quote_order_items(body.items, current_user_id)
    currency_codes = {item["currency_code"] for item in items}
    if len(currency_codes) != 1:
        raise bad_request("MIXED_CURRENCY_ORDER", "订单商品币种不一致")
    total_amount = sum(item["unit_price"] * item["quantity"] for item in items)
    now = local_now()
    order_no = make_no("ORD")
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO content_order (
                order_no, user_id, channel_id, currency_code, order_type,
                order_status, total_amount, discount_amount, payable_amount,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, 'created', %s, 0, %s, %s, %s)
            """,
            (
                order_no,
                current_user_id,
                _channel_id(body.channelId),
                next(iter(currency_codes)),
                body.orderType,
                total_amount,
                total_amount,
                now,
                now,
            ),
        )
        order_id = cursor.lastrowid
        for item in items:
            cursor.execute(
                """
                INSERT INTO content_order_item (
                    order_id, item_type, vip_plan_id, album_id, track_id,
                    item_name, quantity, unit_price_amount, discount_amount,
                    payable_amount, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s)
                """,
                (
                    order_id,
                    item["item_type"],
                    item["vip_plan_id"],
                    item["album_id"],
                    item["track_id"],
                    item["item_name"],
                    item["quantity"],
                    item["unit_price"],
                    item["unit_price"] * item["quantity"],
                    now,
                ),
            )
    order = fetch_one("SELECT * FROM content_order WHERE id = %s", (order_id,))
    if order is None:
        raise not_found("ORDER_NOT_FOUND", "订单创建后回查失败")
    item_rows = fetch_all("SELECT * FROM content_order_item WHERE order_id = %s", (order_id,))
    return ok({"order": _order_payload(order), "items": [_order_item_payload(row) for row in item_rows]})


@router.get("/orders", summary="分页查询订单")
def list_orders(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    order_type: Annotated[
        str | None, Query(alias="orderType", description="订单类型。可选值：vip、album、track、bundle。")
    ] = None,
    order_status: Annotated[
        str | None,
        Query(
            alias="orderStatus",
            description="订单状态筛选。常见值：created、paying、paid、cancelled、refunding、refunded。",
        ),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    offset, limit = offset_limit(page_no, page_size)
    conditions = ["o.user_id = %s"]
    params: list[Any] = [current_user_id]
    if order_type:
        conditions.append("o.order_type = %s")
        params.append(order_type)
    if order_status:
        conditions.append("o.order_status = %s")
        params.append(order_status)
    where_sql = " AND ".join(conditions)
    total = count_total(f"SELECT COUNT(*) AS total FROM content_order o WHERE {where_sql}", tuple(params))
    rows = fetch_all(
        f"""
        SELECT o.*,
               (SELECT item_name FROM content_order_item WHERE order_id = o.id ORDER BY id LIMIT 1) AS first_item_name,
               (SELECT COUNT(*) FROM content_order_item WHERE order_id = o.id) AS item_count
        FROM content_order o
        WHERE {where_sql}
        ORDER BY o.created_at DESC, o.id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [
                {
                    **_order_payload(row),
                    "firstItemName": row["first_item_name"],
                    "itemCount": int(row["item_count"] or 0),
                }
                for row in rows
            ],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.get("/orders/{orderId}", summary="查询订单详情")
def get_order(
    order_id: Annotated[int, Path(alias="orderId", description="订单 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    order = fetch_one(
        "SELECT * FROM content_order WHERE id = %s AND user_id = %s",
        (order_id, current_user_id),
    )
    if order is None:
        raise not_found("ORDER_NOT_FOUND", "订单不存在")
    items = fetch_all("SELECT * FROM content_order_item WHERE order_id = %s ORDER BY id", (order_id,))
    payments = fetch_all("SELECT * FROM payment_record WHERE pay_subject_type = 'content_order' AND pay_subject_id = %s ORDER BY id", (order_id,))
    refunds = fetch_all("SELECT r.* FROM refund_record r WHERE r.refund_subject_type = 'content_order' AND r.refund_subject_id = %s ORDER BY r.id", (order_id,))
    entitlements = fetch_all("SELECT * FROM entitlement_record WHERE user_id = %s AND order_id = %s ORDER BY id", (current_user_id, order_id))
    return ok(
        {
            "order": _order_payload(order),
            "items": [_order_item_payload(row) for row in items],
            "payments": [_payment_payload(row) for row in payments],
            "refunds": [_refund_payload(row) for row in refunds],
            "entitlements": [
                {
                    "entitlementId": row["id"],
                    "targetType": row["target_type"],
                    "targetId": row["target_id"],
                    "targetName": target_name(row["target_type"], int(row["target_id"])),
                    "entitlementStatus": row["entitlement_status"],
                }
                for row in entitlements
            ],
        }
    )


@router.post("/payments", summary="创建支付流水")
def create_payment(
    body: Annotated[PaymentCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    subject = _ensure_payment_subject(body.paySubjectType, body.paySubjectId, current_user_id)
    channels = RECHARGE_PAYMENT_CHANNELS if body.paySubjectType == "recharge_order" else CONTENT_PAYMENT_CHANNELS
    if body.paymentChannel not in channels:
        raise bad_request("INVALID_PAYMENT_CHANNEL", "支付渠道不合法")
    payable = Decimal(subject["payable_amount"])
    status_field = "recharge_status" if body.paySubjectType == "recharge_order" else "order_status"
    if subject[status_field] not in {"created", "paying"}:
        raise conflict("PAY_SUBJECT_NOT_PAYABLE", "支付对象当前状态不可支付")
    if body.paymentChannel == "balance":
        wallet = fetch_one(
            "SELECT * FROM wallet_account WHERE user_id = %s AND currency_code = %s AND wallet_status = 'active'",
            (current_user_id, subject["currency_code"]),
        )
        if wallet is None or Decimal(wallet["available_amount"]) < payable:
            raise forbidden("WALLET_BALANCE_NOT_ENOUGH", "钱包余额不足")
    existing = fetch_one(
        """
        SELECT *
        FROM payment_record
        WHERE pay_subject_type = %s
          AND pay_subject_id = %s
          AND payment_status IN ('created', 'processing')
        ORDER BY id DESC
        LIMIT 1
        """,
        (body.paySubjectType, body.paySubjectId),
    )
    if existing:
        return ok({"payment": _payment_payload(existing)})
    now = local_now()
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO payment_record (
                payment_no, pay_subject_type, pay_subject_id, payment_channel,
                currency_code, payment_amount, payment_status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'created', %s, %s)
            """,
            (
                make_no("PAY"),
                body.paySubjectType,
                body.paySubjectId,
                body.paymentChannel,
                subject["currency_code"],
                payable,
                now,
                now,
            ),
        )
        payment_id = cursor.lastrowid
    payment = fetch_one("SELECT * FROM payment_record WHERE id = %s", (payment_id,))
    if payment is None:
        raise not_found("PAYMENT_NOT_FOUND", "支付流水创建后回查失败")
    return ok({"payment": _payment_payload(payment)})


def _insert_wallet_ledger(
    cursor: Any,
    wallet: dict[str, Any],
    ledger_type: str,
    related_type: str,
    related_id: int,
    amount_delta: Decimal,
) -> dict[str, Any]:
    balance_after = Decimal(wallet["balance_amount"]) + amount_delta
    frozen_after = Decimal(wallet["frozen_amount"])
    available_after = balance_after - frozen_after
    now = local_now()
    cursor.execute(
        """
        UPDATE wallet_account
        SET balance_amount = %s,
            available_amount = %s,
            updated_at = %s
        WHERE id = %s
        """,
        (balance_after, available_after, now, wallet["id"]),
    )
    ledger_no = make_no("WLT")
    cursor.execute(
        """
        INSERT INTO wallet_ledger (
            ledger_no, wallet_id, user_id, ledger_type, related_type,
            related_id, currency_code, amount_delta, frozen_delta,
            balance_after, frozen_after, available_after, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s, %s)
        """,
        (
            ledger_no,
            wallet["id"],
            wallet["user_id"],
            ledger_type,
            related_type,
            related_id,
            wallet["currency_code"],
            amount_delta,
            balance_after,
            frozen_after,
            available_after,
            now,
        ),
    )
    return {
        "ledgerId": cursor.lastrowid,
        "ledgerNo": ledger_no,
        "ledgerType": ledger_type,
        "amountDelta": money(amount_delta),
        "balanceAfter": money(balance_after),
        "availableAfter": money(available_after),
    }


def _grant_order_entitlements(cursor: Any, order: dict[str, Any], paid_at: Any) -> list[dict[str, Any]]:
    items = fetch_all("SELECT * FROM content_order_item WHERE order_id = %s", (order["id"],))
    created: list[dict[str, Any]] = []
    for item in items:
        if item["item_type"] == "vip_plan":
            plan = fetch_one("SELECT * FROM vip_plan WHERE id = %s", (item["vip_plan_id"],))
            if plan is None:
                continue
            member = fetch_one("SELECT * FROM member_account WHERE user_id = %s", (order["user_id"],))
            valid_from = paid_at
            valid_to = paid_at + timedelta(days=int(plan["duration_days"]))
            cursor.execute(
                """
                UPDATE member_account
                SET member_level = %s,
                    member_status = 'active',
                    valid_from = %s,
                    valid_to = GREATEST(COALESCE(valid_to, %s), %s),
                    updated_at = %s
                WHERE user_id = %s
                """,
                (
                    plan["member_level"],
                    valid_from,
                    valid_to,
                    valid_to,
                    paid_at,
                    order["user_id"],
                ),
            )
            if member is None:
                cursor.execute(
                    """
                    INSERT INTO member_account (
                        user_id, member_level, member_status, valid_from,
                        valid_to, created_at, updated_at
                    ) VALUES (%s, %s, 'active', %s, %s, %s, %s)
                    """,
                    (order["user_id"], plan["member_level"], valid_from, valid_to, paid_at, paid_at),
                )
            target_type, target_id, source_type = "vip", plan["id"], "vip"
        elif item["item_type"] == "album":
            target_type, target_id, source_type, valid_to = "album", item["album_id"], "purchase", None
        else:
            target_type, target_id, source_type, valid_to = "track", item["track_id"], "purchase", None
        cursor.execute(
            """
            INSERT IGNORE INTO entitlement_record (
                user_id, source_type, order_id, target_type, target_id,
                valid_from, valid_to, entitlement_status, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)
            """,
            (
                order["user_id"],
                source_type,
                order["id"],
                target_type,
                target_id,
                paid_at,
                valid_to,
                paid_at,
                paid_at,
            ),
        )
        created.append({"targetType": target_type, "targetId": target_id, "sourceType": source_type})
    return created


@router.post("/payment-notifications/mock", summary="模拟支付回调")
def handle_payment_notification(
    body: Annotated[PaymentNotificationRequest, Body()],
    signature: Annotated[
        str | None,
        Header(
            alias="X-Demo-Payment-Signature",
            description="模拟支付或退款回调签名。",
        ),
    ] = None,
):
    if signature != DEMO_PAYMENT_SIGNATURE:
        raise unauthorized("INVALID_PAYMENT_SIGNATURE", "支付回调签名不合法")
    if body.paymentStatus not in PAYMENT_TERMINAL_STATUSES:
        raise bad_request("INVALID_PAYMENT_STATUS", "支付状态不合法")
    paid_at = local_now()
    entitlements: list[dict[str, Any]] = []
    wallet_ledger = None
    with db_cursor() as (_, cursor):
        payment = _cursor_fetch_one(
            cursor,
            "SELECT * FROM payment_record WHERE payment_no = %s FOR UPDATE",
            (body.paymentNo,),
        )
        if payment is None:
            raise not_found("PAYMENT_NOT_FOUND", "支付记录不存在")
        if payment["payment_status"] not in PAYMENT_TERMINAL_STATUSES:
            cursor.execute(
                """
                UPDATE payment_record
                SET payment_status = %s,
                    paid_at = IF(%s = 'success', %s, paid_at),
                    updated_at = %s
                WHERE id = %s
                  AND payment_status NOT IN ('success', 'failed', 'closed')
                """,
                (
                    body.paymentStatus,
                    body.paymentStatus,
                    paid_at,
                    paid_at,
                    payment["id"],
                ),
            )
            if (
                body.paymentStatus == "success"
                and payment["pay_subject_type"] == "content_order"
            ):
                order = _payment_subject_for_update(
                    cursor, "content_order", int(payment["pay_subject_id"])
                )
                if payment["payment_channel"] == "balance":
                    wallet = _cursor_fetch_one(
                        cursor,
                        """
                        SELECT *
                        FROM wallet_account
                        WHERE user_id = %s AND currency_code = %s
                        FOR UPDATE
                        """,
                        (order["user_id"], order["currency_code"]),
                    )
                    if wallet:
                        wallet_ledger = _insert_wallet_ledger(
                            cursor,
                            wallet,
                            "consume",
                            "content_order",
                            int(order["id"]),
                            -Decimal(payment["payment_amount"]),
                        )
                cursor.execute(
                    """
                    UPDATE content_order
                    SET order_status = 'paid', paid_at = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (paid_at, paid_at, order["id"]),
                )
                entitlements = _grant_order_entitlements(cursor, order, paid_at)
            elif (
                body.paymentStatus == "success"
                and payment["pay_subject_type"] == "recharge_order"
            ):
                recharge = _payment_subject_for_update(
                    cursor, "recharge_order", int(payment["pay_subject_id"])
                )
                wallet = _cursor_fetch_one(
                    cursor,
                    "SELECT * FROM wallet_account WHERE id = %s FOR UPDATE",
                    (recharge["wallet_id"],),
                )
                if wallet:
                    wallet_ledger = _insert_wallet_ledger(
                        cursor,
                        wallet,
                        "recharge",
                        "recharge_order",
                        int(recharge["id"]),
                        Decimal(recharge["recharge_amount"]) + Decimal(recharge["gift_amount"]),
                    )
                cursor.execute(
                    """
                    UPDATE recharge_order
                    SET recharge_status = 'credited',
                        paid_at = %s,
                        credited_at = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (paid_at, paid_at, paid_at, recharge["id"]),
                )
        updated = _cursor_fetch_one(
            cursor, "SELECT * FROM payment_record WHERE id = %s", (payment["id"],)
        )
        if updated is None:
            raise not_found("PAYMENT_NOT_FOUND", "支付记录不存在")
        subject = _cursor_fetch_one(
            cursor,
            "SELECT order_status AS subject_status FROM content_order WHERE id = %s",
            (payment["pay_subject_id"],),
        ) if payment["pay_subject_type"] == "content_order" else _cursor_fetch_one(
            cursor,
            "SELECT recharge_status AS subject_status FROM recharge_order WHERE id = %s",
            (payment["pay_subject_id"],),
        )
    return ok(
        {
            "payment": _payment_payload(updated),
            "subject": {
                "subjectType": payment["pay_subject_type"],
                "subjectId": payment["pay_subject_id"],
                "subjectStatus": subject["subject_status"] if subject else None,
            },
            "entitlements": entitlements,
            "walletLedger": wallet_ledger,
        }
    )


@router.post("/refunds", summary="申请退款")
def create_refund(
    body: Annotated[RefundCreateRequest, Body()],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    now = local_now()
    with db_cursor() as (_, cursor):
        payment = _cursor_fetch_one(
            cursor,
            "SELECT * FROM payment_record WHERE id = %s FOR UPDATE",
            (body.paymentId,),
        )
        if payment is None or payment["payment_status"] != "success":
            raise conflict("PAYMENT_NOT_REFUNDABLE", "支付记录不可退款")
        subject = _payment_subject_for_update(
            cursor,
            payment["pay_subject_type"],
            int(payment["pay_subject_id"]),
            current_user_id,
        )
        if payment["pay_subject_type"] == "recharge_order" and body.items:
            raise bad_request("INVALID_REFUND_ITEMS", "充值退款不得提交内容订单明细")
        if payment["pay_subject_type"] == "content_order" and not body.items:
            raise bad_request("MISSING_REFUND_ITEMS", "内容订单退款必须提交退款明细")

        paid_amount = Decimal(payment["payment_amount"])
        refunded = _cursor_fetch_one(
            cursor,
            """
            SELECT COALESCE(SUM(refund_amount), 0) AS amount
            FROM refund_record
            WHERE payment_id = %s
              AND refund_status IN ('requested', 'approved', 'success')
            """,
            (body.paymentId,),
        )
        refunded_amount = Decimal(refunded["amount"]) if refunded else Decimal("0")
        validated_items: list[tuple[RefundItemCreateRequest, dict[str, Any]]] = []

        if payment["pay_subject_type"] == "content_order":
            seen_order_item_ids: set[int] = set()
            refund_amount = Decimal("0")
            for item in body.items:
                if item.orderItemId in seen_order_item_ids:
                    raise bad_request("DUPLICATE_REFUND_ITEM", "退款明细不能重复")
                seen_order_item_ids.add(item.orderItemId)
                if item.refundAmount <= 0:
                    raise bad_request("INVALID_REFUND_AMOUNT", "退款金额不合法")
                order_item = _cursor_fetch_one(
                    cursor,
                    """
                    SELECT *
                    FROM content_order_item
                    WHERE id = %s AND order_id = %s
                    FOR UPDATE
                    """,
                    (item.orderItemId, subject["id"]),
                )
                if order_item is None:
                    raise not_found("ORDER_ITEM_NOT_FOUND", "退款明细不存在")
                item_refunded = _cursor_fetch_one(
                    cursor,
                    """
                    SELECT
                        COALESCE(SUM(ri.refund_quantity), 0) AS quantity,
                        COALESCE(SUM(ri.refund_amount), 0) AS amount
                    FROM refund_record_item ri
                    JOIN refund_record r ON r.id = ri.refund_id
                    WHERE r.payment_id = %s
                      AND ri.order_item_id = %s
                      AND r.refund_status IN ('requested', 'approved', 'success')
                    """,
                    (body.paymentId, item.orderItemId),
                )
                refunded_quantity = int((item_refunded or {}).get("quantity") or 0)
                refunded_item_amount = Decimal(
                    (item_refunded or {}).get("amount") or 0
                )
                remaining_quantity = int(order_item["quantity"]) - refunded_quantity
                remaining_amount = Decimal(order_item["payable_amount"]) - refunded_item_amount
                if item.refundQuantity > remaining_quantity:
                    raise bad_request("INVALID_REFUND_QUANTITY", "退款数量不合法")
                if item.refundAmount > remaining_amount:
                    raise bad_request("INVALID_REFUND_AMOUNT", "退款金额不合法")
                refund_amount += item.refundAmount
                validated_items.append((item, order_item))
        else:
            refund_amount = paid_amount - refunded_amount

        if refund_amount <= 0 or refund_amount + refunded_amount > paid_amount:
            raise bad_request("INVALID_REFUND_AMOUNT", "退款金额不合法")

        cursor.execute(
            """
            INSERT INTO refund_record (
                refund_no, refund_subject_type, refund_subject_id, payment_id,
                refund_reason, refund_amount, refund_status, requested_at,
                created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, 'requested', %s, %s, %s)
            """,
            (
                make_no("RFD"),
                payment["pay_subject_type"],
                payment["pay_subject_id"],
                payment["id"],
                body.refundReason,
                refund_amount,
                now,
                now,
                now,
            ),
        )
        refund_id = cursor.lastrowid
        for item, order_item in validated_items:
            cursor.execute(
                """
                INSERT INTO refund_record_item (
                    refund_id, order_item_id, item_type,
                    refund_quantity, refund_amount, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    refund_id,
                    item.orderItemId,
                    order_item["item_type"],
                    item.refundQuantity,
                    item.refundAmount,
                    now,
                ),
            )
    refund = fetch_one("SELECT * FROM refund_record WHERE id = %s", (refund_id,))
    if refund is None:
        raise not_found("REFUND_NOT_FOUND", "退款单创建后回查失败")
    items = fetch_all("SELECT * FROM refund_record_item WHERE refund_id = %s", (refund_id,))
    return ok(
        {
            "refund": _refund_payload(refund),
            "items": [
                {
                    "refundItemId": row["id"],
                    "orderItemId": row["order_item_id"],
                    "itemType": row["item_type"],
                    "refundQuantity": row["refund_quantity"],
                    "refundAmount": money(row["refund_amount"]),
                }
                for row in items
            ],
        }
    )


def _revoke_refund_entitlements(cursor: Any, refund: dict[str, Any]) -> None:
    if refund["refund_subject_type"] != "content_order":
        return
    items = _cursor_fetch_all(
        cursor,
        """
        SELECT ri.*, oi.album_id, oi.track_id, oi.vip_plan_id
        FROM refund_record_item ri
        JOIN content_order_item oi ON oi.id = ri.order_item_id
        WHERE ri.refund_id = %s
        """,
        (refund["id"],),
    )
    if not items:
        cursor.execute(
            """
            UPDATE entitlement_record
            SET entitlement_status = 'revoked',
                updated_at = %s
            WHERE order_id = %s
              AND entitlement_status = 'active'
            """,
            (local_now(), refund["refund_subject_id"]),
        )
        return
    for item in items:
        if item["item_type"] == "album":
            target_type, target_id = "album", item["album_id"]
        elif item["item_type"] == "track":
            target_type, target_id = "track", item["track_id"]
        else:
            target_type, target_id = "vip", item["vip_plan_id"]
        cursor.execute(
            """
            UPDATE entitlement_record
            SET entitlement_status = 'revoked',
                updated_at = %s
            WHERE order_id = %s
              AND target_type = %s
              AND target_id = %s
              AND entitlement_status = 'active'
            """,
            (local_now(), refund["refund_subject_id"], target_type, target_id),
        )


@router.post("/refund-notifications/mock", summary="模拟退款回调")
def handle_refund_notification(
    body: Annotated[RefundNotificationRequest, Body()],
    signature: Annotated[
        str | None,
        Header(
            alias="X-Demo-Payment-Signature",
            description="模拟支付或退款回调签名。",
        ),
    ] = None,
):
    if signature != DEMO_PAYMENT_SIGNATURE:
        raise unauthorized("INVALID_PAYMENT_SIGNATURE", "退款回调签名不合法")
    if body.refundStatus not in {"approved", "rejected", "success", "failed"}:
        raise bad_request("INVALID_REFUND_STATUS", "退款状态不合法")
    now = local_now()
    wallet_ledger = None
    with db_cursor() as (_, cursor):
        refund = _cursor_fetch_one(
            cursor,
            "SELECT * FROM refund_record WHERE refund_no = %s FOR UPDATE",
            (body.refundNo,),
        )
        if refund is None:
            raise not_found("REFUND_NOT_FOUND", "退款单不存在")
        payment = _cursor_fetch_one(
            cursor,
            "SELECT * FROM payment_record WHERE id = %s FOR UPDATE",
            (refund["payment_id"],),
        )
        if payment is None:
            raise not_found("PAYMENT_NOT_FOUND", "支付记录不存在")
        if refund["refund_status"] not in REFUND_TERMINAL_STATUSES:
            cursor.execute(
                """
                UPDATE refund_record
                SET refund_status = %s,
                    handled_at = IF(%s IN ('approved', 'rejected', 'success', 'failed'), %s, handled_at),
                    refunded_at = IF(%s = 'success', %s, refunded_at),
                    updated_at = %s
                WHERE id = %s
                  AND refund_status NOT IN ('rejected', 'success', 'failed')
                """,
                (
                    body.refundStatus,
                    body.refundStatus,
                    now,
                    body.refundStatus,
                    now,
                    now,
                    refund["id"],
                ),
            )
            if body.refundStatus == "success":
                _revoke_refund_entitlements(cursor, refund)
                if refund["refund_subject_type"] == "content_order":
                    order = _payment_subject_for_update(
                        cursor, "content_order", int(refund["refund_subject_id"])
                    )
                    refunded = _cursor_fetch_one(
                        cursor,
                        """
                        SELECT COALESCE(SUM(refund_amount), 0) AS amount
                        FROM refund_record
                        WHERE refund_subject_type = 'content_order'
                          AND refund_subject_id = %s
                          AND refund_status = 'success'
                        """,
                        (order["id"],),
                    )
                    status = (
                        "refunded"
                        if Decimal((refunded or {}).get("amount") or 0) >= Decimal(order["payable_amount"])
                        else "refunding"
                    )
                    cursor.execute(
                        """
                        UPDATE content_order
                        SET order_status = %s,
                            updated_at = %s
                        WHERE id = %s
                        """,
                        (status, now, order["id"]),
                    )
                    if payment["payment_channel"] == "balance":
                        wallet = _cursor_fetch_one(
                            cursor,
                            """
                            SELECT *
                            FROM wallet_account
                            WHERE user_id = %s AND currency_code = %s
                            FOR UPDATE
                            """,
                            (order["user_id"], order["currency_code"]),
                        )
                        if wallet:
                            wallet_ledger = _insert_wallet_ledger(
                                cursor,
                                wallet,
                                "refund",
                                "refund",
                                int(refund["id"]),
                                Decimal(refund["refund_amount"]),
                            )
                elif refund["refund_subject_type"] == "recharge_order":
                    recharge = _payment_subject_for_update(
                        cursor, "recharge_order", int(refund["refund_subject_id"])
                    )
                    wallet = _cursor_fetch_one(
                        cursor,
                        "SELECT * FROM wallet_account WHERE id = %s FOR UPDATE",
                        (recharge["wallet_id"],),
                    )
                    if wallet:
                        wallet_ledger = _insert_wallet_ledger(
                            cursor,
                            wallet,
                            "refund",
                            "refund",
                            int(refund["id"]),
                            -Decimal(refund["refund_amount"]),
                        )
                    cursor.execute(
                        """
                        UPDATE recharge_order
                        SET recharge_status = 'refunded',
                            updated_at = %s
                        WHERE id = %s
                        """,
                        (now, recharge["id"]),
                    )
        updated = _cursor_fetch_one(
            cursor, "SELECT * FROM refund_record WHERE id = %s", (refund["id"],)
        )
        if updated is None:
            raise not_found("REFUND_NOT_FOUND", "退款单不存在")
    return ok({"refund": _refund_payload(updated), "walletLedger": wallet_ledger})


@router.get("/refunds", summary="分页查询退款单")
def list_refunds(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    refund_status: Annotated[
        str | None,
        Query(
            alias="refundStatus",
            description="退款状态。可选值：requested、approved、rejected、success、failed。",
        ),
    ] = None,
    page_no: Annotated[int, Query(alias="pageNo", description="页码，从 1 开始。")] = 1,
    page_size: Annotated[
        int, Query(alias="pageSize", description="每页数量，服务端限制为 1 到 100。")
    ] = 20,
):
    offset, limit = offset_limit(page_no, page_size)
    conditions = ["COALESCE(o.user_id, ro.user_id) = %s"]
    params: list[Any] = [current_user_id]
    if refund_status:
        conditions.append("r.refund_status = %s")
        params.append(refund_status)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"""
        SELECT COUNT(*) AS total
        FROM refund_record r
        JOIN payment_record p ON p.id = r.payment_id
        LEFT JOIN content_order o
          ON o.id = p.pay_subject_id AND p.pay_subject_type = 'content_order'
        LEFT JOIN recharge_order ro
          ON ro.id = p.pay_subject_id AND p.pay_subject_type = 'recharge_order'
        WHERE {where_sql}
        """,
        tuple(params),
    )
    rows = fetch_all(
        f"""
        SELECT r.*
        FROM refund_record r
        JOIN payment_record p ON p.id = r.payment_id
        LEFT JOIN content_order o
          ON o.id = p.pay_subject_id AND p.pay_subject_type = 'content_order'
        LEFT JOIN recharge_order ro
          ON ro.id = p.pay_subject_id AND p.pay_subject_type = 'recharge_order'
        WHERE {where_sql}
        ORDER BY r.requested_at DESC, r.id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [_refund_payload(row) for row in rows],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )
