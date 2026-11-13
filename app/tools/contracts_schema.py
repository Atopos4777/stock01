"""工具参数契约：Pydantic 严格校验，模型无法绕过限制。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SearchProductsArgs(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=20)
    price_max: float | None = Field(default=None, ge=0, le=100000)
    price_min: float | None = Field(default=None, ge=0, le=100000)
    top_k: int = Field(default=3, ge=1, le=5)


class GetLiveOfferArgs(BaseModel):
    sku_ids: list[str] = Field(min_length=1, max_length=5)

    @field_validator("sku_ids")
    @classmethod
    def _check_sku(cls, v: list[str]) -> list[str]:
        for s in v:
            if not s.startswith("SKU") or not s[3:].isdigit():
                raise ValueError("sku_id 格式非法")
        return v


class OrderNoArgs(BaseModel):
    order_no: str = Field(min_length=12, max_length=12, pattern=r"^SO\d{10}$")


class EvaluateAfterSaleArgs(BaseModel):
    order_no: str = Field(pattern=r"^SO\d{10}$")
    reason: str = Field(min_length=1, max_length=200)


class CreateDraftArgs(BaseModel):
    order_no: str = Field(pattern=r"^SO\d{10}$")
    reason: str = Field(min_length=1, max_length=200)
    scene: str | None = Field(default=None, pattern=r"^(no_reason|quality|wrong_item)$")


class ConfirmAfterSaleArgs(BaseModel):
    draft_id: str = Field(min_length=6, max_length=40)
    idempotency_key: str = Field(min_length=8, max_length=64)
    user_confirmed: bool = True
    expected_order_version: int | None = Field(default=None, ge=1, le=999)


class PolicyQAArgs(BaseModel):
    question: str = Field(min_length=2, max_length=200)
    category: str | None = Field(default=None, max_length=20)


class HandoffArgs(BaseModel):
    thread_id: str = Field(min_length=4, max_length=48)
    intent: str = Field(max_length=32)
    slots: dict = Field(default_factory=dict)
    tool_results: dict = Field(default_factory=dict)
    fail_reason: str = Field(default="", max_length=200)
    risk_level: str = Field(default="low", pattern=r"^(low|medium|high)$")
    summary: str = Field(default="", max_length=400)


TOOL_SPECS = {
    "search_products": (SearchProductsArgs, "按结构化条件 + 语义混合检索商品，返回候选卡片"),
    "get_live_offer": (GetLiveOfferArgs, "查询实时价格、库存与促销资格"),
    "get_order": (OrderNoArgs, "查询本人订单（服务端强制归属校验）"),
    "get_logistics": (OrderNoArgs, "查询本人订单物流节点"),
    "evaluate_after_sale": (EvaluateAfterSaleArgs, "规则引擎判断售后资格与金额"),
    "create_after_sale_draft": (CreateDraftArgs, "创建售后申请草稿（不产生实际变更）"),
    "confirm_after_sale": (ConfirmAfterSaleArgs, "确认并提交售后申请（幂等）"),
    "policy_qa": (PolicyQAArgs, "政策知识库检索与引用"),
    "handoff_to_human": (HandoffArgs, "转人工并落库接管包"),
}
