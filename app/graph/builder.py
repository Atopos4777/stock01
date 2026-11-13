"""状态图装配：单 Orchestrator + 确定性子流程，所有分支显式可达。"""
from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.graph import nodes
from app.graph.state import CommerceState
from app.observability.telemetry import Tracer, new_request_id

logger = logging.getLogger(__name__)

_compiled = None


def _route_after_slots(state: CommerceState) -> str:
    intent = state.get("intent", "unknown")
    missing = state.get("missing") or []
    rounds = state.get("clarify_round", 0)
    needs_clarify = intent in {"product_advice", "order_query", "after_sales"} and missing
    if needs_clarify and rounds < settings.max_clarify_rounds:
        return "clarify"
    if needs_clarify and rounds >= settings.max_clarify_rounds:
        return "handoff"
    return {
        "product_advice": "retrieve_products",
        "order_query": "query_order",
        "after_sales": "evaluate_after_sale",
        "policy_qa": "policy_rag",
        "smalltalk": "smalltalk",
        "unsafe": "refuse_unsafe",
    }.get(intent, "handoff")


def _route_after_draft(state: CommerceState) -> str:
    if state.get("needs_handoff"):
        return "handoff"
    return "finalize"


def _route_after_enrich(state: CommerceState) -> str:
    if state.get("error") == "TOOL_ERROR":
        return "handoff"
    return "compose_products"


def build() -> "StateGraph":
    global _compiled
    if _compiled is not None:
        return _compiled

    g = StateGraph(CommerceState)
    g.add_node("authenticate", nodes.authenticate)
    g.add_node("classify_intent", nodes.classify_intent)
    g.add_node("extract_slots", nodes.extract_slots)
    g.add_node("clarify", nodes.clarify)
    g.add_node("retrieve_products", nodes.retrieve_products)
    g.add_node("live_enrich", nodes.live_enrich)
    g.add_node("compose_products", nodes.compose_products)
    g.add_node("query_order", nodes.query_order)
    g.add_node("evaluate_after_sale", nodes.evaluate_after_sale)
    g.add_node("prepare_draft", nodes.prepare_draft)
    g.add_node("policy_rag", nodes.policy_rag)
    g.add_node("smalltalk", nodes.smalltalk)
    g.add_node("refuse_unsafe", nodes.refuse_unsafe)
    g.add_node("escalate", nodes.handoff)
    g.add_node("finalize", nodes.finalize)

    g.add_edge(START, "authenticate")
    g.add_edge("authenticate", "classify_intent")
    g.add_edge("classify_intent", "extract_slots")
    g.add_conditional_edges(
        "extract_slots",
        _route_after_slots,
        {
            "clarify": "clarify",
            "retrieve_products": "retrieve_products",
            "query_order": "query_order",
            "evaluate_after_sale": "evaluate_after_sale",
            "policy_rag": "policy_rag",
            "smalltalk": "smalltalk",
            "refuse_unsafe": "refuse_unsafe",
            "handoff": "escalate",
        },
    )
    g.add_edge("retrieve_products", "live_enrich")
    g.add_conditional_edges(
        "live_enrich", _route_after_enrich, {"compose_products": "compose_products", "handoff": "escalate"}
    )
    g.add_edge("compose_products", "finalize")
    g.add_edge("query_order", "finalize")
    g.add_edge("evaluate_after_sale", "prepare_draft")
    g.add_conditional_edges("prepare_draft", _route_after_draft, {"handoff": "escalate", "finalize": "finalize"})
    g.add_edge("policy_rag", "finalize")
    g.add_edge("smalltalk", "finalize")
    g.add_edge("refuse_unsafe", "finalize")
    g.add_edge("clarify", "finalize")
    g.add_edge("escalate", "finalize")
    g.add_edge("finalize", END)

    _compiled = g.compile()
    logger.info("LangGraph 状态图编译完成：%d 个节点", 15)
    return _compiled


def run(message: str, identity: dict, thread_id: str, history: str = "",
        tracer: Tracer | None = None) -> tuple[CommerceState, Tracer]:
    tracer = tracer or Tracer(user_id=identity["user_id"])
    nodes.set_tracer(tracer)
    graph = build()
    init: CommerceState = {
        "request_id": new_request_id(),
        "thread_id": thread_id,
        "user_id": identity["user_id"],
        "role": identity["role"],
        "tenant_id": identity.get("tenant_id", "t_demo"),
        "message": message,
        "history_summary": history,
        "clarify_round": 0,
        "steps": 0,
        "events": [],
        "tool_results": {},
        "needs_handoff": False,
        "pending_action": None,
        "citations": [],
        "cards": [],
        "candidates": [],
    }
    final = graph.invoke(init, config={"recursion_limit": settings.max_graph_steps * 3})
    return final, tracer
