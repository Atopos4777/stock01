"""工具网关：白名单 → 校验 → 执行 → 超时/异常归一 → 审计。模型只能经由这里触达业务。"""
from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from app.core.security import require_tool
from app.observability.telemetry import Tracer, audit_tool, metrics
from app.tools.contracts_schema import TOOL_SPECS

TOOL_ERROR = "TOOL_ERROR"


class ToolDenied(PermissionError):
    pass


def _impl(tool: str):
    from app import tools  # noqa: F401  (确保包已加载)
    from app.tools import contracts

    return getattr(contracts, tool)


def call(tool: str, args: dict[str, Any], ctx: dict, tracer: Tracer) -> dict:
    """统一工具调用入口。ctx 至少含 user_id / role / trace_id。"""
    t0 = time.perf_counter()
    try:
        require_tool(ctx["role"], tool)
        spec = TOOL_SPECS.get(tool)
        if spec is None:
            raise ToolDenied(f"未知工具 {tool}")
        model = spec[0]
        try:
            validated = model(**args)
        except ValidationError as exc:
            raise ValueError(f"参数校验失败: {exc.errors()[0]['msg']}") from exc

        kwargs = validated.model_dump()
        fn = _impl(tool)
        # 身份只由服务端注入
        if tool in {"get_order", "get_logistics", "list_orders"}:
            kwargs["user_id"] = ctx["user_id"]
        elif tool == "evaluate_after_sale":
            kwargs["user_id"] = ctx["user_id"]
        elif tool == "create_after_sale_draft":
            kwargs["user_id"] = ctx["user_id"]
        elif tool == "confirm_after_sale":
            kwargs["user_id"] = ctx["user_id"]
        elif tool == "handoff_to_human":
            kwargs["user_id"] = ctx["user_id"]
        if tool == "confirm_after_sale":
            kwargs["trace_id"] = ctx["trace_id"]

        metrics.tool_calls += 1
        result = fn(**kwargs)
        latency = (time.perf_counter() - t0) * 1000
        tracer.record("tool_call", tool=tool, ok=True, latency_ms=round(latency, 2))
        audit_tool(ctx["trace_id"], ctx["user_id"], tool, args, True, latency, "OK")
        return {"ok": True, "tool": tool, "data": result}
    except PermissionError as exc:
        latency = (time.perf_counter() - t0) * 1000
        metrics.tool_errors += 1
        tracer.record("tool_call", tool=tool, ok=False, denied=True, reason=str(exc))
        audit_tool(ctx["trace_id"], ctx["user_id"], tool, args, False, latency, "DENIED")
        return {"ok": False, "tool": tool, "code": "DENIED", "error": str(exc)}
    except ValueError as exc:
        latency = (time.perf_counter() - t0) * 1000
        metrics.tool_errors += 1
        tracer.record("tool_call", tool=tool, ok=False, reason=str(exc))
        audit_tool(ctx["trace_id"], ctx["user_id"], tool, args, False, latency, "BAD_ARGS")
        return {"ok": False, "tool": tool, "code": "BAD_ARGS", "error": str(exc)}
    except TimeoutError as exc:
        latency = (time.perf_counter() - t0) * 1000
        metrics.tool_errors += 1
        tracer.record("tool_call", tool=tool, ok=False, reason="timeout")
        audit_tool(ctx["trace_id"], ctx["user_id"], tool, args, False, latency, "TIMEOUT")
        return {"ok": False, "tool": tool, "code": "TIMEOUT", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        latency = (time.perf_counter() - t0) * 1000
        metrics.tool_errors += 1
        code = getattr(exc, "args", ["TOOL_ERROR"])[0] if exc.args else TOOL_ERROR
        if code == "ORDER_NOT_ACCESSIBLE":
            tracer.record("tool_call", tool=tool, ok=False, denied=True, reason="ownership")
            audit_tool(ctx["trace_id"], ctx["user_id"], tool, args, False, latency, "DENIED")
            return {"ok": False, "tool": tool, "code": "DENIED", "error": "订单不可访问，请确认订单号后重试"}
        tracer.record("tool_call", tool=tool, ok=False, reason=str(exc))
        audit_tool(ctx["trace_id"], ctx["user_id"], tool, args, False, latency, TOOL_ERROR)
        return {"ok": False, "tool": tool, "code": TOOL_ERROR, "error": "工具执行失败，已记录"}
