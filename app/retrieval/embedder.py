"""向量化：BGE-M3 优先，加载失败自动降级哈希向量，并显式标注模式。"""
from __future__ import annotations

import hashlib
import logging

import numpy as np

from app.config import settings

logger = logging.getLogger(__name__)

_STATE: dict[str, object] = {"mode": None, "model": None, "dim": None}


def _hash_embed(text: str, dim: int = 256) -> np.ndarray:
    """字符 n-gram 哈希向量：不下载模型也能跑通链路，但语义能力弱，仅作降级。"""
    vec = np.zeros(dim, dtype=np.float32)
    t = (text or "").replace(" ", "")
    grams = [t[i : i + 2] for i in range(max(0, len(t) - 1))] or [t]
    for g in grams:
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16) % dim
        vec[h] += 1.0
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


class _LocalBgeEncoder:
    """本地目录直读：SentenceTransformer 对本地路径会误判为 repo id，这里用 transformers 兜底。

    BGE-M3 的句向量取 [CLS] 并做 L2 归一化，与官方 sentence-transformers 配置一致。
    """

    def __init__(self, path: str) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        logger.info("直读本地模型目录 %s ...", path)
        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        self.model = AutoModel.from_pretrained(path, local_files_only=True).eval()
        self._dim = int(self.model.config.hidden_size)

    def get_sentence_embedding_dimension(self) -> int:
        return self._dim

    def encode(self, texts, batch_size: int = 32, normalize_embeddings: bool = True, show_progress_bar: bool = False):
        torch = self._torch
        out = []
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch = list(texts[i : i + batch_size])
                enc = self.tokenizer(batch, padding=True, truncation=True, max_length=512, return_tensors="pt")
                vec = self.model(**enc).last_hidden_state[:, 0]
                if normalize_embeddings:
                    vec = torch.nn.functional.normalize(vec, p=2, dim=1)
                out.append(vec.cpu().numpy())
        return np.vstack(out) if out else np.zeros((0, self._dim), dtype=np.float32)


def _load_bge():
    import os

    name = settings.embedding_model
    if os.path.isdir(name):
        return _LocalBgeEncoder(name)

    from sentence_transformers import SentenceTransformer  # 延迟导入，未安装直接抛错

    logger.info("加载向量模型 %s ...", name)
    model = SentenceTransformer(name, device="cpu")
    return model


def get_embedder():
    """单例懒加载；mode 决定使用 bge 还是 hash。"""
    if _STATE["mode"] is not None:
        return _STATE

    requested = settings.embedding_mode.lower()
    if requested in {"hash"}:
        _STATE.update(mode="hash", model=None, dim=256)
        return _STATE

    try:
        model = _load_bge()
        dim = int(model.get_sentence_embedding_dimension())
        _STATE.update(mode="bge", model=model, dim=dim)
        logger.info("向量模式：bge（%s，dim=%d）", settings.embedding_model, dim)
    except Exception as exc:  # noqa: BLE001
        logger.warning("BGE 加载失败，降级哈希向量：%s", exc)
        _STATE.update(mode="hash", model=None, dim=256)
    return _STATE


def encode(texts: list[str], batch_size: int | None = None) -> np.ndarray:
    state = get_embedder()
    if state["mode"] == "bge":
        model = state["model"]
        vectors = model.encode(
            texts, batch_size=batch_size or settings.embedding_batch,
            normalize_embeddings=True, show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)
    return np.vstack([_hash_embed(t) for t in texts]) if texts else np.zeros((0, 256), dtype=np.float32)


def embedding_mode() -> str:
    return str(get_embedder()["mode"])


def reset_embedder() -> None:
    """测试用：清除单例。"""
    _STATE.update(mode=None, model=None, dim=None)
