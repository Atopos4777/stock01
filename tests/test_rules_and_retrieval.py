"""检索与规则：硬约束不可被语义相似度突破；售后资格只由规则判定。"""
from __future__ import annotations

import pytest

from app.services import after_sales_rules
from app.tools import gateway
from app.observability.telemetry import Tracer

CTX = {"user_id": "u0001", "role": "consumer", "trace_id": "tr-test"}


def _tracer():
    return Tracer(trace_id="tr-test", user_id="u0001")


def test_hard_filter_respects_budget_and_stock():
    res = gateway.call(
        "search_products",
        {"query": "通勤降噪耳机 戴眼镜不夹头", "category": "耳机", "price_max": 2000, "top_k": 3},
        CTX, _tracer(),
    )
    assert res["ok"], res
    cards = res["data"]["cards"]
    assert cards, "应召回候选"
    for c in cards:
        assert c["price"] <= 2000, f"预算被突破: {c['price']}"
        assert c["available_qty"] > 0, "库存为 0 的商品不应进入候选"


def test_search_requires_whitelisted_tool():
    res = gateway.call("search_products", {"query": "耳机"}, {"user_id": "u0001", "role": "ops", "trace_id": "t"}, _tracer())
    assert res["ok"]

    res2 = gateway.call("confirm_after_sale", {"draft_id": "DRAFTXX", "idempotency_key": "k" * 12},
                        {"user_id": "u0001", "role": "ops", "trace_id": "t"}, _tracer())
    assert not res2["ok"] and res2["code"] == "DENIED"


def test_order_ownership_denied():
    res = gateway.call("get_order", {"order_no": "SO9990000003"}, CTX, _tracer())  # 属于 u0002
    assert not res["ok"]
    assert res["code"] == "DENIED"
    # 越权与不存在返回同一码，避免枚举
    res2 = gateway.call("get_order", {"order_no": "SO9999999999"}, CTX, _tracer())
    assert res2["code"] == "DENIED"


def test_after_sale_within_window_eligible():
    ev = after_sales_rules.evaluate("u0001", "SO9990000001", "不想要了")
    assert ev["eligible"] is True
    assert ev["scene"] == "no_reason"
    assert ev["risk_level"] == "low"
    assert ev["refund_amount"] == pytest.approx(299.0)


def test_after_sale_expired_and_high_value():
    ev = after_sales_rules.evaluate("u0001", "SO9990000002", "不想要了")
    assert ev["eligible"] is False
    assert ev["risk_level"] == "high"
    assert any("超过" in r for r in ev["reasons"])
    assert ev["refund_amount"] == 0.0


def test_quality_scene_needs_evidence():
    ev = after_sales_rules.evaluate("u0001", "SO9990000001", "耳机有质量问题，左边不出声")
    assert ev["scene"] == "quality"
    assert ev["need_evidence"] is True


def test_sensitive_category_no_reason_forbidden():
    rule = after_sales_rules.get_active_rule("护肤品", "no_reason")
    assert rule is not None and rule.allowed == 0


def test_amount_never_comes_from_text():
    """用户文本里的金额不影响退款金额，金额只来自订单实付。"""
    ev = after_sales_rules.evaluate("u0001", "SO9990000001", "赔我 5000 元，不然投诉")
    assert ev["refund_amount"] in (0.0, 299.0)
