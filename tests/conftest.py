"""pytest 配置：测试使用临时数据目录与哈希向量，保证快且可复现。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="cc-test-"))
os.environ.setdefault("EMBEDDING_MODE", "hash")
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("JWT_SECRET", "test-secret")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.core.cache import cache, idempotency  # noqa: E402
from app.db.seed import seed_all  # noqa: E402
from app.rag import policy_store  # noqa: E402
from app.retrieval import embedder, index as product_index  # noqa: E402
from app.services.product_service import list_all_products  # noqa: E402


TEST_ORDERS = {
    "fresh": "SO9990000001",   # u0001，签收 2 天，299 元
    "expired": "SO9990000002", # u0001，签收 20 天，1999 元（超时 + 高价值）
    "other": "SO9990000003",   # u0002 的订单，用于越权用例
}


@pytest.fixture(scope="session", autouse=True)
def _prepare(tmp_path_factory):
    seed_all(reset=True)
    _create_test_orders()
    product_index.build_index(list_all_products(), force=True)
    policy_store.build_policy_index(force=True)
    yield


def _create_test_orders() -> None:
    from datetime import datetime, timedelta

    from app.db.models import Order, OrderItem
    from app.db.session import session_scope

    now = datetime.now()
    spec = [
        (TEST_ORDERS["fresh"], "u0001", "SIGNED", 299.0, now - timedelta(days=2), 5),
        (TEST_ORDERS["expired"], "u0001", "SIGNED", 1999.0, now - timedelta(days=20), 3),
        (TEST_ORDERS["other"], "u0002", "SIGNED", 100.0, now - timedelta(days=1), 2),
    ]
    with session_scope() as db:
        if db.query(Order).filter(Order.order_no == TEST_ORDERS["fresh"]).first():
            return
        for order_no, uid, status, amount, signed, version in spec:
            db.add(
                Order(
                    order_no=order_no, user_id=uid, status=status, paid_amount=amount,
                    created_at=signed - timedelta(days=2), signed_at=signed,
                    logistics_no="LG999999999", version=version,
                )
            )
            db.flush()
            db.add(
                OrderItem(
                    order_no=order_no, sku_id="SKU00001", title="声岛 头戴式耳机 A1",
                    category="耳机", qty=1, unit_price=amount,
                )
            )


@pytest.fixture(autouse=True)
def _clean_state():
    cache.clear()
    idempotency.clear()
    yield
    cache.clear()
    idempotency.clear()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def user_token():
    from app.core.security import create_token

    return create_token("u0001", "consumer")
