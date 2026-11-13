"""证据充分性判断与引用构造：无证据必须拒答，不允许模型自由发挥。"""
from __future__ import annotations

MIN_SCORE = 0.012  # RRF 阈值：低于此视为证据不足


def is_grounded(chunks: list[dict]) -> bool:
    if not chunks:
        return False
    top = chunks[0]
    return top.get("score", 0.0) >= MIN_SCORE and (top.get("bm25", 0.0) > 0.5 or top.get("vector", 0.0) > 0.35)


def build_citations(chunks: list[dict]) -> list[dict]:
    seen: set[str] = set()
    citations = []
    for c in chunks:
        key = f"{c['doc_id']}#{c['section']}"
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            {
                "doc_id": c["doc_id"],
                "title": c["title"],
                "section": c["section"],
                "version": c["version"],
                "effective_at": c["effective_at"],
                "authority": c["authority"],
                "excerpt": c["content"][:160] + ("…" if len(c["content"]) > 160 else ""),
                "score": c.get("score", 0.0),
            }
        )
    return citations


def refuse_message() -> str:
    return (
        "这个问题我目前没有找到可依据的正式政策条款，为避免给你错误信息，我先不做结论。"
        "你可以换个说法，或直接转人工客服核实（我会把会话上下文一并交接）。"
    )
