"""Deterministic Markdown rendering and safe idempotent local export."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from agent_research.models import Identifier, Sha256, StrictModel
from agent_research.report_drafting import (
    MAX_REPORT_REVISIONS,
    ReportDraft,
    hash_report_draft,
)
from agent_research.tool_contracts import (
    SOURCE_SNAPSHOT_V1,
    SourceSnapshotIdV1,
)


MAX_ARTIFACT_BYTES = 131_072
REPARSE_POINT_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
ArtifactFilename = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}\.md$"),
]


class ExportOutcome(StrEnum):
    CREATED = "CREATED"
    UNCHANGED = "UNCHANGED"


class ExportRequest(StrictModel):
    """Approved report values accepted by the file boundary."""

    schema_version: Literal["export-request-v1"] = "export-request-v1"
    run_id: Identifier
    thread_id: Identifier
    source_snapshot_id: SourceSnapshotIdV1 = SOURCE_SNAPSHOT_V1
    approved_report_revision: Annotated[
        int,
        Field(ge=1, le=MAX_REPORT_REVISIONS),
    ]
    approved_report_hash: Sha256
    format: Literal["markdown"] = "markdown"
    report: ReportDraft

    @model_validator(mode="after")
    def validate_approved_report(self) -> Self:
        if self.report.revision != self.approved_report_revision:
            raise ValueError("export request report revision mismatch")
        if hash_report_draft(self.report) != self.approved_report_hash:
            raise ValueError("export request report hash mismatch")
        if self.report.source_snapshot_id != self.source_snapshot_id:
            raise ValueError("export request source snapshot mismatch")
        return self


class ArtifactRecord(StrictModel):
    """Checkpoint-safe metadata for one published file."""

    schema_version: Literal["artifact-record-v1"] = "artifact-record-v1"
    artifact_id: Sha256
    idempotency_key: Sha256
    format: Literal["markdown"] = "markdown"
    relative_path: ArtifactFilename
    content_sha256: Sha256
    size_bytes: Annotated[int, Field(gt=0, le=MAX_ARTIFACT_BYTES)]
    report_revision: Annotated[
        int,
        Field(ge=1, le=MAX_REPORT_REVISIONS),
    ]
    report_hash: Sha256
    source_snapshot_id: SourceSnapshotIdV1 = SOURCE_SNAPSHOT_V1

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.relative_path != f"{self.artifact_id}.md":
            raise ValueError("artifact path must derive from artifact_id")
        if self.artifact_id != self.idempotency_key:
            raise ValueError("artifact ID and idempotency key must match")
        return self


class ExportResult(StrictModel):
    schema_version: Literal["export-result-v1"] = "export-result-v1"
    outcome: ExportOutcome
    artifact: ArtifactRecord


class ExportPathError(ValueError):
    """Raised when the injected export root or target is unsafe."""


class ExportConflictError(ValueError):
    """Raised when the same artifact ID already has different bytes."""


class ExportWriteError(ValueError):
    """Raised when a safe atomic publication cannot finish."""


def compute_artifact_id(request: ExportRequest) -> str:
    """Bind identity to approved report and fixed output format."""

    canonical = json.dumps(
        {
            "schema_version": "artifact-identity-v1",
            "run_id": request.run_id,
            "approved_report_revision": request.approved_report_revision,
            "approved_report_hash": request.approved_report_hash,
            "format": request.format,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _escape_markdown_text(value: str) -> str:
    escaped = value.replace("&", "&amp;")
    escaped = escaped.replace("<", "&lt;").replace(">", "&gt;")
    for marker in (
        "\\",
        "`",
        "*",
        "_",
        "{",
        "}",
        "[",
        "]",
        "(",
        ")",
        "#",
        "+",
        "-",
        "!",
        "|",
    ):
        escaped = escaped.replace(marker, f"\\{marker}")
    return escaped


def render_markdown(request: ExportRequest) -> bytes:
    """Render one deterministic UTF-8 Markdown artifact."""

    report = request.report
    lines = [
        "# AI 应用技术选型研究报告",
        "",
        f"- Run ID: `{request.run_id}`",
        f"- Thread ID: `{request.thread_id}`",
        f"- Report revision: `{request.approved_report_revision}`",
        f"- Report hash: `{request.approved_report_hash}`",
        f"- Source snapshot: `{request.source_snapshot_id}`",
        "",
        "## 研究问题",
        "",
        _escape_markdown_text(report.research_question),
        "",
        "## 执行摘要",
        "",
        _escape_markdown_text(report.executive_summary),
        "",
        "## 推荐方案",
        "",
        f"`{report.recommendation_candidate_id}`",
        "",
        "## 证据声明",
        "",
    ]
    for claim in report.claims:
        lines.extend(
            (
                f"### `{claim.claim_id}`",
                "",
                f"- Candidate: `{claim.candidate_id}`",
                f"- Dimension: `{claim.dimension_id}`",
                f"- Strength: `{claim.strength}`",
                "",
                _escape_markdown_text(claim.statement),
                "",
                "- Evidence:",
                *(
                    f"  - `{evidence_id}`"
                    for evidence_id in claim.evidence_ids
                ),
                "",
            )
        )

    lines.extend(("## 限制", ""))
    if report.limitations:
        lines.extend(
            f"- {_escape_markdown_text(item)}"
            for item in report.limitations
        )
    else:
        lines.append("- 无额外限制。")

    lines.extend(("", "## 引用", ""))
    for citation in report.citations:
        lines.extend(
            (
                f"### `{citation.evidence_id}`",
                "",
                f"- Source: `{citation.source_id}`",
                f"- Section: `{citation.section_id}`",
                (
                    "- Title: "
                    f"{_escape_markdown_text(citation.source_title)}"
                ),
                f"- Version: `{citation.source_version}`",
                f"- SHA-256: `{citation.source_sha256}`",
                "",
            )
        )
    rendered = ("\n".join(lines).rstrip() + "\n").encode("utf-8")
    if not 0 < len(rendered) <= MAX_ARTIFACT_BYTES:
        raise ExportWriteError("EXPORT_RENDERED_SIZE_OUT_OF_RANGE")
    return rendered


def _has_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & REPARSE_POINT_FLAG)


def _is_link_or_reparse(path: Path) -> bool:
    return path.is_symlink() or _has_reparse_point(path)


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


class SafeMarkdownExporter:
    """Publish one content-checked file below an injected allowlist root."""

    def __init__(self, export_root: Path) -> None:
        self.export_root = export_root
        self.export_count = 0
        self.created_count = 0

    def export(self, request: ExportRequest) -> ExportResult:
        self.export_count += 1
        try:
            return self._export_once(request)
        except (
            ExportConflictError,
            ExportPathError,
            ExportWriteError,
        ):
            raise
        except OSError as exc:
            raise ExportWriteError("EXPORT_FILESYSTEM_OPERATION_FAILED") from exc

    def _export_once(self, request: ExportRequest) -> ExportResult:
        root = self._prepare_root()
        artifact_id = compute_artifact_id(request)
        relative_path = f"{artifact_id}.md"
        target = root / relative_path
        rendered = render_markdown(request)
        content_hash = hashlib.sha256(rendered).hexdigest()
        artifact = ArtifactRecord(
            artifact_id=artifact_id,
            idempotency_key=artifact_id,
            relative_path=relative_path,
            content_sha256=content_hash,
            size_bytes=len(rendered),
            report_revision=request.approved_report_revision,
            report_hash=request.approved_report_hash,
        )

        if _lexists(target):
            self._verify_existing(target, rendered)
            return ExportResult(
                outcome=ExportOutcome.UNCHANGED,
                artifact=artifact,
            )

        temp_path: Path | None = None
        try:
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{artifact_id}.",
                suffix=".tmp",
                dir=root,
            )
            temp_path = Path(temp_name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(rendered)
                stream.flush()
                os.fsync(stream.fileno())

            if (
                temp_path.parent != root
                or _is_link_or_reparse(temp_path)
                or not temp_path.is_file()
            ):
                raise ExportPathError("EXPORT_TEMP_PATH_UNSAFE")

            try:
                os.link(temp_path, target)
            except FileExistsError:
                self._verify_existing(target, rendered)
                return ExportResult(
                    outcome=ExportOutcome.UNCHANGED,
                    artifact=artifact,
                )
            except OSError as exc:
                raise ExportWriteError(
                    "EXPORT_ATOMIC_PUBLISH_FAILED"
                ) from exc

            self._verify_existing(target, rendered)
            self.created_count += 1
            return ExportResult(
                outcome=ExportOutcome.CREATED,
                artifact=artifact,
            )
        finally:
            if temp_path is not None and _lexists(temp_path):
                temp_path.unlink()

    def _prepare_root(self) -> Path:
        root = self.export_root
        if not root.is_absolute() or ".." in root.parts:
            raise ExportPathError("EXPORT_ROOT_MUST_BE_ABSOLUTE_AND_NORMALIZED")

        current = root
        while True:
            if _lexists(current) and _is_link_or_reparse(current):
                raise ExportPathError("EXPORT_ROOT_REPARSE_POINT_REJECTED")
            if current.parent == current:
                break
            current = current.parent

        if (
            not _lexists(root.parent)
            or _is_link_or_reparse(root.parent)
            or not root.parent.is_dir()
        ):
            raise ExportPathError("EXPORT_ROOT_PARENT_DIRECTORY_REQUIRED")
        if _lexists(root) and not root.is_dir():
            raise ExportPathError("EXPORT_ROOT_DIRECTORY_REQUIRED")
        try:
            root.mkdir(exist_ok=True)
        except OSError as exc:
            raise ExportWriteError("EXPORT_ROOT_CREATE_FAILED") from exc
        if _is_link_or_reparse(root) or not root.is_dir():
            raise ExportPathError("EXPORT_ROOT_DIRECTORY_REQUIRED")
        if root.resolve(strict=True) != root:
            raise ExportPathError("EXPORT_ROOT_NOT_NORMALIZED")
        return root

    @staticmethod
    def _verify_existing(target: Path, expected: bytes) -> None:
        if _is_link_or_reparse(target) or not target.is_file():
            raise ExportPathError("EXPORT_TARGET_REGULAR_FILE_REQUIRED")
        try:
            if target.stat().st_size > MAX_ARTIFACT_BYTES:
                raise ExportConflictError("EXPORT_ARTIFACT_CONFLICT")
            actual = target.read_bytes()
        except OSError as exc:
            raise ExportWriteError("EXPORT_TARGET_READ_FAILED") from exc
        if actual != expected:
            raise ExportConflictError("EXPORT_ARTIFACT_CONFLICT")
