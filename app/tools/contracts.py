"""工具实现：所有业务能力在此封装，参数已校验，身份由服务端注入。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.cache import idempotency
from app.db.models import AfterSaleApplication, AfterSaleDraft, Order
from app.db.session import session_scope
from app.rag import grounding, policy_store
from app.retrieval import index as product_index
from app.services import after_sales_rules, order_service, product_service


# ---------- 商品 ----------
def search_products(query: str, category: str | None = None, price_max: float | None = None,
                    price_min: float | None = None, top_k: int = 3) -> dict:
    filters = {
        "category": category,
        "price_max": price_max,
        "price_min": price_min,
        "in_stock": True,
    }
    result = product_index.search(query, filters=filters, top_k=top_k)
    cards = [
        {
            "sku_id": c["sku_id"],
            "title": c["title"],
            "brand": c["brand"],
            "category": c["category"],
            "price": c["price"],
            "available_qty": c["available_qty"],
            "rating": c["rating"],
            "sales_30d": c["sales_30d"],
            "explain": c["explain"],
            "score": c["score"],
            "review": c["review_summary"],
        }
        for c in result["candidates"]
    ]
    return {"cards": cards, "meta": result["meta"]}


def get_live_offer(sku_ids: list[str]) -> dict:
    data = product_service.get_live_offer(sku_ids)
    return {
        "offers": data,
        "queried_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": "价格与库存为实时查询结果，不来自知识库",
    }


# ---------- 订单 ----------
def get_order(user_id: str, order_no: str) -> dict:
    return order_service.get_order(user_id, order_no)


def get_logistics(user_id: str, order_no: str) -> dict:
    return order_service.get_logistics(user_id, order_no)


def list_orders(user_id: str, limit: int = 5) -> dict:
    return {"orders": order_service.list_user_orders(user_id, limit=limit)}


# ---------- 售后 ----------
def evaluate_after_sale(user_id: str, order_no: str, reason: str) -> dict:
    return after_sales_rules.evaluate(user_id, order_no, reason)


def create_after_sale_draft(user_id: str, order_no: str, reason: str, scene: str | None = None) -> dict:
    evaluation = after_sales_rules.evaluate(user_id, order_no, reason)
    if evaluation.get("code") == "ORDER_NOT_ACCESSIBLE":
        raise order_service.OwnershipError("ORDER_NOT_ACCESSIBLE")

    with session_scope() as db:
        order = db.scalar(select(Order).where(Order.order_no == order_no, Order.user_id == user_id))
        if order is None:
            raise order_service.OwnershipError("ORDER_NOT_ACCESSIBLE")
        draft_id = f"DR{uuid.uuid4().hex[:10].upper()}"
        draft = AfterSaleDraft(
            draft_id=draft_id,
            order_no=order_no,
            user_id=user_id,
            scene=evaluation.get("scene", scene or "no_reason"),
            reason=reason[:200],
            refund_amount=evaluation.get("refund_amount", 0.0),
            rule_version=evaluation.get("rule_version", "N/A"),
            expected_order_version=order.version,
            risk_level=evaluation.get("risk_level", "medium"),
            status="AWAIT_CONFIRM" if evaluation.get("eligible") else "REJECTED",
        )
        db.add(draft)
    return {"draft_id": draft_id, "status": draft.status, "evaluation": evaluation}


def confirm_after_sale(draft_id: str, user_id: str, idempotency_key: str,
                       user_confirmed: bool = True, expected_order_version: int | None = None,
                       trace_id: str = "") -> dict:
    """写操作唯一入口：归属 → 状态 → 规则版本 → 订单版本 → 幂等 → 事务提交。"""
    key = f"{draft_id}:{idempotency_key}"

    def _do() -> dict:
        if not user_confirmed:
            return {"status": "REJECTED", "reason": "用户未确认，未提交"}
        with session_scope() as db:
            draft = db.scalar(select(AfterSaleDraft).where(AfterSaleDraft.draft_id == draft_id))
            if draft is None or draft.user_id != user_id:
                # 不区分不存在/无权限
                raise order_service.OwnershipError("DRAFT_NOT_ACCESSIBLE")
            if draft.status not in {"AWAIT_CONFIRM", "DRAFTED"}:
                return {"status": draft.status, "reason": "草稿状态不允许提交", "draft_id": draft_id}

            order = db.scalar(select(Order).where(Order.order_no == draft.order_no))
            if order is None:
                raise order_service.OwnershipError("ORDER_NOT_ACCESSIBLE")

            # 订单版本冲突：并发变更必须重新评估
            expect = expected_order_version if expected_order_version is not None else draft.expected_order_version
            if order.version != expect:
                return {
                    "status": "CONFLICT",
                    "reason": f"订单状态已变更（期望 version={expect}，当前 {order.version}），需重新评估",
                    "draft_id": draft_id,
                }

            # 规则版本仍生效校验
            rule = after_sales_rules.get_active_rule(
                (order_service.get_order(user_id, draft.order_no)["items"][0]["category"]), draft.scene
            )
            if rule is not None and rule.version != draft.rule_version:
                return {
                    "status": "CONFLICT",
                    "reason": f"售后规则已更新（{draft.rule_version} → {rule.version}），需重新评估",
                    "draft_id": draft_id,
                }

            application_id = f"AS{datetime.now().strftime('%Y%m%d')}{uuid.uuid4().hex[:6].upper()}"
            app_row = AfterSaleApplication(
                application_id=application_id,
                draft_id=draft_id,
                idempotency_key=key,
                order_no=draft.order_no,
                user_id=user_id,
                amount=draft.refund_amount,
                status="SUBMITTED" if draft.risk_level != "high" else "PENDING_SUPERVISOR",
                trace_id=trace_id,
            )
            db.add(app_row)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                existing = db.scalar(
                    select(AfterSaleApplication).where(AfterSaleApplication.idempotency_key == key)
                )
                if existing:
                    return {"status": existing.status, "application_id": existing.application_id,
                            "draft_id": draft_id, "idempotent": True}
                raise
            draft.status = "SUBMITTED"
            draft.application_id = application_id
            draft.submitted_at = datetime.now()
            return {
                "status": app_row.status,
                "application_id": application_id,
                "draft_id": draft_id,
                "amount": draft.refund_amount,
                "risk_level": draft.risk_level,
                "idempotent": False,
            }

    result, first_time = idempotency.run_once(key, _do)
    return {**result, "idempotent": not first_time}


# ---------- 政策 ----------
def policy_qa(question: str, category: str | None = None) -> dict:
    chunks = policy_store.search_policy(question, category=category, top_k=4)
    if not grounding.is_grounded(chunks):
        return {"grounded": False, "answer": "", "citations": [], "chunks": chunks}
    return {
        "grounded": True,
        "answer": "",
        "citations": grounding.build_citations(chunks),
        "chunks": chunks,
    }


# ---------- 人工接管 ----------
def handoff_to_human(thread_id: str, user_id: str, intent: str, slots: dict,
                     tool_results: dict, fail_reason: str, risk_level: str, summary: str) -> dict:
    from app.db.models import HandoffTicket

    ticket_id = f"TK{uuid.uuid4().hex[:10].upper()}"
    with session_scope() as db:
        db.add(
            HandoffTicket(
                ticket_id=ticket_id,
                thread_id=thread_id,
                user_id=user_id,
                intent=intent,
                slots=slots or {},
                tool_results=tool_results or {},
                fail_reason=fail_reason[:200],
                risk_level=risk_level,
                summary=summary[:400],
                status="WAITING",
            )
        )
    return {"ticket_id": ticket_id, "status": "WAITING", "message": "已转人工，客服会带着上下文接手"}
