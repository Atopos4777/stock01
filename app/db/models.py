"""数据模型：商品/库存/订单/售后规则/知识块/售后草稿/接管单。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    sku_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    spu_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40), index=True)
    sub_category: Mapped[str] = mapped_column(String(40), default="")
    brand: Mapped[str] = mapped_column(String(40), default="")
    price: Mapped[float] = mapped_column(Float, index=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(Text, default="")
    review_summary: Mapped[str] = mapped_column(Text, default="")
    sales_30d: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float] = mapped_column(Float, default=4.5)
    status: Mapped[str] = mapped_column(String(16), default="on_sale")  # on_sale / off_shelf
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    inventory: Mapped["Inventory"] = relationship(back_populates="product", uselist=False)


class Inventory(Base):
    __tablename__ = "inventory"

    sku_id: Mapped[str] = mapped_column(ForeignKey("products.sku_id"), primary_key=True)
    warehouse_id: Mapped[str] = mapped_column(String(16), primary_key=True, default="WH01")
    available_qty: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)

    product: Mapped[Product] = relationship(back_populates="inventory")


class Order(Base):
    __tablename__ = "orders"

    order_no: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)   # 归属校验依据
    status: Mapped[str] = mapped_column(String(24), default="PAID")
    paid_amount: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    logistics_no: Mapped[str] = mapped_column(String(40), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(ForeignKey("orders.order_no"), index=True)
    sku_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)

    order: Mapped[Order] = relationship(back_populates="items")


class AfterSaleRule(Base):
    __tablename__ = "after_sale_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(40))
    scene: Mapped[str] = mapped_column(String(24))       # no_reason / quality / wrong_item
    condition: Mapped[str] = mapped_column(String(200))
    window_days: Mapped[int] = mapped_column(Integer)
    need_evidence: Mapped[int] = mapped_column(Integer, default=0)
    allowed: Mapped[int] = mapped_column(Integer, default=1)
    effective_from: Mapped[datetime] = mapped_column(DateTime)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    version: Mapped[str] = mapped_column(String(24), default="R-2026.01")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_id: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(120))
    section: Mapped[str] = mapped_column(String(120), default="")
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40), default="general")  # 适用品类，general 为通用
    authority: Mapped[str] = mapped_column(String(40), default="平台售后政策")
    version: Mapped[str] = mapped_column(String(24), default="v2026.09")
    effective_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (Index("ix_chunk_doc", "doc_id", "chunk_index"),)


class AfterSaleDraft(Base):
    __tablename__ = "after_sale_drafts"

    draft_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    application_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    order_no: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    scene: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text, default="")
    refund_amount: Mapped[float] = mapped_column(Float, default=0.0)
    rule_version: Mapped[str] = mapped_column(String(24))
    expected_order_version: Mapped[int] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(String(12), default="low")
    status: Mapped[str] = mapped_column(String(20), default="DRAFTED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AfterSaleApplication(Base):
    __tablename__ = "after_sale_applications"

    application_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    draft_id: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    order_no: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    amount: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="SUBMITTED")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    trace_id: Mapped[str] = mapped_column(String(48), default="")


class HandoffTicket(Base):
    __tablename__ = "handoff_tickets"

    ticket_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(48), index=True)
    user_id: Mapped[str] = mapped_column(String(32))
    intent: Mapped[str] = mapped_column(String(32))
    slots: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_results: Mapped[dict] = mapped_column(JSON, default=dict)
    fail_reason: Mapped[str] = mapped_column(String(200), default="")
    risk_level: Mapped[str] = mapped_column(String(12), default="low")
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="WAITING")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(48), index=True)
    user_id: Mapped[str] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(12))
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (UniqueConstraint("thread_id", "id", name="uq_thread_turn"),)
