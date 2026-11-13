"""商品检索索引：BM25 + 向量双路召回 → RRF 融合 → 可解释精排。"""
from __future__ import annotations

import logging
from pathlib import Path

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

from app.config import settings
from app.retrieval import embedder
from app.retrieval.rerank import rerank_candidates
from app.retrieval.rrf import rrf_fuse
from app.services.product_service import product_doc

logger = logging.getLogger(__name__)

jieba.setLogLevel(logging.WARNING)

STATE: dict[str, object] = {
    "ready": False,
    "docs": [],
    "skus": [],
    "sku_idx": {},
    "tokens": [],
    "bm25": None,
    "vectors": None,
    "mode": None,
}


def _cache_file(mode: str, n: int) -> Path:
    return settings.data_dir / f"vectors_products_{mode}_{n}.npy"


def build_index(products: list[dict], force: bool = False) -> dict:
    """构建商品索引；向量落盘缓存，二次启动直接加载。"""
    if STATE["ready"] and not force and len(STATE["docs"]) == len(products):
        return {"reused": True, "n": len(products), "mode": STATE["mode"]}

    docs = [product_doc(p) for p in products]
    tokens = [list(jieba.cut(d)) for d in docs]
    bm25 = BM25Okapi(tokens)

    mode = embedder.embedding_mode()
    cache = _cache_file(mode, len(docs))
    if cache.exists() and not force:
        vectors = np.load(cache)
        logger.info("向量缓存命中：%s", cache.name)
    else:
        logger.info("编码 %d 条商品文档（mode=%s）...", len(docs), mode)
        vectors = embedder.encode(docs)
        try:
            np.save(cache, vectors)
        except OSError:
            pass

    STATE.update(
        ready=True,
        docs=docs,
        skus=[p["sku_id"] for p in products],
        sku_idx={p["sku_id"]: i for i, p in enumerate(products)},
        tokens=tokens,
        bm25=bm25,
        vectors=vectors,
        mode=mode,
        products=products,
    )
    logger.info("商品索引就绪：%d 条，mode=%s", len(products), mode)
    return {"reused": False, "n": len(products), "mode": mode}


def is_ready() -> bool:
    return bool(STATE["ready"])


def _allowed_indices(filters: dict) -> np.ndarray:
    products: list[dict] = STATE["products"]  # type: ignore[assignment]
    idx = []
    for i, p in enumerate(products):
        if filters.get("category") and p["category"] != filters["category"]:
            continue
        if filters.get("price_max") is not None and p["price"] > filters["price_max"]:
            continue
        if filters.get("price_min") is not None and p["price"] < filters["price_min"]:
            continue
        if filters.get("in_stock", True) and (p["available_qty"] or 0) <= 0:
            continue
        idx.append(i)
    return np.asarray(idx, dtype=np.int64)


def search(query: str, filters: dict | None = None, top_k: int | None = None, rerank: bool = True) -> dict:
    """返回 {candidates:[...], meta:{...}}，candidates 已按精排分降序。

    rerank=False 时按 RRF 融合分排序，仅用于评测隔离"相关性"与"业务精排"两层。
    """
    if not STATE["ready"]:
        raise RuntimeError("索引未就绪")
    filters = filters or {}
    top_k = top_k or settings.final_top_k
    allowed = _allowed_indices(filters)
    if allowed.size == 0:
        return {"candidates": [], "meta": {"reason": "hard_filter_empty", "allowed": 0}}

    # BM25 路：只在允许集合内取分
    bm25_scores = np.asarray(STATE["bm25"].get_scores(list(jieba.cut(query))), dtype=np.float32)
    bm_all = np.full(len(bm25_scores), -1e9, dtype=np.float32)
    bm_all[allowed] = bm25_scores[allowed]

    # 向量路：查询编码后与允许集合做余弦（向量已归一化，点积即余弦）
    qv = embedder.encode([query])[0]
    vec_all = np.full(len(bm25_scores), -1e9, dtype=np.float32)
    sims = np.asarray(STATE["vectors"], dtype=np.float32) @ qv  # type: ignore[arg-type]
    vec_all[allowed] = sims[allowed]

    bm_ranked = np.argsort(-bm_all)[: settings.bm25_top_k]
    vec_ranked = np.argsort(-vec_all)[: settings.vector_top_k]

    fused = rrf_fuse(
        [[int(i) for i in bm_ranked if bm_all[i] > -1e8],
         [int(i) for i in vec_ranked if vec_all[i] > -1e8]],
        k=settings.rrf_k,
        weights=[settings.rrf_bm25_weight, settings.rrf_vector_weight],
    )

    pool = fused[: max(top_k * 6, 20)]
    products: list[dict] = STATE["products"]  # type: ignore[assignment]
    candidates = []
    for i, rrf_score in pool:
        p = products[i]
        candidates.append(
            {
                **p,
                "rrf_score": round(rrf_score, 5),
                "bm25_score": round(float(bm_all[i]), 3) if bm_all[i] > -1e8 else 0.0,
                "vector_score": round(float(vec_all[i]), 4) if vec_all[i] > -1e8 else 0.0,
            }
        )

    ranked = rerank_candidates(candidates, filters, top_k=top_k) if rerank else [
        {**c, "score": c["rrf_score"], "explain": ["RRF 融合分排序"]} for c in candidates[:top_k]
    ]
    return {
        "candidates": ranked,
        "meta": {
            "allowed": int(allowed.size),
            "bm25_hits": len(bm_ranked),
            "vector_hits": len(vec_ranked),
            "fusion": "rrf",
            "k": settings.rrf_k,
            "embedding_mode": STATE["mode"],
        },
    }
