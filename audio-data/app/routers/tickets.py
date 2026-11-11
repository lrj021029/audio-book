"""Support-ticket APIs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query
from pydantic import BaseModel, Field

from ..database import db_cursor, fetch_all, fetch_one
from ..dependencies import get_current_user_id, get_optional_current_user_id
from ..errors import bad_request, not_found
from ..response import ok
from ..utils import count_total, format_datetime, local_now, make_no, offset_limit
from .common import target_exists, target_name

router = APIRouter(prefix="/api/v1", tags=["tickets"])

TICKET_TYPES = {
    "feature_feedback",
    "usage_feedback",
    "copyright_complaint",
    "payment_issue",
    "account_issue",
    "content_issue",
    "other",
}
RELATED_TYPES = {
    "none",
    "album",
    "track",
    "content_order",
    "recharge_order",
    "payment",
    "refund",
    "upload_task",
    "report",
}
PRIVATE_RELATED_TYPES = {
    "content_order",
    "recharge_order",
    "payment",
    "refund",
    "upload_task",
    "report",
}


class SupportTicketCreateRequest(BaseModel):
    ticketType: str = Field(
        description=(
            "工单类型。可选值：feature_feedback、usage_feedback、copyright_complaint、"
            "payment_issue、account_issue、content_issue、other。"
        )
    )
    relatedType: str = Field(
        default="none",
        description=(
            "关联对象类型。可选值：none、album、track、content_order、recharge_order、"
            "payment、refund、upload_task、report。"
        ),
    )
    relatedId: int | None = Field(
        default=None, description="关联对象 ID；relatedType=none 时可为空。"
    )
    contactMobile: str | None = Field(
        default=None, description="联系电话；未登录提交工单时 contactMobile 和 contactEmail 至少填一项。"
    )
    contactEmail: str | None = Field(
        default=None, description="联系邮箱；未登录提交工单时 contactMobile 和 contactEmail 至少填一项。"
    )
    ticketTitle: str = Field(description="工单标题；不能为空字符串。")
    ticketContent: str = Field(description="工单内容；不能为空字符串。")


def _ticket_payload(row: dict[str, Any], include_content: bool = False) -> dict[str, Any]:
    payload = {
        "ticketId": row["id"],
        "ticketNo": row["ticket_no"],
        "ticketType": row["ticket_type"],
        "relatedType": row["related_type"],
        "relatedId": row["related_id"],
        "ticketTitle": row["ticket_title"],
        "ticketStatus": row["ticket_status"],
        "submittedAt": format_datetime(row["submitted_at"]),
        "handledAt": format_datetime(row["handled_at"]),
        "closedAt": format_datetime(row["closed_at"]),
    }
    if include_content:
        payload.update(
            {
                "ticketContent": row["ticket_content"],
                "contactMobile": row["contact_mobile"],
                "contactEmail": row["contact_email"],
                "handleResult": row["handle_result"],
            }
        )
    return payload


def _related_object(related_type: str, related_id: int | None) -> dict[str, Any] | None:
    if related_type == "none" or related_id is None:
        return None
    title = target_name(related_type, related_id)
    if title is None:
        if related_type == "content_order":
            row = fetch_one("SELECT order_no AS title FROM content_order WHERE id = %s", (related_id,))
        elif related_type == "recharge_order":
            row = fetch_one("SELECT recharge_no AS title FROM recharge_order WHERE id = %s", (related_id,))
        elif related_type == "payment":
            row = fetch_one("SELECT payment_no AS title FROM payment_record WHERE id = %s", (related_id,))
        elif related_type == "refund":
            row = fetch_one("SELECT refund_no AS title FROM refund_record WHERE id = %s", (related_id,))
        else:
            row = None
        title = row["title"] if row else None
    return {"relatedType": related_type, "relatedId": related_id, "title": title}


def _private_related_owned(
    related_type: str, related_id: int | None, user_id: int | None
) -> bool:
    if related_type not in PRIVATE_RELATED_TYPES:
        return True
    if user_id is None or related_id is None:
        return False
    sql_map = {
        "content_order": (
            "SELECT id FROM content_order WHERE id = %s AND user_id = %s"
        ),
        "recharge_order": (
            "SELECT id FROM recharge_order WHERE id = %s AND user_id = %s"
        ),
        "payment": (
            """
            SELECT p.id
            FROM payment_record p
            LEFT JOIN content_order co
              ON co.id = p.pay_subject_id AND p.pay_subject_type = 'content_order'
            LEFT JOIN recharge_order ro
              ON ro.id = p.pay_subject_id AND p.pay_subject_type = 'recharge_order'
            WHERE p.id = %s AND COALESCE(co.user_id, ro.user_id) = %s
            """
        ),
        "refund": (
            """
            SELECT r.id
            FROM refund_record r
            JOIN payment_record p ON p.id = r.payment_id
            LEFT JOIN content_order co
              ON co.id = p.pay_subject_id AND p.pay_subject_type = 'content_order'
            LEFT JOIN recharge_order ro
              ON ro.id = p.pay_subject_id AND p.pay_subject_type = 'recharge_order'
            WHERE r.id = %s AND COALESCE(co.user_id, ro.user_id) = %s
            """
        ),
        "upload_task": (
            """
            SELECT task.id
            FROM content_upload_task task
            JOIN creator_profile creator ON creator.id = task.creator_id
            WHERE task.id = %s AND creator.user_id = %s
            """
        ),
        "report": "SELECT id FROM content_report WHERE id = %s AND user_id = %s",
    }
    return fetch_one(sql_map[related_type], (related_id, user_id)) is not None


@router.post("/support-tickets", summary="提交客服工单")
def create_support_ticket(
    body: Annotated[SupportTicketCreateRequest, Body()],
    current_user_id: Annotated[
        int | None, Depends(get_optional_current_user_id)
    ] = None,
):
    if body.ticketType not in TICKET_TYPES:
        raise bad_request("INVALID_TICKET_TYPE", "工单类型不合法")
    if body.relatedType not in RELATED_TYPES:
        raise bad_request("INVALID_RELATED_TYPE", "关联对象类型不合法")
    if not body.ticketTitle.strip():
        raise bad_request("EMPTY_TICKET_TITLE", "工单标题不能为空")
    if not body.ticketContent.strip():
        raise bad_request("EMPTY_TICKET_CONTENT", "工单内容不能为空")
    if current_user_id is None and not (body.contactMobile or body.contactEmail):
        raise bad_request("MISSING_CONTACT_INFO", "未登录提交工单必须填写联系方式")
    if not target_exists(body.relatedType, body.relatedId):
        raise not_found("SUPPORT_TICKET_RELATED_OBJECT_NOT_FOUND", "关联对象不存在")
    if not _private_related_owned(body.relatedType, body.relatedId, current_user_id):
        raise not_found("SUPPORT_TICKET_RELATED_OBJECT_NOT_FOUND", "关联对象不存在")
    now = local_now()
    ticket_no = make_no("TCK")
    with db_cursor() as (_, cursor):
        cursor.execute(
            """
            INSERT INTO support_ticket (
                ticket_no, user_id, ticket_type, related_type, related_id,
                ticket_title, ticket_content, contact_mobile, contact_email,
                ticket_status, submitted_at, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'submitted', %s, %s, %s)
            """,
            (
                ticket_no,
                current_user_id,
                body.ticketType,
                body.relatedType,
                body.relatedId,
                body.ticketTitle.strip(),
                body.ticketContent.strip(),
                body.contactMobile,
                body.contactEmail,
                now,
                now,
                now,
            ),
        )
        ticket_id = cursor.lastrowid
    return ok(
        {
            "ticketId": ticket_id,
            "ticketNo": ticket_no,
            "ticketStatus": "submitted",
            "submittedAt": format_datetime(now),
        }
    )


@router.get("/support-tickets", summary="分页查询客服工单")
def list_support_tickets(
    current_user_id: Annotated[int, Depends(get_current_user_id)],
    ticket_status: Annotated[
        str | None,
        Query(
            alias="ticketStatus",
            description="客服工单状态筛选。当前数据值：submitted、resolved。",
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
    if ticket_status:
        conditions.append("ticket_status = %s")
        params.append(ticket_status)
    where_sql = " AND ".join(conditions)
    total = count_total(
        f"SELECT COUNT(*) AS total FROM support_ticket WHERE {where_sql}",
        tuple(params),
    )
    rows = fetch_all(
        f"""
        SELECT *
        FROM support_ticket
        WHERE {where_sql}
        ORDER BY submitted_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, offset]),
    )
    return ok(
        {
            "list": [_ticket_payload(row) for row in rows],
            "pageNo": page_no,
            "pageSize": page_size,
            "total": total,
        }
    )


@router.get("/support-tickets/{ticketId}", summary="查询客服工单详情")
def get_support_ticket(
    ticket_id: Annotated[int, Path(alias="ticketId", description="客服工单 ID。")],
    current_user_id: Annotated[int, Depends(get_current_user_id)],
):
    row = fetch_one(
        """
        SELECT *
        FROM support_ticket
        WHERE id = %s AND user_id = %s
        """,
        (ticket_id, current_user_id),
    )
    if row is None:
        raise not_found("SUPPORT_TICKET_NOT_FOUND", "工单不存在")
    return ok(
        {
            "ticket": _ticket_payload(row, include_content=True),
            "relatedObject": _related_object(row["related_type"], row["related_id"]),
        }
    )
