"""P3 本地 MCP 笔记检索与受控任务创建服务（离线核心，规划实现中）。

本包当前包含：
- Slice A：search_notes 的纯标准库数据合同、索引与离线检索逻辑。
- Slice B1：safe_open 句柄级路径安全索引层（Windows 原生 API，仅索引/读取）。
- Slice B2a：tasks 受控写入离线核心（create_task 数据合同、HITL 状态机、sqlite3
  持久化、no-replace 原子发布）。B2a 不含任何 MCP Server/Resource/stdio/Host/Client
  代码（属于后续 B2b，需单独批准）。

全包不接触网络、模型或真实私人笔记；路径安全与受控写均失败关闭、不降级。
"""

from .contracts import (
    KEYWORD_MIN,
    KEYWORD_MAX,
    MAX_HITS,
    EXCERPT_MAX,
    INVALID_ARGUMENTS,
    TASK_TITLE_MIN,
    TASK_TITLE_MAX,
    TASK_DESC_MIN,
    TASK_DESC_MAX,
    Keyword,
    NoteIndexEntry,
    SearchHit,
    SearchResult,
    validate_keyword,
    validate_task_field,
    parse_search_notes_args,
)
from .index import compute_note_id, extract_title, build_index, read_note_content
from .search import search_notes
from .tasks import (
    TasksStore,
    TrustedContext,
    TaskResult,
    TaskIntent,
    TaskPublishError,
    CONFIRMATION_REQUIRED,
    CONFIRMATION_IDENTITY_MISMATCH,
    CONFIRMATION_MISMATCH,
    CONFIRMATION_EXPIRED,
    CONFIRMATION_ALREADY_CONSUMED,
    CONFIRMATION_INVALID_ID,
    IDEMPOTENCY_CONFLICT,
    TASK_CONFLICT,
    TASK_WRITE_FAILED,
    TASK_INVALID_ID,
    TASK_ROOT_UNSAFE,
    CONFIRM_VALIDITY_SECONDS,
)

__all__ = [
    "KEYWORD_MIN",
    "KEYWORD_MAX",
    "MAX_HITS",
    "EXCERPT_MAX",
    "INVALID_ARGUMENTS",
    "TASK_TITLE_MIN",
    "TASK_TITLE_MAX",
    "TASK_DESC_MIN",
    "TASK_DESC_MAX",
    "Keyword",
    "NoteIndexEntry",
    "SearchHit",
    "SearchResult",
    "validate_keyword",
    "validate_task_field",
    "parse_search_notes_args",
    "compute_note_id",
    "extract_title",
    "build_index",
    "read_note_content",
    "search_notes",
    "TasksStore",
    "TrustedContext",
    "TaskResult",
    "TaskIntent",
    "TaskPublishError",
    "CONFIRMATION_REQUIRED",
    "CONFIRMATION_IDENTITY_MISMATCH",
    "CONFIRMATION_MISMATCH",
    "CONFIRMATION_EXPIRED",
    "CONFIRMATION_ALREADY_CONSUMED",
    "CONFIRMATION_INVALID_ID",
    "IDEMPOTENCY_CONFLICT",
    "TASK_CONFLICT",
    "TASK_WRITE_FAILED",
    "TASK_INVALID_ID",
    "TASK_ROOT_UNSAFE",
    "CONFIRM_VALIDITY_SECONDS",
]
