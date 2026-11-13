"""政策知识库检索：按品类过滤 + BM25/向量双路 → RRF；返回带版本的引用。"""
from __future__ import annotations

import logging

import jieba
import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select

from app.db.models import KnowledgeChunk
from app.db.session import session_scope
from app.retrieval import embedder
from app.retrieval.rrf import rrf_fuse

logger = logging.getLogger(__name__)

STATE: dict[str, object] = {"ready": False, "chunks": [], "bm25": None, "vectors": None}


def build_policy_index(force: bool = False) -> dict:
    if STATE["ready"] and not force:
        return {"reused": True, "n": len(STATE["chunks"])}  # type: ignore[arg-type]

    with session_scope() as db:
        rows = db.scalars(select(KnowledgeChunk).order_by(KnowledgeChunk.id)).all()
        chunks = [
            {
                "id": c.id,
                "doc_id": c.doc_id,
                "title": c.title,
                "section": c.section,
                "content": c.content,
                "category": c.category,
                "authority": c.authority,
                "version": c.version,
                "effective_at": c.effective_at.strftime("%Y-%m-%d"),
                "chunk_index": c.chunk_index,
            }
            for c in rows
        ]
    tokens = [list(jieba.cut(f"{c['title']}{c['section']}{c['content']}")) for c in chunks]
    STATE.update(
        ready=True,
        chunks=chunks,
        bm25=BM25Okapi(tokens) if tokens else None,
        vectors=embedder.encode([f"{c['title']}｜{c['section']}｜{c['content']}" for c in chunks])
        if chunks else np.zeros((0, 256), dtype=np.float32),
    )
    logger.info("政策索引就绪：%d 块", len(chunks))
    return {"reused": False, "n": len(chunks)}


def search_policy(query: str, category: str | None = None, top_k: int = 4) -> list[dict]:
    if not STATE["ready"] or not STATE["chunks"]:
        return []
    chunks: list[dict] = STATE["chunks"]  # type: ignore[assignment]
    allowed = np.array(
        [i for i, c in enumerate(chunks) if category in (None, "general") or c["category"] in {category, "general"}],
        dtype=np.int64,
    )
    if allowed.size == 0:
        return []

    bm_scores = np.asarray(STATE["bm25"].get_scores(list(jieba.cut(query))), dtype=np.float32)
    bm_all = np.full(len(chunks), -1e9, dtype=np.float32)
    bm_all[allowed] = bm_scores[allowed]

    qv = embedder.encode([query])[0]
    vec_all = np.full(len(chunks), -1e9, dtype=np.float32)
    vec_all[allowed] = (np.asarray(STATE["vectors"], dtype=np.float32) @ qv)[allowed]

    bm_rank = [int(i) for i in np.argsort(-bm_all)[:12] if bm_all[i] > -1e8]
    vec_rank = [int(i) for i in np.argsort(-vec_all)[:12] if vec_all[i] > -1e8]
    fused = rrf_fuse([bm_rank, vec_rank])[:top_k]

    out = []
    for i, score in fused:
        c = chunks[i]
        out.append(
            {
                **c,
                "score": round(score, 5),
                "bm25": round(float(bm_all[i]), 3) if bm_all[i] > -1e8 else 0.0,
                "vector": round(float(vec_all[i]), 4) if vec_all[i] > -1e8 else 0.0,
            }
        )
    return out


def is_ready() -> bool:
    return bool(STATE["ready"])
