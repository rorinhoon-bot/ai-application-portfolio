"""V2 report rendering keeps evidence scope visible to readers."""

from __future__ import annotations

import hashlib

from agent_research.v2.contracts import (
    CandidateSpec,
    DimensionSpec,
    EvidenceCell,
    ModelResult,
    ResearchRequestV2,
)
from agent_research.v2.exporter import render_markdown


def test_rendered_report_explains_unknown_scope() -> None:
    request = ResearchRequestV2(
        research_question="Compare two frameworks.",
        audience="student engineering team",
        candidates=(
            CandidateSpec(candidate_id="langgraph", name="LangGraph"),
            CandidateSpec(candidate_id="pydantic-ai", name="PydanticAI"),
        ),
        dimensions=(
            DimensionSpec(dimension_id="state-model", question="State?", weight_percent=34),
            DimensionSpec(dimension_id="human-approval", question="Approval?", weight_percent=33),
            DimensionSpec(dimension_id="recovery", question="Recovery?", weight_percent=33),
        ),
        hard_constraints=("Use supplied evidence.",),
        source_snapshot_id="snapshot-v2-dev",
        model_config_hash=hashlib.sha256(b"scripted-v2").hexdigest(),
        budget_authorization_id="budget-dev",
    )
    cells = tuple(
        EvidenceCell(
            candidate_id=candidate.candidate_id,
            dimension_id=dimension.dimension_id,
            status="unknown",
            claim="本次已读证据未覆盖。",
        )
        for candidate in request.candidates
        for dimension in request.dimensions
    )
    report = ModelResult(
        task="draft",
        provider="scripted",
        model_id="scripted-v2",
        evidence_cells=cells,
        executive_summary="有限简报。",
        decision_status="insufficient_evidence",
        limitations=("未读取的资料不能被否定。",),
    )

    rendered = render_markdown(request=request, report=report).decode("utf-8")

    assert "## 证据范围" in rendered
    assert "本次运行实际读取" in rendered
    assert "不表示整个冻结快照" in rendered


def _export_fixture(tmp_path):
    from test_v2_source_store import _request, _fixture
    from agent_research.v2.source_store import SourceStore
    from agent_research.v2.model_client import ScriptedModelClient
    request = _request()
    snapshot, texts = _fixture(tmp_path)
    evidence = SourceStore(snapshot, texts).search(query="recovery", request=request)
    report = ScriptedModelClient().generate(task="draft", payload={
        "request": request.model_dump(mode="json"),
        "evidence": [item.model_dump(mode="json") for item in evidence],
    })
    return request, report, evidence


def test_new_export_retains_caveat_locator_and_is_idempotent(tmp_path):
    from agent_research.v2.exporter import V2Exporter
    request, report, evidence = _export_fixture(tmp_path)
    cells = list(report.evidence_cells)
    cells[0] = cells[0].model_copy(update={"caveat": "Only this excerpt; no production guarantee."})
    report = report.model_copy(update={"evidence_cells": tuple(cells)})
    exporter = V2Exporter(tmp_path / "artifacts")
    args = dict(run_id="run-export", request=request, report=report, report_revision=1, evidence=evidence)
    first = exporter.export(**args)
    assert exporter.export(**args) == first
    files = list((tmp_path / "artifacts").glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "Only this excerpt; no production guarantee." in text
    assert "未选择具体候选" in text
    assert request.source_snapshot_id in text
    assert evidence[0].locator in text
    assert evidence[0].content_sha256 in text


def test_upgrade_reuses_exact_legacy_artifact_without_second_file(tmp_path):
    from agent_research.v2.exporter import V2Exporter, _render_legacy_markdown, ExportError
    from agent_research.v2.contracts import sha256_json
    import pytest
    request, report, evidence = _export_fixture(tmp_path)
    root = tmp_path / "artifacts"
    root.mkdir()
    legacy_id = sha256_json({
        "run_id": "run-old", "report_revision": 1,
        "report_hash": report.raw_response_sha256 or sha256_json(report.model_dump(mode="json")),
        "format": "markdown-v2",
    })
    target = root / f"{legacy_id}.md"
    original = _render_legacy_markdown(request=request, report=report)
    target.write_bytes(original)
    exporter = V2Exporter(root)
    args = dict(run_id="run-old", request=request, report=report, report_revision=1, evidence=evidence)
    assert exporter.export(**args)[0] == legacy_id
    assert target.read_bytes() == original
    assert len(list(root.glob("*.md"))) == 1
    target.write_bytes(b"corrupted")
    with pytest.raises(ExportError, match="V2_EXPORT_ARTIFACT_CONFLICT"):
        exporter.export(**args)
    assert target.read_bytes() == b"corrupted"
