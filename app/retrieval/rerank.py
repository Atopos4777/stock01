"""可解释精排：RRF 相关性 + 业务信号（库存/销量/评分/预算贴合），权重显式可配。"""
from __future__ import annotations

W = {
    "rrf": 1.0,
    "stock": 0.12,
    "sales": 0.18,
    "rating": 0.10,
    "budget_fit": 0.15,
}


def rerank_candidates(candidates: list[dict], filters: dict, top_k: int = 3) -> list[dict]:
    budget = filters.get("price_max")
    for c in candidates:
        reasons = []
        # 相关性归一：RRF 最大约 2/(k+1)
        rel = min(1.0, c["rrf_score"] * 30)
        stock = 1.0 if c["available_qty"] >= 20 else (0.6 if c["available_qty"] > 0 else 0.0)
        sales = min(1.0, c["sales_30d"] / 3000)
        rating = max(0.0, (c["rating"] - 3.5) / 1.5)
        fit = 1.0
        if budget:
            fit = max(0.0, 1.0 - (budget - c["price"]) / budget * 0.3)

        total = (
            W["rrf"] * rel + W["stock"] * stock + W["sales"] * sales
            + W["rating"] * rating + W["budget_fit"] * fit
        )
        if c["available_qty"] < 20:
            reasons.append(f"库存仅 {c['available_qty']} 件")
        if c["sales_30d"] > 1000:
            reasons.append("近 30 天销量较高")
        if c["rating"] >= 4.6:
            reasons.append(f"评分 {c['rating']}")
        if budget and c["price"] <= budget:
            reasons.append(f"价格 {c['price']:.0f} 元在预算内")

        c["score"] = round(total, 4)
        c["explain"] = reasons or ["与需求相关性较高"]
    return sorted(candidates, key=lambda x: -x["score"])[:top_k]
