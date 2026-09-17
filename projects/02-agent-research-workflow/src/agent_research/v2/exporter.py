"""Content-addressed, non-overwriting V2 Markdown exporter."""

from __future__ import annotations

import hashlib
import html
import os
import tempfile
from pathlib import Path

from agent_research.v2.contracts import EvidenceRecord, ModelResult, ResearchRequestV2, sha256_json


class ExportError(RuntimeError):
    """Stable export error."""


class V2Exporter:
    def __init__(self, root: Path) -> None:
        self.root = root

    def export(
        self,
        *,
        run_id: str,
        request: ResearchRequestV2,
        report: ModelResult,
        report_revision: int,
        evidence: tuple[EvidenceRecord, ...] = (),
    ) -> tuple[str, str, int]:
        if not self.root.is_absolute() or ".." in self.root.parts:
            raise ExportError("V2_EXPORT_ROOT_UNSAFE")
        if not self.root.parent.exists() or not self.root.parent.is_dir():
            raise ExportError("V2_EXPORT_PARENT_REQUIRED")
        self.root.mkdir(exist_ok=True)
        if self.root.is_symlink() or _is_reparse(self.root):
            raise ExportError("V2_EXPORT_ROOT_REPARSE_POINT")
        # Preserve an already-published legacy artifact after an upgrade/crash.
        # Do not create a second file for the same old approved report.
        legacy_id = sha256_json({
            "run_id": run_id, "report_revision": report_revision,
            "report_hash": report.raw_response_sha256 or sha256_json(report.model_dump(mode="json")),
            "format": "markdown-v2",
        })
        legacy_target = self.root / f"{legacy_id}.md"
        if legacy_target.exists() or legacy_target.is_symlink():
            if legacy_target.is_symlink() or _is_reparse(legacy_target) or not legacy_target.is_file():
                raise ExportError("V2_EXPORT_TARGET_UNSAFE")
            old_content = legacy_target.read_bytes()
            if old_content != _render_legacy_markdown(request=request, report=report):
                raise ExportError("V2_EXPORT_ARTIFACT_CONFLICT")
            return legacy_id, hashlib.sha256(old_content).hexdigest(), len(old_content)
        content = render_markdown(request=request, report=report, evidence=evidence)
        content_hash = hashlib.sha256(content).hexdigest()
        artifact_id = sha256_json(
            {
                "run_id": run_id,
                "report_revision": report_revision,
                "report_hash": report.raw_response_sha256 or sha256_json(report.model_dump(mode="json")),
                "format": "markdown-v2.1",
            }
        )
        target = self.root / f"{artifact_id}.md"
        if target.exists():
            if target.is_symlink() or _is_reparse(target) or not target.is_file():
                raise ExportError("V2_EXPORT_TARGET_UNSAFE")
            existing = target.read_bytes()
            if existing != content:
                raise ExportError("V2_EXPORT_ARTIFACT_CONFLICT")
            return artifact_id, content_hash, len(existing)
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{artifact_id}.", suffix=".tmp", dir=self.root)
        temporary = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if target.read_bytes() != content:
                    raise ExportError("V2_EXPORT_ARTIFACT_CONFLICT")
            except OSError as exc:
                raise ExportError("V2_EXPORT_ATOMIC_PUBLISH_FAILED") from exc
        finally:
            if temporary.exists():
                temporary.unlink()
        return artifact_id, content_hash, len(content)


def _render_legacy_markdown(*, request: ResearchRequestV2, report: ModelResult) -> bytes:
    lines = [
        "# AI 工作流框架选型简报",
        "",
        f"## 研究问题\n{_escape(request.research_question)}",
        "",
        "## 证据范围",
        "本报告的 `supported`/`contradicted` 只基于本次运行实际读取且列出的证据。"
        "`unknown` 只表示本次已读证据未覆盖该单元，不表示整个冻结快照、框架或其文档不具备该能力。",
        "",
        f"## 执行摘要\n{_escape(report.executive_summary)}",
        "",
        f"## 决策状态\n`{report.decision_status.value if report.decision_status else 'unknown'}`",
        "",
        "## 证据矩阵",
        "",
        "| 候选 | 维度 | 状态 | 结论 | 证据 |\n"
        "|---|---|---|---|---|",
    ]
    for cell in report.evidence_cells:
        lines.append(
            f"| {_escape(cell.candidate_id)} | {_escape(cell.dimension_id)} | "
            f"{cell.status} | {_escape(cell.claim)} | "
            f"{_escape(', '.join(cell.evidence_ids) or '无')} |"
        )
    lines.extend(["", "## 限制", ""])
    lines.extend(f"- {_escape(item)}" for item in report.limitations)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _escape(value: str) -> str:
    return html.escape(value, quote=True).replace("|", "\\|")


def _is_reparse(path: Path) -> bool:
    return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def render_markdown(
    *, request: ResearchRequestV2, report: ModelResult,
    evidence: tuple[EvidenceRecord, ...] = (),
) -> bytes:
    """Append review-critical fields without silently changing legacy files."""
    lines = [_render_legacy_markdown(request=request, report=report).decode("utf-8"),
             "## 候选选择", _escape(report.recommendation or "未选择具体候选"),
             "", "## 每格限制与来源定位", "",
             f"快照：{_escape(request.source_snapshot_id)}", ""]
    for cell in report.evidence_cells:
        lines.append(f"- {_escape(cell.candidate_id)}/{_escape(cell.dimension_id)}："
                     f"{_escape(cell.caveat or '未另列限制；不代表没有限制。')}")
    cited = {eid for cell in report.evidence_cells for eid in cell.evidence_ids}
    lines.extend(["", "### 本次已读引用", ""])
    for item in sorted(evidence, key=lambda value: value.evidence_id):
        if item.evidence_id in cited:
            lines.append(f"- {_escape(item.evidence_id)}：{_escape(item.locator)}；"
                         f"章节 SHA256：{item.content_sha256}")
    if cited and not evidence:
        lines.append("未提供定位记录；请按证据ID核对原始快照。")
    lines.extend(["", "导出格式：markdown-v2.1", ""])
    return "\n".join(lines).encode("utf-8")
