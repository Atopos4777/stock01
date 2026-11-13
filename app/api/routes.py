"""HTTP 接口：chat(SSE) / confirm / health / metrics / token。"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.core.cache import cache
from app.core.security import create_token, get_identity
from app.db.models import ConversationTurn, Product
from app.db.session import session_scope
from app.graph import builder
from app.llm.client import health as llm_health
from app.observability.telemetry import Tracer, metrics
from app.rag import policy_store
from app.retrieval import embedder, index as product_index
from app.tools import gateway

router = APIRouter(prefix="/api")

RATE_LIMIT_PER_MIN = 30


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    thread_id: str | None = Field(default=None, max_length=48)


class ConfirmRequest(BaseModel):
    draft_id: str = Field(min_length=6, max_length=40)
    idempotency_key: str = Field(min_length=8, max_length=64)
    user_confirmed: bool = True
    expected_order_version: int | None = None


def _rate_limit(user_id: str) -> None:
    key = f"rl:{user_id}:{datetime.now().strftime('%Y%m%d%H%M')}"
    hits = cache.get(key) or 0
    if hits >= RATE_LIMIT_PER_MIN:
        raise HTTPException(429, "请求过于频繁，请稍后重试")
    cache.set(key, hits + 1, ttl=70)


def _history(user_id: str, thread_id: str) -> str:
    with session_scope() as db:
        rows = db.scalars(
            select(ConversationTurn)
            .where(ConversationTurn.thread_id == thread_id, ConversationTurn.user_id == user_id)
            .order_by(ConversationTurn.id.desc())
            .limit(4)
        ).all()
    if not rows:
        return ""
    parts = [f"{r.role}: {r.content[:80]}" for r in reversed(rows)]
    return " | ".join(parts)


def _persist_turn(user_id: str, thread_id: str, role: str, content: str, intent: str = "") -> None:
    with session_scope() as db:
        db.add(
            ConversationTurn(
                thread_id=thread_id, user_id=user_id, role=role, content=content[:500], intent=intent
            )
        )


@router.get("/token")
def issue_token(
    user_id: str = Query(default="u0001", min_length=3, max_length=32),
    role: str = Query(default="consumer", pattern=r"^(consumer|agent|supervisor|ops)$"),
):
    """Demo 用签发接口：生产环境应由统一登录体系签发。"""
    return {"token": create_token(user_id, role), "user_id": user_id, "role": role}


@router.post("/chat")
async def chat(body: ChatRequest, request: Request, identity: dict = Depends(get_identity)):
    _rate_limit(identity["user_id"])
    thread_id = body.thread_id or f"th-{identity['user_id']}-{uuid.uuid4().hex[:8]}"
    tracer = Tracer(user_id=identity["user_id"])
    history = _history(identity["user_id"], thread_id)
    _persist_turn(identity["user_id"], thread_id, "user", body.message)

    t0 = time.perf_counter()
    first_token_ms: dict[str, float] = {}

    async def event_stream():
        yield {
            "event": "status",
            "data": json.dumps(
                {"stage": "connect", "label": "已建立连接，开始处理", "thread_id": thread_id},
                ensure_ascii=False,
            ),
        }
        try:
            final, tr = await asyncio.to_thread(
                builder.run, body.message, identity, thread_id, history, tracer
            )
        except Exception as exc:  # noqa: BLE001
            metrics.observe((time.perf_counter() - t0) * 1000, ok=False)
            yield {
                "event": "error",
                "data": json.dumps({"message": f"处理失败：{exc}"}, ensure_ascii=False),
            }
            return

        for ev in final.get("events", []):
            yield {"event": "status", "data": json.dumps(ev, ensure_ascii=False)}

        answer = final.get("response", "") or "（无输出）"
        first_token_ms["v"] = (time.perf_counter() - t0) * 1000
        chunk = 14
        for i in range(0, len(answer), chunk):
            if await request.is_disconnected():
                break
            yield {"event": "token", "data": json.dumps({"text": answer[i : i + chunk]}, ensure_ascii=False)}
            await asyncio.sleep(0.012)

        payload = {
            "thread_id": thread_id,
            "intent": final.get("intent"),
            "slots": final.get("slots", {}),
            "cards": final.get("cards", []),
            "citations": final.get("citations", []),
            "pending_action": final.get("pending_action"),
            "handoff": final.get("handoff"),
            "evaluation": final.get("evaluation"),
            "order": final.get("order"),
            "risk_level": final.get("risk_level"),
            "trace_id": tr.trace_id,
            "usage": tr.summary(),
        }
        yield {"event": "result", "data": json.dumps(payload, ensure_ascii=False, default=str)}

        total_ms = (time.perf_counter() - t0) * 1000
        metrics.observe(total_ms, tr.tokens_in, tr.tokens_out, ok=True)
        tr.record("response_sent", total_ms=round(total_ms, 2), ttft_ms=round(first_token_ms["v"], 2))
        tr.flush()
        _persist_turn(identity["user_id"], thread_id, "assistant", answer, final.get("intent", ""))
        yield {
            "event": "done",
            "data": json.dumps(
                {
                    "total_ms": round(total_ms, 2),
                    "ttft_ms": round(first_token_ms["v"], 2),
                    "tokens_in": tr.tokens_in,
                    "tokens_out": tr.tokens_out,
                },
                ensure_ascii=False,
            ),
        }

    async def _format():
        async for item in event_stream():
            yield f"event: {item['event']}\ndata: {item['data']}\n\n"

    return StreamingResponse(
        _format(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/confirm")
def confirm(body: ConfirmRequest, identity: dict = Depends(get_identity)):
    tracer = Tracer(user_id=identity["user_id"])
    res = gateway.call(
        "confirm_after_sale",
        {
            "draft_id": body.draft_id,
            "idempotency_key": body.idempotency_key,
            "user_confirmed": body.user_confirmed,
            "expected_order_version": body.expected_order_version,
        },
        {"user_id": identity["user_id"], "role": identity["role"], "trace_id": tracer.trace_id},
        tracer,
    )
    tracer.flush()
    if not res["ok"]:
        return {"ok": False, "code": res["code"], "message": res.get("error", "提交失败")}
    return {"ok": True, "result": res["data"]}


@router.get("/orders")
def my_orders(identity: dict = Depends(get_identity)):
    from app.tools.contracts import list_orders

    return list_orders(identity["user_id"], limit=6)


@router.get("/health")
def health():
    with session_scope() as db:
        n_products = db.query(Product).count()
    return {
        "status": "ok",
        "app": settings.app_name,
        "llm": llm_health(),
        "embedding_mode": embedder.embedding_mode(),
        "product_index": {"ready": product_index.is_ready(), "rows": n_products},
        "policy_index": {"ready": policy_store.is_ready()},
        "graph_nodes": 15,
        "limits": {
            "max_clarify_rounds": settings.max_clarify_rounds,
            "max_graph_steps": settings.max_graph_steps,
            "high_value_threshold": settings.high_value_threshold,
        },
    }


@router.get("/metrics")
def get_metrics():
    return metrics.snapshot()
