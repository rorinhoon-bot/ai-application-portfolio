"""P3 Slice A+B1：search_notes 数据合同、参数校验与路径安全常量（纯标准库，离线）。

本模块只定义数据类型、稳定错误码与纯函数校验。不接触 MCP SDK、网络、模型
或真实私人笔记。

Slice A 安全要点（P1 修复）：
- `validate_keyword` 先做 NFKC 归一，再做形态拒绝，防止全角 `／＼：｜＜＞＆`
  等经归一后绕过路径/URL/Shell 检查。
- 非法参数返回稳定 `ArgumentError` 错误对象（error_code 固定 invalid-arguments），
  而不是 None，便于调用方稳定判定与脱敏返回。
- `title` 视为不可信笔记数据，提供转义 + 限长的纯函数，在索引登记处统一净化。

Slice B1 路径安全常量与错误码：
- 原生/Win32 枚举使用不同具名常量，避免混淆（见下方 *FILE_*_INFORMATION）。
- 稳定错误码不泄露路径、正文、用户名、环境变量或原始系统错误文本。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Union

# 稳定错误码（对外不泄露路径、正文或异常栈）
INVALID_ARGUMENTS = "invalid-arguments"

# 合同常量
KEYWORD_MIN = 1
KEYWORD_MAX = 80
MAX_HITS = 5
EXCERPT_MAX = 120  # SearchHit.excerpt 最终长度硬上限（含转义与省略号）
TITLE_MAX = 80  # 笔记标题安全输出长度硬上限（含转义与省略号）

# 危险文本形态（即便用户只是普通搜索也要拒绝，避免被当成路径/URL/命令）
_URL_PREFIXES = ("http://", "https://", "ftp://", "file://")
_SHELL_TOKENS = (";", "|", "&&", "||", "$(", "`", "<", ">", "&")

# Slice B1：路径安全索引稳定错误码（对外不含路径/正文/用户名/异常细节）
INDEX_BUILD_FAILED = "index-build-failed"
NOT_ALLOWED_REPARSE = "not-allowed-reparse"
NOT_A_REGULAR_FILE = "not-a-regular-file"
PATH_ESCAPE = "path-escape"
IO_ERROR = "io-error"
UNSAFE_OPEN_UNAVAILABLE = "unsafe-open-unavailable"
CONTENT_TOO_LARGE = "content-too-large"
NOT_REGISTERED = "not-registered"

# Slice B1：单笔记内容读取容量上限（1 MiB）。区别于 Slice A 的 EXCERPT_MAX=120 检索摘录上限。
MAX_NOTE_BYTES = 1_048_576

# Slice B1：原生 / Win32 枚举具名常量（v6 防止两类枚举数值巧合而混淆）
NATIVE_FILE_DIRECTORY_INFORMATION = 1  # 原生 FILE_INFORMATION_CLASS（NtQueryDirectoryFile 用）
WIN32_FILE_BASIC_INFO = 0             # Win32 FILE_INFO_BY_HANDLE_CLASS（GetFileInformationByHandleEx 用）
WIN32_FILE_STANDARD_INFO = 1          # Win32 FILE_INFO_BY_HANDLE_CLASS（GetFileInformationByHandleEx 用）


@dataclass(frozen=True)
class Keyword:
    """已归一化（NFKC + 去首尾空白）的搜索关键词，长度 KEYWORD_MIN..KEYWORD_MAX。"""

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
    error_code: Union[str, None]


@dataclass(frozen=True)
class ArgumentError:
    """稳定非法参数错误对象。所有参数校验失败统一返回该对象，error_code 固定。

    调用方据此稳定判定“参数非法”，而不是依赖 None 或异常；对外可映射为
    稳定错误码，不泄露路径、正文或异常细节。
    """

    error_code: str = INVALID_ARGUMENTS


# 统一返回类型：合法为 Keyword，非法为 ArgumentError
ValidationResult = Union[Keyword, ArgumentError]


def _escape_char(ch: str) -> str:
    """转义单个 HTML 特殊字符；其余原样返回。"""
    if ch == "&":
        return "&amp;"
    if ch == "<":
        return "&lt;"
    if ch == ">":
        return "&gt;"
    return ch


def _escape_only(text: str) -> str:
    """仅转义 HTML 特殊字符（不做长度截断）。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sanitize_budget(text: str, budget: int) -> str:
    """丢弃控制字符、转义 HTML 特殊字符，并截断使最终转义长度 <= budget。

    budget 为“最终转义文本”的字符预算；因 &/</> 会膨胀为多字符实体，必须按
    转义后的真实长度累计，避免超过上限。
    """
    out: list[str] = []
    length = 0
    for ch in text:
        if unicodedata.category(ch) == "Cc":
            continue
        esc = _escape_char(ch)
        if length + len(esc) > budget:
            break
        out.append(esc)
        length += len(esc)
    return "".join(out)


def sanitize_title(text: str, max_len: int = TITLE_MAX) -> str:
    """把不可信笔记标题净化成安全输出：去控制字符、转义 HTML、限长。

    若净化后需截断，末尾补一个省略号并计入上限，确保最终长度 <= max_len。
    这是标题进入结果的唯一净化边界；SearchHit 直接复用已净化的标题，避免二次转义。
    """
    cleaned = "".join(ch for ch in text if unicodedata.category(ch) != "Cc")
    if len(_escape_only(cleaned)) <= max_len:
        return _escape_only(cleaned)
    budget = max(0, max_len - 1)  # 预留一个省略号
    return _sanitize_budget(cleaned, budget) + "…"


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


def validate_keyword(raw: str) -> ValidationResult:
    """校验单个关键词字符串。合法返回 Keyword；非法返回 ArgumentError（不读不写）。

    顺序（P1 修复）：
    1. 非字符串直接拒绝。
    2. 先 NFKC 归一——防止全角 `／＼：｜＜＞＆＄（` 等经归一后变成危险形态。
    3. 再去首尾空白，按归一后长度判定 1..80。
    4. 拒绝控制字符、绝对路径、`..` 段、URL scheme、Shell 语义。
    """
    if not isinstance(raw, str):
        return ArgumentError()
    value = unicodedata.normalize("NFKC", raw).strip()
    if len(value) < KEYWORD_MIN or len(value) > KEYWORD_MAX:
        return ArgumentError()
    if _has_control_char(value):
        return ArgumentError()
    if _looks_like_path(value):
        return ArgumentError()
    if _looks_like_url(value):
        return ArgumentError()
    if _has_shell_token(value):
        return ArgumentError()
    return Keyword(value=value)


def parse_search_notes_args(args) -> ValidationResult:
    """MCP 参数层校验：拒绝非对象、未知字段、keyword 非字符串；非法返回 ArgumentError。"""
    if not isinstance(args, dict):
        return ArgumentError()
    if set(args.keys()) != {"keyword"}:
        return ArgumentError()
    return validate_keyword(args["keyword"])
