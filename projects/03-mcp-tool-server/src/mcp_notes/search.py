"""P3 Slice A：search_notes 离线检索逻辑（纯标准库，离线）。

匹配规则（已由数据合同锁定）：Unicode NFKC 归一 + casefold（比 lower 更强，覆盖
ß→ss 等）；正文不执行、不解析为权限、不访问其中 URL。结果仅含稳定 note_id、标题、
脱敏截断摘录与匹配计数。

安全要点（P1 修复）：
- hits 上限 5、excerpt 上限 120 为模块常量硬上限，函数不接收可调参数，调用方无法绕过。
- excerpt 转义后（&/</> 膨胀为多字符实体）与省略号一并计入 120 长度预算，最终长度必 <= 120。
- 标题来自已净化的 NoteIndexEntry.title，直接复用，不做二次转义（避免实体被重复转义）。
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
    _sanitize_budget,
)


def _normalize(text: str) -> str:
    # NFKC 归一 + casefold：确定性、覆盖全角与德文 ß 等大小写折叠
    return unicodedata.normalize("NFKC", text).casefold()


def _make_excerpt(norm_text: str, kw_norm: str) -> str:
    """围绕命中位置取上下文窗口，转义并截断使最终长度（含省略号）<= EXCERPT_MAX。"""
    idx = norm_text.find(kw_norm)
    if idx == -1:
        start, end = 0, len(norm_text)
    else:
        context = 20
        start = max(0, idx - context)
        end = min(len(norm_text), idx + len(kw_norm) + context)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(norm_text) else ""
    # 省略号计入预算：可用文本预算 = 上限 - 实际省略号长度
    budget = EXCERPT_MAX - len(prefix) - len(suffix)
    if budget < 0:
        budget = 0
    window = norm_text[start:end]
    escaped = _sanitize_budget(window, budget)
    return prefix + escaped + suffix


def search_notes(
    keyword: Keyword,
    entries: Sequence[NoteIndexEntry],
    content_provider: Callable[[NoteIndexEntry], str],
) -> SearchResult:
    """对登记笔记做确定性关键词匹配。content_provider 注入正文来源（便于测试隔离）。

    返回：命中笔记按索引顺序；最多 MAX_HITS(5) 条；total_matched 为命中笔记总数。
    hits 与 excerpt 上限均为硬常量，调用方无法通过参数放大。
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
                excerpt=_make_excerpt(norm_text, kw),
                match_count=count,
            )
        )
    if not hits:
        return SearchResult(status="ok", hits=(), total_matched=0, error_code=None)
    # 硬上限：即便命中更多也只返回前 MAX_HITS 条（按索引顺序）
    capped = hits[:MAX_HITS]
    return SearchResult(
        status="ok",
        hits=tuple(capped),
        total_matched=len(hits),
        error_code=None,
    )
