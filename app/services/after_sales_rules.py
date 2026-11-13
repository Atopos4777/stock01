"""售后规则引擎：纯规则、可单测、版本化。LLM 不参与资格与金额裁决。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.db.models import AfterSaleRule, Order, OrderItem
from app.db.session import session_scope

SCENE_ALIAS = {
    "no_reason": "无理由退货",
    "quality": "质量问题",
    "wrong_item": "错发/漏发",
}


def _now() -> datetime:
    return datetime.now()


def resolve_scene(reason_text: str) -> str:
    t = (reason_text or "").lower()
    if any(k in t for k in ["质量", "坏", "故障", "破损", "开胶", "断", "瑕疵", "漏液", "过敏"]):
        return "quality"
    if any(k in t for k in ["错发", "发错", "漏发", "少发", "不是我买的", "错货"]):
        return "wrong_item"
    return "no_reason"


def get_active_rule(category: str, scene: str) -> AfterSaleRule | None:
    """精确品类规则优先，其次回落到 general。"""
    now = _now()
    with session_scope() as db:
        for cat in (category, "general"):
            row = db.scalars(
                select(AfterSaleRule).where(
                    AfterSaleRule.category == cat,
                    AfterSaleRule.scene == scene,
                    AfterSaleRule.effective_from <= now,
                ).order_by(AfterSaleRule.effective_from.desc())
            ).first()
            if row is not None:
                return row
    return None


def evaluate(user_id: str, order_no: str, reason_text: str) -> dict:
    """返回 {eligible, scene, rule_version, refund_amount, risk_level, reasons[], need_evidence}"""
    with session_scope() as db:
        order = db.scalar(select(Order).where(Order.order_no == order_no))
        # 归属校验：与工具层同一套语义，不泄露订单是否存在
        if order is None or order.user_id != user_id:
            # 故意延迟到工具层抛出统一错误；此处返回不可受理
            return {
                "eligible": False,
                "scene": "unknown",
                "rule_version": "N/A",
                "refund_amount": 0.0,
                "risk_level": "high",
                "need_evidence": False,
                "reasons": ["订单不可访问，请确认订单号后重试"],
                "code": "ORDER_NOT_ACCESSIBLE",
            }
        items = db.scalars(select(OrderItem).where(OrderItem.order_no == order_no)).all()
        main_item = max(items, key=lambda i: i.unit_price) if items else None
        category = main_item.category if main_item else "general"

    scene = resolve_scene(reason_text)
    rule = get_active_rule(category, scene)
    reasons: list[str] = []
    eligible = True

    if rule is None:
        return {
            "eligible": False, "scene": scene, "rule_version": "N/A",
            "refund_amount": 0.0, "risk_level": "medium", "need_evidence": False,
            "reasons": ["未找到适用的售后规则，转人工确认"], "code": "NO_ACTIVE_RULE",
        }

    if not rule.allowed:
        eligible = False
        reasons.append(f"{category or '该品类'}不支持{SCENE_ALIAS.get(scene, scene)}（{rule.condition}）")

    if scene == "no_reason":
        anchor = order.signed_at
        if anchor is None:
            eligible = False
            reasons.append("订单尚未签收，暂不能申请无理由退货；如需取消订单请另行走取消流程")
    elif scene == "quality":
        anchor = order.signed_at
        if anchor is None:
            eligible = False
            reasons.append("订单尚未签收，需签收后再提交质量问题举证")
    else:
        anchor = order.created_at

    if anchor is not None:
        days = (_now() - anchor).days
        if days > rule.window_days:
            eligible = False
            reasons.append(f"已超过 {rule.window_days} 天受理时限（当前 {days} 天），可转保修流程")

    need_evidence = bool(rule.need_evidence)
    if need_evidence:
        reasons.append("需提供图片或视频证据，证据不足将无法通过审核")

    refund_amount = round(float(order.paid_amount), 2)
    if scene == "quality" and eligible:
        reasons.append("质量问题判定成立时，往返运费由商家承担")

    risk = "low"
    if order.paid_amount >= settings.high_value_threshold:
        risk = "high"
        reasons.append(f"订单金额 {order.paid_amount:.2f} 元超过高价值阈值，需主管复核")
    elif need_evidence or order.status not in {"SIGNED", "COMPLETED"}:
        risk = "medium"

    return {
        "eligible": eligible and bool(rule.allowed),
        "scene": scene,
        "scene_label": SCENE_ALIAS.get(scene, scene),
        "rule_version": rule.version,
        "rule_condition": rule.condition,
        "window_days": rule.window_days,
        "refund_amount": refund_amount if eligible else 0.0,
        "risk_level": risk,
        "need_evidence": need_evidence,
        "reasons": reasons or ["符合当前售后规则，可创建申请草稿"],
        "code": "OK",
    }
