"""Offline LangGraph tests for the safe report draft slice."""

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
from agent_research.report_drafting import (
    DeterministicFakeWriter,
    DraftClaim,
    DraftPolicy,
    DraftProposal,
    EvidenceCitationBinder,
    hash_report_draft,
)
from agent_research.runtime_state import RuntimeState, RuntimeStatus
from agent_research.tool_contracts import (
    SearchSourcesArgs,
    ToolCall,
    ToolName,
)
from agent_research.workflow import (
    build_draft_report_graph,
    create_initial_state,
    workflow_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIVACY_EVIDENCE = (
    "atlasflow-security-cost-v1#data-boundary",
    "atlasflow-reliability-v1#checkpointing",
    "procurement-constraints-v1#privacy-policy",
)
PRIVACY_CLAIM_IDS = (
    "atlas-local-data",
    "atlas-durable-checkpoint",
)


def _bundle() -> EvaluationBundle:
    return load_evaluation_bundle(PROJECT_ROOT)


def _case(case_id: str) -> WorkflowCase:
    return next(
        case
        for case in _bundle().evaluation.cases
        if case.case_id == case_id
    )


def _gold_claims(*claim_ids: str) -> tuple[GoldClaim, ...]:
    wanted = set(claim_ids)
    return tuple(
        claim for claim in _bundle().gold.claims if claim.claim_id in wanted
    )


def _proposal() -> DraftProposal:
    return DraftProposal(
        writer_id="deterministic-writer-v1",
        executive_summary=(
            "AtlasFlow matches local data handling and durable recovery needs."
        ),
        claims=tuple(
            DraftClaim.model_validate(claim.model_dump(mode="json"))
            for claim in _gold_claims(*PRIVACY_CLAIM_IDS)
        ),
        recommendation_candidate_id="atlasflow",
        limitations=("Only the fixed synthetic snapshot was evaluated.",),
    )


def _writer(
    proposal: DraftProposal | None = None,
) -> DeterministicFakeWriter:
    return DeterministicFakeWriter(proposal or _proposal())


def _binder() -> EvidenceCitationBinder:
    recommendation_rule = next(
        rule
        for rule in _bundle().gold.recommendation_rules
        if rule.case_id == "privacy-durable-selection"
    )
    return EvidenceCitationBinder(
        sources=_bundle().sources,
        policy=DraftPolicy(
            policy_id="privacy-draft-policy",
            allowed_claims=_gold_claims(*PRIVACY_CLAIM_IDS),
            allowed_recommendations=recommendation_rule.allowed_candidates,
        ),
    )


def _privacy_assessor() -> DeterministicEvidenceAssessor:
    return DeterministicEvidenceAssessor(
        sources=_bundle().sources,
        policy=EvidencePolicy(
            policy_id="privacy-durable-policy",
            requirements=tuple(
                EvidenceRequirement(
                    requirement_id=f"required-proof-{index}",
                    description=f"Required fixed proof number {index}.",
                    acceptable_evidence_sets=((evidence_id,),),
                )
                for index, evidence_id in enumerate(
                    PRIVACY_EVIDENCE,
                    start=1,
                )
            ),
        ),
    )


def _offline_assessor() -> DeterministicEvidenceAssessor:
    return DeterministicEvidenceAssessor(
        sources=_bundle().sources,
        policy=EvidencePolicy(
            policy_id="offline-proof-policy",
            requirements=(
                EvidenceRequirement(
                    requirement_id="deployment-model",
                    description="Deployment model must be present.",
                    acceptable_evidence_sets=(
                        ("cedarflow-overview-v1#deployment-model",),
                    ),
                ),
                EvidenceRequirement(
                    requirement_id="complete-offline-proof",
                    description="Complete offline operation must be explicit.",
                    acceptable_evidence_sets=(),
                ),
            ),
        ),
    )


def _search_call(
    *,
    call_id: str,
    case: WorkflowCase,
    query: str,
    source_types: tuple[str, ...],
    top_k: int,
) -> ToolCall:
    return ToolCall(
        call_id=call_id,
        tool_name=ToolName.SEARCH_SOURCES,
        arguments=SearchSourcesArgs(
            query=query,
            candidate_ids=case.input.candidates,
            source_types=source_types,
            top_k=top_k,
        ),
    )


def _privacy_calls(case: WorkflowCase) -> tuple[ToolCall, ToolCall]:
    first = _search_call(
        call_id="privacy-search",
        case=case,
        query="local data boundary checkpoint recovery privacy policy",
        source_types=(
            "security-and-cost",
            "reliability",
            "constraints",
        ),
        top_k=3,
    )
    return (
        first,
        first.model_copy(update={"call_id": "unused-second-search"}),
    )


def _offline_calls(case: WorkflowCase) -> tuple[ToolCall, ToolCall]:
    return (
        _search_call(
            call_id="offline-search-one",
            case=case,
            query="CedarFlow deployment model offline operation",
            source_types=("overview",),
            top_k=1,
        ),
        _search_call(
            call_id="offline-search-two",
            case=case,
            query="CedarFlow data boundary offline operation",
            source_types=("security-and-cost",),
            top_k=1,
        ),
    )


def _approval(state: RuntimeState) -> dict[str, object]:
    return {
        "schema_version": "requirements-decision-v1",
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "expected_revision": state.human_confirmation_revision,
        "expected_request_hash": state.confirmation_request_hash,
        "action": HumanActionKind.APPROVE.value,
    }


def _snapshot(graph: object, config: dict[str, object]) -> RuntimeState:
    state = graph.get_state(config)  # type: ignore[attr-defined]
    return RuntimeState.model_validate(state.values)


def _run(
    *,
    checkpoint: Path,
    case: WorkflowCase,
    calls: tuple[ToolCall, ToolCall],
    assessor: DeterministicEvidenceAssessor,
    writer: DeterministicFakeWriter,
    binder: EvidenceCitationBinder,
) -> RuntimeState:
    config = workflow_config(f"thread-{case.case_id}")
    executor = DeterministicFakeToolExecutor(
        sources=_bundle().sources,
        outcomes=case.tool_outcomes,
    )
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_draft_report_graph(
            checkpointer=saver,
            tool_calls=calls,
            executor=executor,
            assessor=assessor,
            writer=writer,
            binder=binder,
        )
        graph.invoke(
            create_initial_state(
                run_id=f"run-{case.case_id}",
                thread_id=f"thread-{case.case_id}",
                request=case.input,
            ),
            config,
        )
        waiting = _snapshot(graph, config)
        graph.invoke(Command(resume=_approval(waiting)), config)
        final = _snapshot(graph, config)
        assert graph.get_state(config).next == ()
        return final


def test_sufficient_evidence_creates_bound_structured_draft(
    tmp_path: Path,
) -> None:
    case = _case("privacy-durable-selection")
    writer = _writer()

    final = _run(
        checkpoint=tmp_path / "draft.sqlite3",
        case=case,
        calls=_privacy_calls(case),
        assessor=_privacy_assessor(),
        writer=writer,
        binder=_binder(),
    )

    assert final.status is RuntimeStatus.DRAFTED
    assert final.graph_version == "draft-report-v1"
    assert final.report_revision == 1
    assert final.report_draft is not None
    assert final.report_hash == hash_report_draft(final.report_draft)
    assert final.report_draft.recommendation_candidate_id == "atlasflow"
    assert {
        citation.evidence_id
        for citation in final.report_draft.citations
    } <= set(final.evidence_ids)
    assert final.artifact_id is None
    assert final.review_rounds == 0
    assert writer.write_count == 1

    tampered = final.model_dump(mode="json")
    tampered["report_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="report draft hash mismatch"):
        RuntimeState.model_validate(tampered)


def test_invalid_draft_proposal_fails_without_report(
    tmp_path: Path,
) -> None:
    case = _case("privacy-durable-selection")
    proposal = _proposal()
    invalid_claim = proposal.claims[0].model_copy(
        update={
            "evidence_ids": (
                "atlasflow-overview-v1#workflow-control",
            )
        }
    )
    invalid = proposal.model_copy(
        update={"claims": (invalid_claim, proposal.claims[1])}
    )
    writer = _writer(invalid)

    final = _run(
        checkpoint=tmp_path / "invalid-draft.sqlite3",
        case=case,
        calls=_privacy_calls(case),
        assessor=_privacy_assessor(),
        writer=writer,
        binder=_binder(),
    )

    assert final.status is RuntimeStatus.FAILED
    assert final.errors[-1].code == "invalid-draft-proposal"
    assert final.errors[-1].node.value == "draft_report"
    assert final.report_draft is None
    assert final.report_revision == 0
    assert final.report_hash is None
    assert writer.write_count == 1


def test_insufficient_evidence_never_calls_writer(
    tmp_path: Path,
) -> None:
    case = _case("missing-offline-proof")
    writer = _writer()

    final = _run(
        checkpoint=tmp_path / "insufficient.sqlite3",
        case=case,
        calls=_offline_calls(case),
        assessor=_offline_assessor(),
        writer=writer,
        binder=_binder(),
    )

    assert final.status is RuntimeStatus.FAILED
    assert final.errors[-1].code == "evidence-insufficient"
    assert final.report_draft is None
    assert final.report_hash is None
    assert final.artifact_id is None
    assert writer.write_count == 0


def test_checkpoint_restores_draft_without_runtime_writer_or_binder(
    tmp_path: Path,
) -> None:
    case = _case("privacy-durable-selection")
    checkpoint = tmp_path / "draft-checkpoint.sqlite3"
    calls = _privacy_calls(case)
    final = _run(
        checkpoint=checkpoint,
        case=case,
        calls=calls,
        assessor=_privacy_assessor(),
        writer=_writer(),
        binder=_binder(),
    )
    raw = checkpoint.read_bytes()

    assert b"DeterministicFakeWriter" not in raw
    assert b"EvidenceCitationBinder" not in raw
    assert b"private-vendor-response-body" not in raw

    restored_writer = _writer()
    config = workflow_config(f"thread-{case.case_id}")
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        restored_graph = build_draft_report_graph(
            checkpointer=saver,
            tool_calls=calls,
            executor=DeterministicFakeToolExecutor(
                sources=_bundle().sources,
                outcomes=case.tool_outcomes,
            ),
            assessor=_privacy_assessor(),
            writer=restored_writer,
            binder=_binder(),
        )
        restored = _snapshot(restored_graph, config)

    assert restored == final
    assert restored_writer.write_count == 0
