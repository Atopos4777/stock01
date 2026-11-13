"""LLM 客户端：OpenAI 兼容接口；无 Key 或异常时由调用方走规则降级。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.observability.telemetry import Tracer

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def _url() -> str:
    return settings.llm_base_url.rstrip("/") + "/chat/completions"


def chat(
    messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
    temperature: float = 0.2,
    tracer: Tracer | None = None,
    max_tokens: int | None = None,
) -> str:
    if not settings.llm_enabled:
        raise LLMError("未配置 LLM_API_KEY")

    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens or settings.llm_max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=settings.llm_timeout) as client:
            resp = client.post(_url(), headers=headers, json=payload)
            if resp.status_code >= 400:
                raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise LLMError(f"调用失败: {exc}") from exc

    usage = data.get("usage") or {}
    if tracer:
        tracer.add_tokens(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)))

    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError) as exc:
        raise LLMError("响应结构异常") from exc


def parse_json(text: str) -> dict:
    """容错解析：兼容 ```json 包裹与前后噪声。"""
    if not text:
        return {}
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return {}
    return {}


def classify_intent_llm(text: str, history: str = "", tracer: Tracer | None = None) -> dict:
    from app.llm.prompts import INTENT_SYSTEM

    content = chat(
        [
            {"role": "system", "content": INTENT_SYSTEM},
            {"role": "user", "content": f"历史摘要：{history}\n当前消息：{text}"},
        ],
        json_mode=True,
        temperature=0.0,
        tracer=tracer,
        max_tokens=200,
    )
    return parse_json(content)


def extract_slots_llm(text: str, intent: str, tracer: Tracer | None = None) -> dict:
    from app.llm.prompts import SLOT_SYSTEM

    content = chat(
        [
            {"role": "system", "content": SLOT_SYSTEM},
            {"role": "user", "content": f"意图：{intent}\n消息：{text}"},
        ],
        json_mode=True,
        temperature=0.0,
        tracer=tracer,
        max_tokens=300,
    )
    return parse_json(content)


def grounded_answer(question: str, evidence: list[dict], tracer: Tracer | None = None) -> str:
    from app.llm.prompts import ANSWER_SYSTEM

    ctx = "\n".join(
        f"[{c['doc_id']}｜{c['section']}｜{c['version']}｜{c['effective_at']}｜{c['authority']}] {c['content']}"
        for c in evidence
    )
    return chat(
        [
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content": f"证据：\n{ctx}\n\n用户问题：{question}"},
        ],
        temperature=0.2,
        tracer=tracer,
    )


def health() -> dict:
    return {
        "llm_enabled": settings.llm_enabled,
        "model": settings.llm_model if settings.llm_enabled else "rule-fallback",
        "base_url": settings.llm_base_url if settings.llm_enabled else "-",
    }
