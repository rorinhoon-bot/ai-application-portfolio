"""P3 Slice A：search_notes 数据合同与参数校验（纯标准库，离线）。

本模块只定义数据类型、稳定错误码与纯函数校验。不接触 MCP SDK、网络、模型
或真实私人笔记。路径安全（symlink/junction/reparse point/TOCTOU）属于后续切片，
未在此实现；本模块的校验拒绝把任意输入当成路径、URL 或 Shell 指令。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Optional

# 稳定错误码（对外不泄露路径、正文或异常栈）
INVALID_ARGUMENTS = "invalid-arguments"

# 合同常量
KEYWORD_MIN = 1
KEYWORD_MAX = 80
MAX_HITS = 5
EXCERPT_MAX = 120  # SearchHit.excerpt 内部文本上限（不含省略号）

# 危险文本形态（即便用户只是普通搜索也要拒绝，避免被当成路径/URL/命令）
_URL_PREFIXES = ("http://", "https://", "ftp://", "file://")
_SHELL_TOKENS = (";", "|", "&&", "||", "$(", "`", "<", ">", "&")


@dataclass(frozen=True)
class Keyword:
    """已归一化（去首尾空白）的搜索关键词，长度 KEYWORD_MIN..KEYWORD_MAX。"""

    value: str


@dataclass(frozen=True)
class NoteIndexEntry:
    """启动时登记的笔记元数据。relative_path 仅用于内部映射，不进入结果。"""

    note_id: str
    title: str
    relative_path: str
    size: int
    sha256: str
    registered: bool = True


@dataclass(frozen=True)
class SearchHit:
    """单条命中。excerpt 为脱敏截断文本，match_count 为该笔记命中次数。"""

    note_id: str
    title: str
    excerpt: str
    match_count: int


@dataclass(frozen=True)
class SearchResult:
    """对外返回。status 为 \"ok\" 或稳定错误码；error_code 冗余携带错误码。"""

    status: str
    hits: tuple
    total_matched: int
    error_code: Optional[str]


def _has_control_char(s: str) -> bool:
    return any(unicodedata.category(ch) == "Cc" for ch in s)


def _looks_like_path(s: str) -> bool:
    if s.startswith(("/", "\\")):
        return True
    # Windows 盘符：C:\ 或 C:/
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
        return True
    # 路径穿越段 ..
    norm = s.replace("\\", "/")
    if ".." in norm.split("/"):
        return True
    return False


def _looks_like_url(s: str) -> bool:
    low = s.lower()
    return any(low.startswith(p) for p in _URL_PREFIXES)


def _has_shell_token(s: str) -> bool:
    return any(tok in s for tok in _SHELL_TOKENS)


def validate_keyword(raw: str) -> Optional[Keyword]:
    """校验单个关键词字符串。合法返回 Keyword，非法返回 None（不读不写）。

    拒绝：非字符串、空白、超长、控制字符、绝对路径、.. 段、URL scheme、Shell 语义。
    """
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if len(value) < KEYWORD_MIN or len(value) > KEYWORD_MAX:
        return None
    if _has_control_char(value):
        return None
    if _looks_like_path(value):
        return None
    if _looks_like_url(value):
        return None
    if _has_shell_token(value):
        return None
    return Keyword(value=value)


def parse_search_notes_args(args) -> Optional[Keyword]:
    """MCP 参数层校验：拒绝非对象、未知字段、keyword 非字符串。"""
    if not isinstance(args, dict):
        return None
    if set(args.keys()) != {"keyword"}:
        return None
    return validate_keyword(args["keyword"])
