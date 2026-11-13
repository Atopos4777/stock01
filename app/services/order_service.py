"""订单与物流服务：归属校验下沉到 SQL 层，越权与不存在返回同一码。"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.db.models import Order, OrderItem
from app.db.session import session_scope


class OwnershipError(Exception):
    """归属校验失败：对外统一为 ORDER_NOT_ACCESSIBLE，不区分不存在/无权限。"""


def get_order(user_id: str, order_no: str) -> dict:
    order_no = (order_no or "").strip().upper()
    if not order_no.startswith("SO") or not order_no[2:].isdigit():
        raise ValueError("订单号格式不正确，应为 SO 开头加 10 位数字")
    with session_scope() as db:
        order = db.scalar(select(Order).where(Order.order_no == order_no))
        # 关键：不存在与不属于当前用户返回同一异常，避免枚举探测
        if order is None or order.user_id != user_id:
            raise OwnershipError("ORDER_NOT_ACCESSIBLE")
        items = db.scalars(select(OrderItem).where(OrderItem.order_no == order_no)).all()
        return {
            "order_no": order.order_no,
            # 敏感字段最小化：user_id 只返回掩码
            "user_masked": order.user_id[:2] + "***" + order.user_id[-1:],
            "status": order.status,
            "paid_amount": order.paid_amount,
            "created_at": order.created_at.isoformat(timespec="minutes"),
            "signed_at": order.signed_at.isoformat(timespec="minutes") if order.signed_at else None,
            "version": order.version,
            "items": [
                {
                    "sku_id": i.sku_id,
                    "title": i.title,
                    "category": i.category,
                    "qty": i.qty,
                    "unit_price": i.unit_price,
                }
                for i in items
            ],
        }


LOGISTICS_STEPS = {
    "PAID": ["已付款，等待仓库拣货"],
    "SHIPPED": ["已出库", "运输中，已到达分拨中心"],
    "SIGNED": ["已出库", "运输中", "派送中", "已签收"],
    "COMPLETED": ["已出库", "运输中", "已签收", "订单已完成"],
    "CANCELLED": ["订单已取消，退款原路退回"],
}


def get_logistics(user_id: str, order_no: str) -> dict:
    order = get_order(user_id, order_no)  # 复用归属校验
    steps = LOGISTICS_STEPS.get(order["status"], ["状态未知"])
    eta = None
    if order["status"] in {"PAID", "SHIPPED"}:
        base = datetime.fromisoformat(order["created_at"])
        eta = (base + timedelta(days=4)).isoformat(timespec="minutes")
    return {
        "order_no": order["order_no"],
        "status": order["status"],
        "steps": steps,
        "eta": eta,
        "note": "物流节点为模拟数据" if order["status"] != "SIGNED" else "已签收",
    }


def list_user_orders(user_id: str, limit: int = 5) -> list[dict]:
    with session_scope() as db:
        rows = db.scalars(
            select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(limit)
        ).all()
        return [
            {
                "order_no": o.order_no,
                "status": o.status,
                "paid_amount": o.paid_amount,
                "created_at": o.created_at.isoformat(timespec="minutes"),
            }
            for o in rows
        ]
