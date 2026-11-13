"""写操作安全：幂等、版本冲突、越权、未确认不执行。"""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.models import AfterSaleApplication, AfterSaleDraft
from app.db.session import session_scope
from app.tools.contracts import confirm_after_sale, create_after_sale_draft


def _draft(order_no="SO9990000001", reason="不想要了"):
    return create_after_sale_draft("u0001", order_no, reason)


def test_draft_created_not_submitted():
    d = _draft()
    assert d["draft_id"].startswith("DR")
    assert d["status"] == "AWAIT_CONFIRM"
    with session_scope() as db:
        row = db.scalar(select(AfterSaleDraft).where(AfterSaleDraft.draft_id == d["draft_id"]))
        assert row is not None and row.submitted_at is None


def test_confirm_is_idempotent():
    d = _draft()
    key = f"key-{uuid.uuid4().hex[:10]}"
    first = confirm_after_sale(d["draft_id"], "u0001", key, True, 5)
    second = confirm_after_sale(d["draft_id"], "u0001", key, True, 5)

    assert first["status"] == "SUBMITTED"
    assert second["application_id"] == first["application_id"]
    assert second["idempotent"] is True

    with session_scope() as db:
        rows = db.scalars(
            select(AfterSaleApplication).where(AfterSaleApplication.draft_id == d["draft_id"])
        ).all()
        assert len(rows) == 1, "重复提交只能产生一条申请"


def test_confirm_version_conflict():
    d = _draft()
    res = confirm_after_sale(d["draft_id"], "u0001", "key-conflict-01", True, 99)
    assert res["status"] == "CONFLICT"
    assert "version" in res["reason"]


def test_confirm_requires_user_confirmation():
    d = _draft()
    res = confirm_after_sale(d["draft_id"], "u0001", "key-noconfirm", False, 5)
    assert res["status"] == "REJECTED"


def test_confirm_denied_for_non_owner():
    d = _draft()
    try:
        confirm_after_sale(d["draft_id"], "u0002", "key-other-user", True, 5)
    except Exception as exc:  # OwnershipError
        assert "NOT_ACCESSIBLE" in str(exc)
    else:
        raise AssertionError("非归属用户不该提交成功")


def test_ineligible_order_rejected_at_draft_stage():
    d = _draft(order_no="SO9990000002", reason="不想要了")  # 已超 7 天
    assert d["status"] == "REJECTED"
    assert d["evaluation"]["eligible"] is False
