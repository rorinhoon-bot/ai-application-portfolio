"""P3 Slice B1：笔记索引构建与内容读取（句柄级路径安全，离线）。

本切片通过 `safe_open` 的 Windows 原生句柄层（NtOpenFile / NtQueryDirectoryFile）
建立 `.md` 笔记索引并读取正文，抵御 symlink / junction / reparse point 跟随与
TOCTOU，并拒绝 `..` 路径逃逸与非普通文件。

保留 Slice A 行为：`compute_note_id`、`extract_title`、NoteIndexEntry 字段
（note_id / title / relative_path / size / sha256）与字符串读取结果不变。

事务语义（§9）：索引构建整体失败（含原生不可用、配置非法、IO 错误、reparse、
超大文件 > MAX_NOTE_BYTES 等）时整体失败、不发布部分索引。
超大文件使本次构建失败并丢弃新索引，绝不静默跳过或发布部分结果。
"""

from __future__ import annotations

import hashlib

from .contracts import NoteIndexEntry, TITLE_MAX, sanitize_title

NOTE_EXT = ".md"


def compute_note_id(relative_path: str) -> str:
    """note_id 由 relative_path 的 SHA-256 前 16 位派生：稳定、重排不变、不可逆推路径。"""
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def extract_title(text: str, fallback_name: str) -> str:
    """取首个一级标题文本；无则回退为文件名（去 .md）。

    标题来自不可信笔记内容，统一经 sanitize_title 净化（去控制字符、转义 HTML、
    限长）后进入索引与结果，不在检索层二次转义。
    """
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return sanitize_title(s[2:].strip(), TITLE_MAX)
    if fallback_name.endswith(NOTE_EXT):
        return sanitize_title(fallback_name[: -len(NOTE_EXT)], TITLE_MAX)
    return sanitize_title(fallback_name, TITLE_MAX)


def _make_entry(relative_path: str, data: bytes, filename: str) -> NoteIndexEntry:
    """从文件字节构造 NoteIndexEntry（保留 Slice A 字段语义）。"""
    text = data.decode("utf-8", errors="replace")
    return NoteIndexEntry(
        note_id=compute_note_id(relative_path),
        title=extract_title(text, filename),
        relative_path=relative_path,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def build_index(notes_root: object) -> list[NoteIndexEntry]:
    """从笔记根目录经句柄级路径安全层登记 `.md` 文件，生成 NoteIndexEntry 列表。

    整体失败（原生不可用 / 配置非法 / IO 错误 / reparse / 超大文件等）抛
    `IndexBuildFailed`，不发布部分索引（§9）。超大文件（> MAX_NOTE_BYTES）会使
    本次构建失败并丢弃新索引，绝不静默跳过。
    """
    from . import safe_open

    if not safe_open.verify_native_support():
        # R0：绝不回退到字符串路径方案
        raise safe_open.UnsafeOpenUnavailable()

    root_h = None
    entries: list[NoteIndexEntry] = []
    try:
        root_name = safe_open.configure_root(str(notes_root))
        root_h = safe_open._nt_open(0, root_name, is_dir=True)

        def consumer(rel_parts: list[str]) -> None:
            rel = "/".join(rel_parts)
            # 超大文件会在此抛出 ContentTooLarge → 向上传播 → 整个构建失败
            data = safe_open.open_file_relative(root_h, rel_parts)
            entries.append(_make_entry(rel, data, rel_parts[-1]))

        safe_open._walk(root_h, [], consumer)
    except safe_open.SafeOpenError:
        # 构建失败：丢弃新索引，不发布部分（§9 事务语义）。
        # 涵盖 NotAllowedReparse / ContentTooLarge / IoError / PathEscape 等。
        raise safe_open.IndexBuildFailed()
    finally:
        if root_h is not None:
            safe_open._close(root_h)

    entries.sort(key=lambda e: e.relative_path)
    return entries


def read_note_content(entry: NoteIndexEntry, notes_root: object) -> str:
    """按登记的 relative_path 经句柄级路径安全层读取笔记正文（UTF-8）。"""
    from . import safe_open

    if not safe_open.verify_native_support():
        raise safe_open.UnsafeOpenUnavailable()

    root_h = None
    try:
        root_name = safe_open.configure_root(str(notes_root))
        root_h = safe_open._nt_open(0, root_name, is_dir=True)
        parts = entry.relative_path.replace("\\", "/").split("/")
        data = safe_open.open_file_relative(root_h, parts)
    finally:
        if root_h is not None:
            safe_open._close(root_h)
    return data.decode("utf-8", errors="replace")
