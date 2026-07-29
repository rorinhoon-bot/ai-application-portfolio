"""Offline tests for deterministic safe Markdown export."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import ValidationError

from agent_research.data_loader import EvaluationBundle, load_evaluation_bundle
from agent_research.evidence_assessment import (
    DeterministicEvidenceAssessor,
    EvidencePolicy,
    EvidenceRequirement,
)
from agent_research.fake_tools import DeterministicFakeToolExecutor
from agent_research.models import (
    GoldClaim,
    HumanActionKind,
    WorkflowCase,
)
from agent_research.report_approval import DeterministicHumanReportReviser
from agent_research.report_drafting import (
    DeterministicFakeWriter,
    DraftClaim,
    DraftPolicy,
    DraftProposal,
    EvidenceCitationBinder,
    ReportDraft,
    hash_report_draft,
)
from agent_research.report_export import (
    ExportConflictError,
    ExportOutcome,
    ExportPathError,
    ExportRequest,
    ExportWriteError,
    SafeMarkdownExporter,
    compute_artifact_id,
    render_markdown,
)
from agent_research.report_review import (
    DeterministicDraftReviser,
    DeterministicReportReviewer,
    ReviewPolicy,
)
from agent_research.runtime_state import RuntimeState, RuntimeStatus
from agent_research.tool_contracts import (
    SearchSourcesArgs,
    ToolCall,
    ToolName,
)
from agent_research.workflow import (
    build_report_export_graph,
    create_initial_state,
    export_report,
    workflow_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESUME_EVIDENCE = (
    "atlasflow-reliability-v1#checkpointing",
    "atlasflow-reliability-v1#idempotency",
)


def _bundle() -> EvaluationBundle:
    return load_evaluation_bundle(PROJECT_ROOT)


def _case() -> WorkflowCase:
    return next(
        case
        for case in _bundle().evaluation.cases
        if case.case_id == "checkpoint-resume-export"
    )


def _gold_claim() -> GoldClaim:
    return next(
        claim
        for claim in _bundle().gold.claims
        if claim.claim_id == "atlas-durable-checkpoint"
    )


def _proposal() -> DraftProposal:
    claim = _gold_claim()
    return DraftProposal(
        writer_id="deterministic-writer-v1",
        executive_summary=(
            "AtlasFlow supports the fixed local checkpoint requirement."
        ),
        claims=(
            DraftClaim.model_validate(claim.model_dump(mode="json")),
        ),
        recommendation_candidate_id="atlasflow",
        limitations=(
            "The fixed gold set has no separate idempotency report claim.",
        ),
    )


def _binder() -> EvidenceCitationBinder:
    return EvidenceCitationBinder(
        sources=_bundle().sources,
        policy=DraftPolicy(
            policy_id="resume-export-draft-policy",
            allowed_claims=(_gold_claim(),),
            allowed_recommendations=("atlasflow",),
        ),
    )


def _report() -> ReportDraft:
    return _binder().bind(
        proposal=_proposal(),
        confirmed_requirements=_case().input,
        available_evidence_ids=RESUME_EVIDENCE,
        revision=1,
    )


def _request(report: ReportDraft | None = None) -> ExportRequest:
    selected = report or _report()
    return ExportRequest(
        run_id="run-checkpoint-resume-export",
        thread_id="thread-checkpoint-resume-export",
        approved_report_revision=selected.revision,
        approved_report_hash=hash_report_draft(selected),
        report=selected,
    )


def _assessor() -> DeterministicEvidenceAssessor:
    return DeterministicEvidenceAssessor(
        sources=_bundle().sources,
        policy=EvidencePolicy(
            policy_id="resume-export-evidence-policy",
            requirements=tuple(
                EvidenceRequirement(
                    requirement_id=f"resume-proof-{index}",
                    description=f"Required resume proof {index}.",
                    acceptable_evidence_sets=((evidence_id,),),
                )
                for index, evidence_id in enumerate(
                    RESUME_EVIDENCE,
                    start=1,
                )
            ),
        ),
    )


def _calls() -> tuple[ToolCall, ToolCall]:
    case = _case()
    first = ToolCall(
        call_id="resume-search",
        tool_name=ToolName.SEARCH_SOURCES,
        arguments=SearchSourcesArgs(
            query="AtlasFlow checkpoint recovery idempotency",
            candidate_ids=case.input.candidates,
            source_types=("reliability",),
            top_k=2,
        ),
    )
    return (
        first,
        first.model_copy(update={"call_id": "unused-resume-search"}),
    )


def _review_policy() -> ReviewPolicy:
    return ReviewPolicy(
        policy_id="resume-export-review-policy",
        required_candidate_ids=("atlasflow",),
        required_dimension_ids=("reliability",),
        forbidden_statements=_bundle().gold.forbidden_claims,
    )


def _build_export_graph(
    *,
    saver: SqliteSaver,
    exporter: SafeMarkdownExporter,
    interrupt_before_export: bool,
):
    case = _case()
    return build_report_export_graph(
        checkpointer=saver,
        tool_calls=_calls(),
        executor=DeterministicFakeToolExecutor(
            sources=_bundle().sources,
            outcomes=case.tool_outcomes,
        ),
        assessor=_assessor(),
        writer=DeterministicFakeWriter(_proposal()),
        binder=_binder(),
        reviewer=DeterministicReportReviewer(_review_policy()),
        reviser=DeterministicDraftReviser((_proposal(),)),
        human_reviser=DeterministicHumanReportReviser((_proposal(),)),
        exporter=exporter,
        interrupt_before_export=interrupt_before_export,
    )


def _snapshot(graph: object, config: dict[str, object]) -> RuntimeState:
    snapshot = graph.get_state(config)  # type: ignore[attr-defined]
    return RuntimeState.model_validate(snapshot.values)


def _requirements_approval(state: RuntimeState) -> dict[str, object]:
    return {
        "schema_version": "requirements-decision-v1",
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "expected_revision": state.human_confirmation_revision,
        "expected_request_hash": state.confirmation_request_hash,
        "action": HumanActionKind.APPROVE.value,
    }


def _report_decision(
    state: RuntimeState,
    action: HumanActionKind,
) -> dict[str, object]:
    return {
        "schema_version": "report-decision-v1",
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "expected_confirmation_revision": (
            state.report_confirmation_revision
        ),
        "expected_report_revision": state.report_revision,
        "expected_report_hash": state.report_hash,
        "action": action.value,
    }


def test_export_request_is_strict_and_bound_to_report() -> None:
    request = _request()
    payload = request.model_dump(mode="json")
    payload["approved_report_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="report hash mismatch"):
        ExportRequest.model_validate(payload)

    payload = request.model_dump(mode="json")
    payload["output_path"] = r"C:\untrusted\report.md"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExportRequest.model_validate(payload)


def test_artifact_identity_is_deterministic_and_revision_bound() -> None:
    request = _request()
    assert compute_artifact_id(request) == compute_artifact_id(request)

    next_revision_report = request.report.model_copy(update={"revision": 2})
    next_request = _request(next_revision_report)
    assert compute_artifact_id(next_request) != compute_artifact_id(request)


def test_markdown_export_creates_once_then_returns_unchanged(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    exporter = SafeMarkdownExporter(root)
    request = _request()

    created = exporter.export(request)
    unchanged = exporter.export(request)
    files = tuple(root.glob("*.md"))

    assert created.outcome is ExportOutcome.CREATED
    assert unchanged.outcome is ExportOutcome.UNCHANGED
    assert created.artifact == unchanged.artifact
    assert files == (root / created.artifact.relative_path,)
    assert files[0].read_bytes() == render_markdown(request)
    assert tuple(root.glob("*.tmp")) == ()
    assert exporter.export_count == 2
    assert exporter.created_count == 1


def test_same_artifact_id_with_different_bytes_fails_without_overwrite(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    exporter = SafeMarkdownExporter(root)
    request = _request()
    created = exporter.export(request)
    target = root / created.artifact.relative_path
    conflicting = b"existing-different-content\n"
    target.write_bytes(conflicting)

    with pytest.raises(
        ExportConflictError,
        match="EXPORT_ARTIFACT_CONFLICT",
    ):
        exporter.export(request)

    assert target.read_bytes() == conflicting
    assert exporter.created_count == 1


def test_export_rejects_relative_or_reparse_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        ExportPathError,
        match="EXPORT_ROOT_MUST_BE_ABSOLUTE_AND_NORMALIZED",
    ):
        SafeMarkdownExporter(Path("relative-artifacts")).export(_request())

    nested = tmp_path / "missing-parent" / "artifacts"
    with pytest.raises(
        ExportPathError,
        match="EXPORT_ROOT_PARENT_DIRECTORY_REQUIRED",
    ):
        SafeMarkdownExporter(nested).export(_request())
    assert not nested.parent.exists()

    root = tmp_path / "reparse-artifacts"
    root.mkdir()
    monkeypatch.setattr(
        "agent_research.report_export._has_reparse_point",
        lambda path: path == root,
    )
    with pytest.raises(
        ExportPathError,
        match="EXPORT_ROOT_REPARSE_POINT_REJECTED",
    ):
        SafeMarkdownExporter(root).export(_request())


def test_atomic_publish_failure_leaves_no_partial_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "atomic-failure"

    def fail_link(source: Path, target: Path) -> None:
        raise PermissionError("blocked for deterministic test")

    monkeypatch.setattr(
        "agent_research.report_export.os.link",
        fail_link,
    )

    with pytest.raises(
        ExportWriteError,
        match="EXPORT_ATOMIC_PUBLISH_FAILED",
    ):
        SafeMarkdownExporter(root).export(_request())

    assert tuple(root.iterdir()) == ()


def test_export_rejects_non_file_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "non-file-target"
    root.mkdir()
    request = _request()
    target = root / f"{compute_artifact_id(request)}.md"
    target.mkdir()

    with pytest.raises(
        ExportPathError,
        match="EXPORT_TARGET_REGULAR_FILE_REQUIRED",
    ):
        SafeMarkdownExporter(root).export(request)

    assert target.is_dir()


def test_renderer_escapes_active_markdown_and_html() -> None:
    payload = _report().model_dump(mode="json")
    payload["executive_summary"] = "<script>alert(1)</script> **bold**"
    report = ReportDraft.model_validate(payload)
    rendered = render_markdown(_request(report)).decode("utf-8")

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "\\*\\*bold\\*\\*" in rendered


def test_export_node_rejects_unapproved_state_without_creating_root(
    tmp_path: Path,
) -> None:
    state = RuntimeState.model_validate(
        create_initial_state(
            run_id="run-unapproved-export",
            thread_id="thread-unapproved-export",
            request=_case().input,
        )
    )
    root = tmp_path / "must-not-exist"

    with pytest.raises(ValueError, match="EXPORT_REQUIRES_APPROVED_REPORT"):
        export_report(state, exporter=SafeMarkdownExporter(root))

    assert not root.exists()


def test_checkpoint_recovery_replays_export_without_second_artifact(
    tmp_path: Path,
) -> None:
    case = _case()
    checkpoint = tmp_path / "export-checkpoint.sqlite3"
    root = tmp_path / "private-export-root"
    config = workflow_config("thread-checkpoint-resume-export")

    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = _build_export_graph(
            saver=saver,
            exporter=SafeMarkdownExporter(root),
            interrupt_before_export=True,
        )
        graph.invoke(
            create_initial_state(
                run_id="run-checkpoint-resume-export",
                thread_id="thread-checkpoint-resume-export",
                request=case.input,
            ),
            config,
        )
        requirements_wait = _snapshot(graph, config)
        graph.invoke(
            Command(resume=_requirements_approval(requirements_wait)),
            config,
        )
        report_wait = _snapshot(graph, config)
        graph.invoke(
            Command(
                resume=_report_decision(
                    report_wait,
                    HumanActionKind.APPROVE,
                )
            ),
            config,
        )
        export_ready = _snapshot(graph, config)

        assert export_ready.status is RuntimeStatus.EXPORT_READY
        assert export_ready.current_node.value == "export_report"
        assert graph.get_state(config).next == ("export_report",)
        assert export_ready.artifact_id is None

    request = ExportRequest(
        run_id=export_ready.run_id,
        thread_id=export_ready.thread_id,
        source_snapshot_id=export_ready.source_snapshot_id,
        approved_report_revision=export_ready.approved_report_revision,
        approved_report_hash=export_ready.approved_report_hash,
        report=export_ready.report_draft,
    )
    crash_window_exporter = SafeMarkdownExporter(root)
    first = crash_window_exporter.export(request)
    assert first.outcome is ExportOutcome.CREATED

    fresh_exporter = SafeMarkdownExporter(root)
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        restored_graph = _build_export_graph(
            saver=saver,
            exporter=fresh_exporter,
            interrupt_before_export=True,
        )
        restored = _snapshot(restored_graph, config)
        assert restored == export_ready

        restored_graph.invoke(None, config)
        final = _snapshot(restored_graph, config)

        assert restored_graph.get_state(config).next == ()

    assert final.status is RuntimeStatus.COMPLETED
    assert final.last_export_outcome is ExportOutcome.UNCHANGED
    assert final.artifact_record is not None
    assert final.artifact_id == first.artifact.artifact_id
    assert final.idempotency_key == first.artifact.idempotency_key
    assert len(tuple(root.glob("*.md"))) == case.expected.artifact_count == 1
    assert tuple(root.glob("*.tmp")) == ()
    assert crash_window_exporter.export_count == 1
    assert crash_window_exporter.created_count == 1
    assert fresh_exporter.export_count == 1
    assert fresh_exporter.created_count == 0

    raw = checkpoint.read_bytes().lower()
    for forbidden in (
        b"safemarkdownexporter",
        b"private-export-root",
        b"authorization: bearer",
        b"api_key=",
        b"cookie:",
        b"private-vendor-response-body",
    ):
        assert forbidden not in raw

    tampered = final.model_dump(mode="json")
    tampered["artifact_id"] = "f" * 64
    with pytest.raises(
        ValidationError,
        match="artifact record does not match runtime state",
    ):
        RuntimeState.model_validate(tampered)

    tampered_content = final.model_dump(mode="json")
    tampered_content["artifact_record"]["content_sha256"] = "f" * 64
    with pytest.raises(
        ValidationError,
        match="artifact record does not match deterministic export",
    ):
        RuntimeState.model_validate(tampered_content)


def test_export_conflict_becomes_stable_failure_without_overwrite(
    tmp_path: Path,
) -> None:
    case = _case()
    root = tmp_path / "conflict-root"
    config = workflow_config("thread-export-conflict")
    with SqliteSaver.from_conn_string(
        str(tmp_path / "export-conflict.sqlite3")
    ) as saver:
        graph = _build_export_graph(
            saver=saver,
            exporter=SafeMarkdownExporter(root),
            interrupt_before_export=True,
        )
        graph.invoke(
            create_initial_state(
                run_id="run-export-conflict",
                thread_id="thread-export-conflict",
                request=case.input,
            ),
            config,
        )
        requirements_wait = _snapshot(graph, config)
        graph.invoke(
            Command(resume=_requirements_approval(requirements_wait)),
            config,
        )
        report_wait = _snapshot(graph, config)
        graph.invoke(
            Command(
                resume=_report_decision(
                    report_wait,
                    HumanActionKind.APPROVE,
                )
            ),
            config,
        )
        export_ready = _snapshot(graph, config)
        request = ExportRequest(
            run_id=export_ready.run_id,
            thread_id=export_ready.thread_id,
            source_snapshot_id=export_ready.source_snapshot_id,
            approved_report_revision=export_ready.approved_report_revision,
            approved_report_hash=export_ready.approved_report_hash,
            report=export_ready.report_draft,
        )
        artifact_id = compute_artifact_id(request)
        root.mkdir()
        target = root / f"{artifact_id}.md"
        conflicting = b"do-not-overwrite\n"
        target.write_bytes(conflicting)

        graph.invoke(None, config)
        final = _snapshot(graph, config)

    assert final.status is RuntimeStatus.FAILED
    assert final.errors[-1].code == "export-artifact-conflict"
    assert final.artifact_id is None
    assert target.read_bytes() == conflicting


def test_report_rejection_never_calls_exporter(
    tmp_path: Path,
) -> None:
    case = _case()
    root = tmp_path / "rejected-root"
    exporter = SafeMarkdownExporter(root)
    config = workflow_config("thread-export-rejected")
    with SqliteSaver.from_conn_string(
        str(tmp_path / "export-rejected.sqlite3")
    ) as saver:
        graph = _build_export_graph(
            saver=saver,
            exporter=exporter,
            interrupt_before_export=False,
        )
        graph.invoke(
            create_initial_state(
                run_id="run-export-rejected",
                thread_id="thread-export-rejected",
                request=case.input,
            ),
            config,
        )
        requirements_wait = _snapshot(graph, config)
        graph.invoke(
            Command(resume=_requirements_approval(requirements_wait)),
            config,
        )
        report_wait = _snapshot(graph, config)
        graph.invoke(
            Command(
                resume=_report_decision(
                    report_wait,
                    HumanActionKind.REJECT,
                )
            ),
            config,
        )
        final = _snapshot(graph, config)

    assert final.status is RuntimeStatus.REPORT_REJECTED
    assert exporter.export_count == 0
    assert not root.exists()
