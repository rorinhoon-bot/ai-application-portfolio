"""P3 本地 MCP 笔记检索与受控任务创建服务（规划实现中）。

本包当前仅包含 Slice A：search_notes 的纯标准库数据合同、索引与离线检索逻辑。
不接触 MCP SDK、网络、模型或真实私人笔记。路径安全（symlink/junction/reparse
point/TOCTOU）属于后续切片，本切片未实现。
"""

from .contracts import (
    KEYWORD_MIN,
    KEYWORD_MAX,
    MAX_HITS,
    EXCERPT_MAX,
    INVALID_ARGUMENTS,
    Keyword,
    NoteIndexEntry,
    SearchHit,
    SearchResult,
    validate_keyword,
    parse_search_notes_args,
)
from .index import compute_note_id, extract_title, build_index, read_note_content
from .search import search_notes

__all__ = [
    "KEYWORD_MIN",
    "KEYWORD_MAX",
    "MAX_HITS",
    "EXCERPT_MAX",
    "INVALID_ARGUMENTS",
    "Keyword",
    "NoteIndexEntry",
    "SearchHit",
    "SearchResult",
    "validate_keyword",
    "parse_search_notes_args",
    "compute_note_id",
    "extract_title",
    "build_index",
    "read_note_content",
    "search_notes",
]
