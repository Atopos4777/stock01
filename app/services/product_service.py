"""商品服务：结构化硬过滤（类目/预算/库存/状态），不做语义判断。"""
from __future__ import annotations

from sqlalchemy import select

from app.db.models import Inventory, Product
from app.db.session import session_scope


def _row(p: Product, inv: Inventory | None) -> dict:
    return {
        "sku_id": p.sku_id,
        "spu_id": p.spu_id,
        "title": p.title,
        "category": p.category,
        "sub_category": p.sub_category,
        "brand": p.brand,
        "price": p.price,
        "attributes": p.attributes or {},
        "description": p.description,
        "review_summary": p.review_summary,
        "sales_30d": p.sales_30d,
        "rating": p.rating,
        "status": p.status,
        "available_qty": inv.available_qty if inv else 0,
    }


def list_all_products(limit: int | None = None) -> list[dict]:
    with session_scope() as db:
        stmt = select(Product, Inventory).join(
            Inventory, Inventory.sku_id == Product.sku_id, isouter=True
        )
        if limit:
            stmt = stmt.limit(limit)
        return [_row(p, inv) for p, inv in db.execute(stmt).all()]


def filter_products(
    category: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    in_stock: bool = True,
    limit: int = 600,
) -> list[dict]:
    """硬约束过滤：预算、类目、库存、上架状态。语义偏好交给检索层。"""
    with session_scope() as db:
        stmt = select(Product, Inventory).join(
            Inventory, Inventory.sku_id == Product.sku_id, isouter=True
        ).where(Product.status == "on_sale")
        if category:
            stmt = stmt.where(Product.category == category)
        if price_min is not None:
            stmt = stmt.where(Product.price >= price_min)
        if price_max is not None:
            stmt = stmt.where(Product.price <= price_max)
        if in_stock:
            stmt = stmt.where(Inventory.available_qty > 0)
        rows = db.execute(stmt.limit(limit)).all()
        return [_row(p, inv) for p, inv in rows]


def get_live_offer(sku_ids: list[str]) -> dict[str, dict]:
    """实时价格/库存/促销资格：唯一可信来源，禁止用知识库替代。"""
    with session_scope() as db:
        rows = db.execute(
            select(Product, Inventory).join(
                Inventory, Inventory.sku_id == Product.sku_id, isouter=True
            ).where(Product.sku_id.in_(sku_ids))
        ).all()
        out: dict[str, dict] = {}
        for p, inv in rows:
            promo = None
            if p.sales_30d > 1000:
                promo = "满300减30"
            elif p.sales_30d > 300:
                promo = "新客立减10元"
            out[p.sku_id] = {
                "sku_id": p.sku_id,
                "price": p.price,
                "available_qty": inv.available_qty if inv else 0,
                "status": p.status,
                "promo": promo,
                "queried_at": "live",
            }
        return out


def categories() -> list[str]:
    with session_scope() as db:
        return [c for (c,) in db.execute(select(Product.category).distinct()).all()]


def product_doc(p: dict) -> str:
    """检索用文档：标题 + 类目 + 属性 + 描述 + 评价摘要。"""
    attrs = "、".join(f"{k}{v}" for k, v in (p.get("attributes") or {}).items())
    return f"{p['title']}｜{p['category']}｜{p['sub_category']}｜{attrs}｜{p['description']}｜{p['review_summary']}"
