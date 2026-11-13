"""RRF 融合：按排名而非原始分数融合，规避不同检索器分数量纲不可比。

支持按通道加权：属性词直给的查询里词法通道更可靠，权重可调大。
"""
from __future__ import annotations


def rrf_fuse(rank_lists: list[list[int]], k: int = 60, weights: list[float] | None = None) -> list[tuple[int, float]]:
    if weights is None:
        weights = [1.0] * len(rank_lists)
    scores: dict[int, float] = {}
    for w, ranked in zip(weights, rank_lists):
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
    return sorted(scores.items(), key=lambda kv: -kv[1])
