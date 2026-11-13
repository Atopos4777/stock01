"""JWT 鉴权：user_id / role 只从 Token 注入，绝不接受请求体传入。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from fastapi import Header, HTTPException, status

from app.config import settings

Role = Literal["consumer", "agent", "supervisor", "ops"]


def create_token(user_id: str, role: Role = "consumer", tenant_id: str = "t_demo") -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 已过期")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 非法")


def get_identity(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI 依赖：从 Authorization: Bearer <jwt> 解析身份。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少 Bearer Token")
    claims = decode_token(authorization.split(" ", 1)[1].strip())
    return {
        "user_id": claims["sub"],
        "role": claims.get("role", "consumer"),
        "tenant_id": claims.get("tenant_id", "t_demo"),
    }


# 角色 → 允许调用的工具白名单（服务端决定，模型无权变更）
TOOL_WHITELIST: dict[str, set[str]] = {
    "consumer": {
        "search_products", "get_live_offer", "get_order", "get_logistics",
        "evaluate_after_sale", "create_after_sale_draft", "confirm_after_sale",
        "policy_qa", "handoff_to_human",
    },
    "agent": {
        "search_products", "get_live_offer", "get_order", "get_logistics",
        "evaluate_after_sale", "create_after_sale_draft", "confirm_after_sale",
        "policy_qa", "handoff_to_human",
    },
    "supervisor": {
        "search_products", "get_live_offer", "get_order", "get_logistics",
        "evaluate_after_sale", "create_after_sale_draft", "confirm_after_sale",
        "policy_qa", "handoff_to_human", "approve_after_sale",
    },
    "ops": {"search_products", "policy_qa", "evaluate_after_sale"},
}


def require_tool(role: str, tool_name: str) -> None:
    if tool_name not in TOOL_WHITELIST.get(role, set()):
        raise PermissionError(f"role={role} 无权调用工具 {tool_name}")
