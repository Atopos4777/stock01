"""trace / 审计 / 指标：每个请求一个 trace_id，串起节点、工具、耗时、token。"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings

TRACE_DIR = settings.data_dir / "traces"
TRACE_DIR.mkdir(parents=True, exist_ok=True)


def new_trace_id() -> str:
    return f"tr-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def new_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:12]}"


class Tracer:
    """一次请求的轻量 trace：节点级耗时 + 事件 + token 统计。"""

    def __init__(self, trace_id: str | None = None, user_id: str = "-") -> None:
        self.trace_id = trace_id or new_trace_id()
        self.user_id = user_id
        self.events: list[dict[str, Any]] = []
        self.t0 = time.perf_counter()
        self.tokens_in = 0
        self.tokens_out = 0

    @contextmanager
    def span(self, name: str, **fields: Any):
        st = time.perf_counter()
        err: str | None = None
        try:
            yield
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self.record(
                name,
                duration_ms=round((time.perf_counter() - st) * 1000, 2),
                error=err,
                **fields,
            )

    def record(self, event: str, **fields: Any) -> None:
        self.events.append(
            {
                "event": event,
                "ts": datetime.now().isoformat(timespec="milliseconds"),
                "elapsed_ms": round((time.perf_counter() - self.t0) * 1000, 2),
                **fields,
            }
        )

    def add_tokens(self, tokens_in: int = 0, tokens_out: int = 0) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out

    def summary(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "total_ms": round((time.perf_counter() - self.t0) * 1000, 2),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "events": len(self.events),
        }

    def flush(self) -> None:
        path = TRACE_DIR / f"{self.trace_id}.json"
        try:
            path.write_text(
                json.dumps({"summary": self.summary(), "events": self.events}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass


class Metrics:
    """进程内指标聚合，供 /api/metrics 与压测报告使用。"""

    def __init__(self) -> None:
        self.latencies: list[float] = []
        self.errors = 0
        self.count = 0
        self.token_in = 0
        self.token_out = 0
        self.tool_calls = 0
        self.tool_errors = 0

    def observe(self, ms: float, tokens_in: int = 0, tokens_out: int = 0, ok: bool = True) -> None:
        self.count += 1
        self.latencies.append(ms)
        self.token_in += tokens_in
        self.token_out += tokens_out
        if not ok:
            self.errors += 1

    @staticmethod
    def _pct(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        idx = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
        return round(s[idx], 2)

    def snapshot(self) -> dict[str, Any]:
        return {
            "requests": self.count,
            "errors": self.errors,
            "error_rate": round(self.errors / self.count, 4) if self.count else 0.0,
            "p50_ms": self._pct(self.latencies, 50),
            "p95_ms": self._pct(self.latencies, 95),
            "p99_ms": self._pct(self.latencies, 99),
            "tokens_in": self.token_in,
            "tokens_out": self.token_out,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
        }


metrics = Metrics()


def audit_tool(
    trace_id: str, user_id: str, tool: str, args: dict, ok: bool, latency_ms: float, result_code: str = "OK"
) -> None:
    """工具审计落盘：只记参数哈希摘要，不落敏感原值。"""
    import hashlib

    payload = {
        "trace_id": trace_id,
        "user_id": user_id,
        "tool": tool,
        "args_hash": hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16],
        "ok": ok,
        "code": result_code,
        "latency_ms": latency_ms,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    path = TRACE_DIR / "tool_audits.jsonl"
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass
