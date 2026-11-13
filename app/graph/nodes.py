"""编排节点：概率能力（理解）与确定能力（鉴权/规则/金额）严格分层。"""
from __future__ import annotations

import logging
from datetime import datetime

from app.config import settings
from app.llm import client as llm_client
from app.llm import rule_fallback as rules
from app.llm.client import LLMError
from app.observability.telemetry import Tracer
from app.tools import gateway
from app.tools.contracts import handoff_to_human, policy_qa

logger = logging.getLogger(__name__)

TRACER: Tracer | None = None


def set_tracer(tracer: Tracer) -> None:
    global TRACER
    TRACER = tracer


def _tracer() -> Tracer:
    if TRACER is None:
        raise RuntimeError("tracer 未初始化")
    return TRACER


def _emit(state: dict, stage: str, label: str, **extra) -> list[dict]:
    events = list(state.get("events") or [])
    events.append(
        {
            "type": "status",
            "stage": stage,
            "label": label,
            "elapsed_ms": round((datetime.now() - datetime.now()).total_seconds() * 1000, 1),
            **extra,
        }
    )
    return events


def _ctx(state: dict) -> dict:
    return {
        "user_id": state["user_id"],
        "role": state["role"],
        "trace_id": _tracer().trace_id,
    }


# ---------- 1. 鉴权 ----------
def authenticate(state: dict) -> dict:
    with _tracer().span("authenticate"):
        pass
    return {
        "events": _emit(state, "authenticate", "已完成身份校验（user_id 由 Token 注入）"),
        "steps": state.get("steps", 0) + 1,
        "tool_results": {},
    }


# ---------- 2. 意图 ----------
def classify_intent(state: dict) -> dict:
    text = state["message"]
    intent, conf = None, 0.0
    with _tracer().span("classify_intent"):
        if settings.llm_enabled:
            try:
                data = llm_client.classify_intent_llm(text, state.get("history_summary", ""), _tracer())
                if data.get("intent"):
                    intent, conf = str(data["intent"]), float(data.get("confidence", 0.8))
            except LLMError as exc:
                logger.warning("LLM 意图识别失败，降级规则：%s", exc)
        else:
            intent, conf = rules.classify_intent(text)

    return {
        "intent": intent or "unknown",
        "confidence": conf,
        "events": _emit(state, "classify_intent", f"识别意图：{intent or 'unknown'}（置信度 {conf:.2f}）"),
        "steps": state.get("steps", 0) + 1,
    }


# ---------- 3. 槽位 ----------
def extract_slots(state: dict) -> dict:
    text = state["message"]
    intent = state.get("intent", "unknown")
    slots: dict = {}
    with _tracer().span("extract_slots"):
        if settings.llm_enabled:
            try:
                slots = llm_client.extract_slots_llm(text, intent, _tracer())
            except LLMError as exc:
                logger.warning("LLM 槽位抽取失败，降级规则：%s", exc)
        if not slots:
            slots = rules.extract_slots(text)

    missing = rules.missing_slots(intent, slots)
    return {
        "slots": slots,
        "missing": missing,
        "events": _emit(
            state, "extract_slots",
            f"抽取槽位 {list(slots.keys()) or '无'}" + (f"，缺 {missing}" if missing else ""),
        ),
        "steps": state.get("steps", 0) + 1,
    }


# ---------- 4. 澄清 ----------
def clarify(state: dict) -> dict:
    missing = state.get("missing") or []
    key = missing[0] if missing else "category"
    text = rules.CLARIFY_TEMPLATES.get(key, "请补充更多信息，我才能继续帮你处理。")
    round_no = state.get("clarify_round", 0) + 1
    return {
        "response": text,
        "clarify_round": round_no,
        "events": _emit(state, "clarify", f"信息不足，发起第 {round_no} 轮澄清"),
        "steps": state.get("steps", 0) + 1,
    }


# ---------- 5. 导购检索 ----------
def retrieve_products(state: dict) -> dict:
    slots = state.get("slots", {})
    query = rules.rewrite_query(state["message"], slots)
    args = {
        "query": query,
        "category": slots.get("category"),
        "price_max": slots.get("price_max"),
        "top_k": settings.final_top_k,
    }
    with _tracer().span("retrieve_products"):
        res = gateway.call("search_products", args, _ctx(state), _tracer())
    if not res["ok"]:
        return {
            "error": res["code"],
            "needs_handoff": True,
            "handoff_reason": f"检索失败：{res.get('error')}",
            "events": _emit(state, "retrieve_products", "检索失败，准备转人工"),
            "steps": state.get("steps", 0) + 1,
        }
    data = res["data"]
    return {
        "candidates": data["cards"],
        "events": _emit(
            state, "retrieve_products",
            f"硬过滤后 {data['meta'].get('allowed')} 件，BM25+向量召回后融合精排，取 {len(data['cards'])} 个候选",
            meta=data["meta"],
        ),
        "steps": state.get("steps", 0) + 1,
    }


# ---------- 6. 实时补充 ----------
def live_enrich(state: dict) -> dict:
    candidates = state.get("candidates") or []
    if not candidates:
        return {
            "offers": {},
            "events": _emit(state, "live_enrich", "无候选，跳过实时查询"),
            "steps": state.get("steps", 0) + 1,
        }
    args = {"sku_ids": [c["sku_id"] for c in candidates]}
    with _tracer().span("live_enrich"):
        res = gateway.call("get_live_offer", args, _ctx(state), _tracer())
    if not res["ok"]:
        # 库存/价格不可用：不承诺有货，且禁止推进下单
        return {
            "offers": {},
            "error": res["code"],
            "events": _emit(state, "live_enrich", "实时库存不可用，回答中将不承诺库存与价格"),
            "steps": state.get("steps", 0) + 1,
        }
    offers = res["data"]["offers"]
    for c in candidates:
        o = offers.get(c["sku_id"])
        if o:
            c["price"] = o["price"]
            c["available_qty"] = o["available_qty"]
            c["promo"] = o.get("promo")
    return {
        "candidates": candidates,
        "offers": offers,
        "events": _emit(state, "live_enrich", f"已补充 {len(offers)} 件商品的实时价格与库存"),
        "steps": state.get("steps", 0) + 1,
    }


def compose_products(state: dict) -> dict:
    candidates = state.get("candidates") or []
    slots = state.get("slots", {})
    if not candidates:
        response = (
            "没有找到同时满足预算与库存条件的商品。可以放松预算、换个品类，"
            "或者告诉我更看重的点（比如降噪、轻便），我再筛一次。"
        )
    else:
        response = rules.template_product_answer(candidates, slots)
        if settings.llm_enabled:
            try:
                facts = "\n".join(
                    f"{c['title']}｜{c['price']}元｜库存{c['available_qty']}｜{c['review']}" for c in candidates
                )
                response = llm_client.chat(
                    [
                        {"role": "system", "content": "你是导购助手。只能基于给定候选商品作答，不得编造商品、价格或库存。给 3 个候选，说明差异与推荐理由，120 字内。"},
                        {"role": "user", "content": f"用户需求：{state['message']}\n候选商品：\n{facts}"},
                    ],
                    temperature=0.3,
                    tracer=_tracer(),
                )
            except LLMError:
                pass
    return {
        "response": response,
        "cards": [
            {k: c.get(k) for k in ("sku_id", "title", "brand", "price", "available_qty", "rating", "sales_30d", "explain", "review")}
            for c in candidates
        ],
        "events": _emit(state, "compose", "已生成导购回答与商品卡片"),
        "steps": state.get("steps", 0) + 1,
    }


# ---------- 7. 订单 ----------
def query_order(state: dict) -> dict:
    slots = state.get("slots", {})
    order_no = slots.get("order_no")
    ctx = _ctx(state)
    with _tracer().span("query_order"):
        o = gateway.call("get_order", {"order_no": order_no}, ctx, _tracer())
        logistics = gateway.call("get_logistics", {"order_no": order_no}, ctx, _tracer()) if o["ok"] else None

    if not o["ok"]:
        response = (
            "这个订单号我这边无法查询到可访问的订单。请核对订单号（SO 开头 + 10 位数字）后重试；"
            "如果确认无误，我可以直接转人工帮你核实。"
        )
        return {
            "response": response,
            "needs_handoff": o["code"] == "DENIED",
            "handoff_reason": "订单归属校验未通过",
            "risk_level": "medium",
            "events": _emit(state, "query_order", "订单查询未通过归属校验"),
            "steps": state.get("steps", 0) + 1,
        }
    order = o["data"]
    logi = logistics["data"] if logistics and logistics["ok"] else None
    status_map = {
        "PAID": "待发货", "SHIPPED": "运输中", "SIGNED": "已签收",
        "COMPLETED": "已完成", "CANCELLED": "已取消",
    }
    lines = [
        f"订单 {order['order_no']} 当前状态：**{status_map.get(order['status'], order['status'])}**",
        f"实付金额：{order['paid_amount']:.2f} 元；下单时间：{order['created_at']}",
    ]
    if order.get("signed_at"):
        lines.append(f"签收时间：{order['signed_at']}")
    if logi:
        lines.append(f"物流进度：{' → '.join(logi['steps'])}" + (f"；预计送达 {logi['eta']}" if logi.get("eta") else ""))
    lines.append("商品：" + "；".join(f"{i['title']} ×{i['qty']}" for i in order["items"]))
    return {
        "order": order,
        "logistics": logi,
        "response": "\n".join(lines),
        "cards": [],
        "events": _emit(state, "query_order", "订单与物流查询完成，字段已脱敏"),
        "steps": state.get("steps", 0) + 1,
    }


# ---------- 8. 售后 ----------
def evaluate_after_sale(state: dict) -> dict:
    slots = state.get("slots", {})
    order_no = slots.get("order_no")
    reason = slots.get("reason") or state["message"]
    with _tracer().span("evaluate_after_sale"):
        res = gateway.call(
            "evaluate_after_sale", {"order_no": order_no, "reason": reason}, _ctx(state), _tracer()
        )
    if not res["ok"]:
        return {
            "response": "订单信息无法核实，无法判断售后资格。已为你转人工，避免误判。",
            "needs_handoff": True,
            "handoff_reason": res.get("error", "售后规则判断失败"),
            "risk_level": "medium",
            "events": _emit(state, "evaluate_after_sale", "规则判断失败，转人工"),
            "steps": state.get("steps", 0) + 1,
        }
    ev = res["data"]
    return {
        "evaluation": ev,
        "risk_level": ev.get("risk_level", "low"),
        "events": _emit(
            state, "evaluate_after_sale",
            f"规则引擎判定：{'符合' if ev['eligible'] else '不符合'}（{ev.get('scene_label')}，规则 {ev.get('rule_version')}）",
        ),
        "steps": state.get("steps", 0) + 1,
    }


def prepare_draft(state: dict) -> dict:
    ev = state.get("evaluation") or {}
    slots = state.get("slots", {})
    if not ev.get("eligible"):
        bullets = "\n".join(f"- {r}" for r in ev.get("reasons", []))
        response = (
            f"按当前规则（{ev.get('rule_version')}，{ev.get('scene_label')}）这份申请**不符合直接受理条件**：\n"
            f"{bullets}\n\n"
            "你可以补充证据后重新提交，或让我转人工做例外复核。金额与资格以规则结果为准，我不代为裁决。"
        )
        needs_handoff = ev.get("risk_level") == "high"
        return {
            "response": response,
            "pending_action": None,
            "needs_handoff": needs_handoff,
            "handoff_reason": "规则判定不符合，用户可申请例外复核",
            "events": _emit(state, "prepare_draft", "不符合条件，已给出原因与后续路径"),
            "steps": state.get("steps", 0) + 1,
        }

    with _tracer().span("prepare_draft"):
        res = gateway.call(
            "create_after_sale_draft",
            {"order_no": slots.get("order_no"), "reason": slots.get("reason") or state["message"],
             "scene": slots.get("scene")},
            _ctx(state), _tracer(),
        )
    if not res["ok"]:
        return {
            "response": "创建申请草稿失败，已记录问题并转人工处理。",
            "needs_handoff": True,
            "handoff_reason": res.get("error", "草稿创建失败"),
            "events": _emit(state, "prepare_draft", "草稿创建失败，转人工"),
            "steps": state.get("steps", 0) + 1,
        }
    draft = res["data"]
    bullets = "\n".join(f"- {r}" for r in ev.get("reasons", []))
    response = (
        f"已生成售后申请**草稿**（未提交）：\n"
        f"- 订单：{slots.get('order_no')}\n"
        f"- 场景：{ev.get('scene_label')}\n"
        f"- 拟退款金额：{ev.get('refund_amount', 0):.2f} 元（由规则引擎计算）\n"
        f"- 依据：{ev.get('rule_condition')}（{ev.get('rule_version')}）\n"
        f"- 风险等级：{ev.get('risk_level')}\n"
        f"{bullets}\n\n"
        "**提交前需要你确认**：确认后将生成正式申请（重复点击不会重复提交）。"
    )
    return {
        "draft": draft,
        "pending_action": {
            "type": "confirm_after_sale",
            "draft_id": draft["draft_id"],
            "order_no": slots.get("order_no"),
            "amount": ev.get("refund_amount", 0.0),
            "risk_level": ev.get("risk_level", "low"),
            "rule_version": ev.get("rule_version"),
            "expected_order_version": state.get("order", {}).get("version"),
        },
        "response": response,
        "events": _emit(state, "prepare_draft", "已生成售后草稿，等待用户确认"),
        "steps": state.get("steps", 0) + 1,
    }


# ---------- 9. 政策 ----------
def policy_rag(state: dict) -> dict:
    slots = state.get("slots", {})
    category = slots.get("category")
    with _tracer().span("policy_rag"):
        res = gateway.call(
            "policy_qa", {"question": state["message"], "category": category}, _ctx(state), _tracer()
        )
    if not res["ok"]:
        return {
            "response": "政策检索暂时不可用，已为你转人工核实，避免给出过期信息。",
            "needs_handoff": True,
            "handoff_reason": res.get("error", "政策检索失败"),
            "events": _emit(state, "policy_rag", "检索失败，转人工"),
            "steps": state.get("steps", 0) + 1,
        }
    data = res["data"]
    if not data["grounded"]:
        from app.rag.grounding import refuse_message

        return {
            "response": refuse_message(),
            "citations": [],
            "needs_handoff": True,
            "handoff_reason": "无充分证据",
            "events": _emit(state, "policy_rag", "证据不足，执行拒答"),
            "steps": state.get("steps", 0) + 1,
        }

    answer = ""
    if settings.llm_enabled:
        try:
            answer = llm_client.grounded_answer(state["message"], data["chunks"][:3], _tracer())
        except LLMError:
            answer = ""
    if not answer:
        answer = rules.template_policy_answer(state["message"], data["chunks"])
    return {
        "response": answer,
        "citations": data["citations"],
        "events": _emit(
            state, "policy_rag", f"命中 {len(data['citations'])} 条政策条款，回答已附带版本与生效日期"
        ),
        "steps": state.get("steps", 0) + 1,
    }


# ---------- 10. 小聊 / 兜底 / 接管 ----------
def smalltalk(state: dict) -> dict:
    return {
        "response": "你好，我是商城的智能服务助手，可以帮你选商品、查订单物流、判断售后资格，或解释运费发票等政策。你想先处理哪一件？",
        "events": _emit(state, "smalltalk", "问候语应答"),
        "steps": state.get("steps", 0) + 1,
    }


def refuse_unsafe(state: dict) -> dict:
    _tracer().record("unsafe_request_blocked", message=state["message"][:80])
    return {
        "response": (
            "这个请求涉及越权或绕过规则，我不能执行。"
            "如果你需要查订单、申请售后或了解政策，我可以按正常流程帮你处理；"
            "涉及他人订单或例外审批的，需要人工客服核实身份后处理。"
        ),
        "risk_level": "high",
        "needs_handoff": False,
        "events": _emit(state, "guardrail", "检测到越权/注入意图，已拒绝"),
        "steps": state.get("steps", 0) + 1,
    }


def handoff(state: dict) -> dict:
    slots = state.get("slots", {})
    reason = state.get("handoff_reason") or "无法自动处理"
    summary = state.get("response") or state.get("message", "")
    with _tracer().span("handoff"):
        res = gateway.call(
            "handoff_to_human",
            {
                "thread_id": state.get("thread_id", "-"),
                "intent": state.get("intent", "unknown"),
                "slots": slots,
                "tool_results": state.get("tool_results", {}),
                "fail_reason": reason,
                "risk_level": state.get("risk_level", "low"),
                "summary": summary[:400],
            },
            _ctx(state), _tracer(),
        )
    ticket = res["data"] if res["ok"] else {"ticket_id": "-", "status": "FAILED"}
    base = state.get("response") or ""
    prefix = base + "\n\n" if base else ""
    return {
        "handoff": ticket,
        "response": prefix + f"已转人工（工单 {ticket.get('ticket_id')}），客服会带着本次会话的槽位、工具结果和失败原因接手，你不用重复描述。",
        "events": _emit(state, "handoff", "接管包已落库，等待客服接入"),
        "steps": state.get("steps", 0) + 1,
    }


def finalize(state: dict) -> dict:
    return {"events": _emit(state, "finalize", "响应组装完成")}
