"""文档切块工具：标题层级切分，保留可追溯元数据。"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Chunk:
    title: str
    section: str
    content: str
    index: int


def chunk_markdown(text: str, max_chars: int = 400, min_chars: int = 40) -> list[Chunk]:
    """按 ## / ### 标题切块；表格行不拆开（避免条件与结论分离）。"""
    lines = text.splitlines()
    chunks: list[Chunk] = []
    title = ""
    section = ""
    buf: list[str] = []

    def flush():
        if not buf:
            return
        body = "\n".join(buf).strip()
        if len(body) >= min_chars:
            chunks.append(Chunk(title=title, section=section, content=body, index=len(chunks)))
        buf.clear()

    for line in lines:
        h = re.match(r"^(#{1,3})\s+(.*)$", line)
        if h:
            level = len(h.group(1))
            heading = h.group(2).strip()
            flush()
            if level == 1:
                title = heading
                section = ""
            else:
                section = heading
            continue
        buf.append(line)
        if sum(len(x) for x in buf) > max_chars:
            flush()
    flush()
    return chunks
