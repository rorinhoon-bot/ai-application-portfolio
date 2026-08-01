"""P3 Slice A：笔记索引构建与内容读取（纯标准库，离线）。

注意：本切片仅做最小文件登记与普通文件读取；symlink/junction/reparse point、
路径穿越与 TOCTOU 的拒绝式检查属于后续路径安全切片，未在此实现。当前 build_index
对普通 .md 文件登记元数据，不展开完整防护。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .contracts import NoteIndexEntry

NOTE_EXT = ".md"


def compute_note_id(relative_path: str) -> str:
    """note_id 由 relative_path 的 SHA-256 前 16 位派生：稳定、重排不变、不可逆推路径。"""
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def extract_title(text: str, fallback_name: str) -> str:
    """取首个一级标题文本；无则回退为文件名（去 .md）。"""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    if fallback_name.endswith(NOTE_EXT):
        return fallback_name[: -len(NOTE_EXT)]
    return fallback_name


def build_index(notes_root: os.PathLike | str) -> list[NoteIndexEntry]:
    """从笔记根目录登记普通 .md 文件，生成 NoteIndexEntry 列表（按相对路径排序）。"""
    root = Path(notes_root)
    entries: list[NoteIndexEntry] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() != NOTE_EXT:
            continue
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        rel = str(path.relative_to(root)).replace("\\", "/")
        entries.append(
            NoteIndexEntry(
                note_id=compute_note_id(rel),
                title=extract_title(text, path.name),
                relative_path=rel,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )
    return entries


def read_note_content(entry: NoteIndexEntry, notes_root: os.PathLike | str) -> str:
    """按登记的 relative_path 读取笔记正文（UTF-8）。"""
    root = Path(notes_root)
    path = root / entry.relative_path
    return path.read_text(encoding="utf-8", errors="replace")
