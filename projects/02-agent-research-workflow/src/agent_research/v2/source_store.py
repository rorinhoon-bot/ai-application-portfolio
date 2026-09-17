"""Read-only, versioned source snapshot used by V2 tools."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

from agent_research.v2.contracts import (
    EvidenceRecord,
    ResearchRequestV2,
    SourceEntryV2,
    SourceSnapshotV2,
)


class SourceStoreError(ValueError):
    """Raised for unsafe or inconsistent source data."""


_HEADING = re.compile(
    r"^##\s+(?:\[([a-z][a-z0-9-]*)\]\s+)?(.+?)\s*$",
    re.MULTILINE,
)
_H1_HEADING = re.compile(
    r"^#\s+(?:\[([a-z][a-z0-9-]*)\]\s+)?(.+?)\s*$",
    re.MULTILINE,
)


def _safe_file(root: Path, relative_path: str) -> Path:
    lexical = PurePosixPath(relative_path)
    if (
        lexical.is_absolute()
        or ".." in lexical.parts
        or "." in lexical.parts
        or "\\" in relative_path
    ):
        raise SourceStoreError("SOURCE_PATH_UNSAFE")
    root = root.resolve(strict=True)
    candidate = root.joinpath(*lexical.parts)
    current = root
    for part in lexical.parts:
        current = current / part
        if current.exists() and (current.is_symlink() or _is_reparse(current)):
            raise SourceStoreError("SOURCE_REPARSE_POINT_REJECTED")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise SourceStoreError("SOURCE_FILE_NOT_ALLOWED")
    return resolved


def _is_reparse(path: Path) -> bool:
    return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def load_snapshot(root: Path, manifest_path: Path) -> tuple[SourceSnapshotV2, dict[str, str]]:
    """Load manifest and exact UTF-8 files; return snapshot and text map."""

    root = root.resolve(strict=True)
    manifest = SourceSnapshotV2.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    texts: dict[str, str] = {}
    actual_total = 0
    for entry in manifest.entries:
        path = _safe_file(root, entry.relative_path)
        raw = path.read_bytes()
        if len(raw) != entry.size_bytes:
            raise SourceStoreError(f"SOURCE_SIZE_MISMATCH:{entry.source_id}")
        if hashlib.sha256(raw).hexdigest() != entry.raw_sha256:
            raise SourceStoreError(f"SOURCE_HASH_MISMATCH:{entry.source_id}")
        text = raw.decode("utf-8")
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        if hashlib.sha256(normalized.encode("utf-8")).hexdigest() != entry.normalized_sha256:
            raise SourceStoreError(f"SOURCE_NORMALIZED_HASH_MISMATCH:{entry.source_id}")
        texts[entry.source_id] = normalized
        actual_total += len(raw)
    if actual_total != manifest.total_size_bytes:
        raise SourceStoreError("SOURCE_TOTAL_SIZE_MISMATCH")
    return manifest, texts


class SourceStore:
    """Deterministic keyword search and section reads over immutable snapshot."""

    def __init__(self, snapshot: SourceSnapshotV2, texts: dict[str, str]) -> None:
        self.snapshot = snapshot
        self._entries = {entry.source_id: entry for entry in snapshot.entries}
        self._texts = dict(texts)
        if set(self._entries) != set(self._texts):
            raise SourceStoreError("SOURCE_MEMBER_SET_MISMATCH")

    def search(
        self,
        *,
        query: str,
        request: ResearchRequestV2,
        top_k: int = 6,
        candidate_ids: frozenset[str] | None = None,
    ) -> tuple[EvidenceRecord, ...]:
        if not query.strip() or len(query) > 300:
            raise SourceStoreError("SOURCE_QUERY_INVALID")
        if not 1 <= top_k <= 8:
            raise SourceStoreError("SOURCE_TOP_K_INVALID")
        allowed_candidates = {item.candidate_id for item in request.candidates}
        if candidate_ids is not None and (
            not candidate_ids or not candidate_ids <= allowed_candidates
        ):
            raise SourceStoreError("SOURCE_CANDIDATE_FILTER_INVALID")
        terms = tuple(dict.fromkeys(_terms(query)))
        scored: list[tuple[int, str, str, str]] = []
        for entry in self.snapshot.entries:
            if entry.candidate_id is not None and entry.candidate_id not in allowed_candidates:
                continue
            if (
                candidate_ids is not None
                and entry.candidate_id is not None
                and entry.candidate_id not in candidate_ids
            ):
                continue
            text = self._texts[entry.source_id]
            for section_id, title, body in _sections(text):
                # Rank the excerpt we actually return, not invisible text later
                # in a long chapter. Saturate repeated terms so page length
                # cannot overwhelm section/document relevance.
                excerpt = body.strip()[:2400].casefold()
                score = sum(
                    4 * (term in title.casefold())
                    + 2 * (term in entry.title.casefold())
                    + min(2, excerpt.count(term))
                    for term in terms
                )
                if score:
                    scored.append((score, entry.source_id, section_id, title))
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        return tuple(
            self.read(source_id=source_id, section_id=section_id)
            for _, source_id, section_id, _ in scored[:top_k]
        )

    def read(self, *, source_id: str, section_id: str) -> EvidenceRecord:
        entry = self._entries.get(source_id)
        if entry is None:
            raise SourceStoreError("SOURCE_UNKNOWN")
        sections = dict((sid, (title, body)) for sid, title, body in _sections(self._texts[source_id]))
        section = sections.get(section_id)
        if section is None:
            raise SourceStoreError("SOURCE_SECTION_UNKNOWN")
        title, body = section
        evidence_id = f"{source_id}#{section_id}"
        excerpt = body.strip()[:2400]
        return EvidenceRecord(
            evidence_id=evidence_id,
            source_id=source_id,
            candidate_id=entry.candidate_id,
            section_id=section_id,
            locator=f"{entry.relative_path}#[{section_id}]",
            excerpt=excerpt,
            content_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            source_snapshot_id=self.snapshot.snapshot_id,
        )


def _terms(query: str) -> tuple[str, ...]:
    ignored = {
        "the", "and", "for", "with", "from", "that", "what", "official",
        "evidence", "describes", "does", "this", "these", "those", "about",
        "into", "using", "use", "can", "are", "was", "were", "have", "has",
        "will", "would", "should", "could", "may", "might", "not", "only",
        "all", "any", "each", "which", "who", "where", "when", "why", "how",
        "or", "and", "but", "than", "then", "also",
    }
    return tuple(
        term
        for term in re.findall(r"[\w-]{2,}", query.casefold())
        if term not in ignored
    )


def _sections(text: str) -> tuple[tuple[str, str, str], ...]:
    # Most source pages use H2 sections. Some concise official pages only have
    # a single H1 title; make those pages readable without turning parent H1
    # sections into duplicate search hits when H2 sections are present.
    matches = list(_HEADING.finditer(text))
    if not matches:
        matches = list(_H1_HEADING.finditer(text))
    sections: list[tuple[str, str, str]] = []
    used_ids: set[str] = set()
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section_id = match.group(1) or _slug_section(match.group(2), used_ids)
        used_ids.add(section_id)
        sections.append((section_id, match.group(2), text[match.end():end].strip()))
    return tuple(sections)


def _slug_section(title: str, used_ids: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    if not base:
        base = "section"
    if not base[0].isalpha():
        base = "section-" + base
    base = base[:70].rstrip("-") or "section"
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate
