"""接口层：鉴权、SSE、确认接口、健康检查。"""
from __future__ import annotations

import json


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["product_index"]["ready"] is True
    assert data["embedding_mode"] in {"hash", "bge"}


def test_chat_requires_token(client):
    r = client.post("/api/chat", json={"message": "你好"})
    assert r.status_code == 401


def test_token_issue_and_chat_stream(client):
    tok = client.get("/api/token", params={"user_id": "u0001", "role": "consumer"}).json()["token"]
    with client.stream(
        "POST", "/api/chat", json={"message": "2000以内通勤降噪耳机"}, headers=_auth(tok)
    ) as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
        assert "status" in events and "result" in events and "done" in events


def test_confirm_endpoint_idempotent(client):
    tok = client.get("/api/token", params={"user_id": "u0001", "role": "consumer"}).json()["token"]
    chat = client.post(
        "/api/chat", json={"message": "我要退货，不想要了，订单 SO9990000001"}, headers=_auth(tok)
    )
    payload = None
    for block in chat.text.split("\n\n"):
        if "event: result" in block:
            for line in block.splitlines():
                if line.startswith("data:"):
                    payload = json.loads(line[5:].strip())
    assert payload and payload["pending_action"], "应返回待确认动作"

    body = {
        "draft_id": payload["pending_action"]["draft_id"],
        "idempotency_key": "apikey-abc-123456",
        "user_confirmed": True,
        "expected_order_version": 5,
    }
    first = client.post("/api/confirm", json=body, headers=_auth(tok)).json()
    second = client.post("/api/confirm", json=body, headers=_auth(tok)).json()
    assert first["ok"] and second["ok"]
    assert first["result"]["application_id"] == second["result"]["application_id"]
    assert second["result"]["idempotent"] is True


def test_confirm_denied_without_token(client):
    r = client.post("/api/confirm", json={"draft_id": "DRXXXXXX", "idempotency_key": "k" * 12})
    assert r.status_code == 401


def test_metrics_endpoint(client):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    assert "p95_ms" in r.json()
