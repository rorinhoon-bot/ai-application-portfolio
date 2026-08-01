"""P3 Slice A：search_notes 离线检索逻辑（纯标准库，离线）。

匹配规则（已由数据合同锁定）：大小写无关 + Unicode NFKC 归一；正文不执行、不解析
为权限、不访问其中 URL。结果仅含稳定 note_id、标题、脱敏截断摘录与匹配计数。
"""

from __future__ import annotations

import unicodedata
from typing import Callable, Sequence

from .contracts import (
    Keyword,
    NoteIndexEntry,
    SearchHit,
    SearchResult,
    MAX_HITS,
    EXCERPT_MAX,
)


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def _escape_excerpt(text: str) -> str:
    # 去除控制字符，转义 HTML 特殊字符；正文永远不以原始危险形态出现在结果中
    cleaned = "".join(ch for ch in text if unicodedata.category(ch) != "Cc")
    return cleaned.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _make_excerpt(norm_text: str, kw_norm: str, max_len: int) -> str:
    idx = norm_text.find(kw_norm)
    if idx == -1:
        snippet = norm_text[:max_len]
        return _escape_excerpt(snippet)
    start = max(0, idx - 20)
    end = min(len(norm_text), start + max_len)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(norm_text) else ""
    return prefix + _escape_excerpt(norm_text[start:end]) + suffix


def search_notes(
    keyword: Keyword,
    entries: Sequence[NoteIndexEntry],
    content_provider: Callable[[NoteIndexEntry], str],
    *,
    max_hits: int = MAX_HITS,
    excerpt_max: int = EXCERPT_MAX,
) -> SearchResult:
    """对登记笔记做确定性关键词匹配。content_provider 注入正文来源（便于测试隔离）。

    返回：命中笔记按索引顺序；最多 max_hits 条；total_matched 为命中笔记总数。
    """
    kw = _normalize(keyword.value)
    hits: list[SearchHit] = []
    for entry in entries:
        text = content_provider(entry)
        norm_text = _normalize(text)
        count = norm_text.count(kw)
        if count == 0:
            continue
        hits.append(
            SearchHit(
                note_id=entry.note_id,
                title=entry.title,
                excerpt=_make_excerpt(norm_text, kw, excerpt_max),
                match_count=count,
            )
        )
    if not hits:
        return SearchResult(status="ok", hits=(), total_matched=0, error_code=None)
    return SearchResult(
        status="ok",
        hits=tuple(hits[:max_hits]),
        total_matched=len(hits),
        error_code=None,
    )
