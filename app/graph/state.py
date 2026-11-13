"""会话状态：一次请求的完整上下文，节点只读写约定字段。"""
from __future__ import annotations

from typing import Any, TypedDict


class CommerceState(TypedDict, total=False):
    # 身份（只来自 Token）
    request_id: str
    thread_id: str
    user_id: str
    role: str
    tenant_id: str

    # 输入
    message: str
    history_summary: str

    # 理解
    intent: str
    confidence: float
    slots: dict[str, Any]
    missing: list[str]
    clarify_round: int

    # 业务产物
    candidates: list[dict]
    offers: dict[str, Any]
    order: dict[str, Any]
    logistics: dict[str, Any]
    evaluation: dict[str, Any]
    draft: dict[str, Any]
    citations: list[dict]
    risk_level: str

    # 输出
    response: str
    cards: list[dict]
    pending_action: dict[str, Any] | None
    needs_handoff: bool
    handoff: dict[str, Any] | None
    tool_results: dict[str, Any]
    error: str | None

    # 观测
    events: list[dict]
    steps: int
