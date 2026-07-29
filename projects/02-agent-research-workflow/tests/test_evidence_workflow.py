"""Offline graph tests for bounded deterministic evidence assessment."""

from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent_research.data_loader import EvaluationBundle, load_evaluation_bundle
from agent_research.evidence_assessment import (
    DeterministicEvidenceAssessor,
    EvidenceAssessmentStatus,
    EvidencePolicy,
    EvidenceRequirement,
)
from agent_research.fake_tools import DeterministicFakeToolExecutor
from agent_research.models import (
    HumanActionKind,
    ScriptedToolOutcome,
    WorkflowCase,
)
from agent_research.runtime_state import RuntimeState, RuntimeStatus
from agent_research.tool_contracts import (
    CalculateComparisonArgs,
    CandidateScores,
    DimensionScore,
    SearchSourcesArgs,
    ToolCall,
    ToolName,
)
from agent_research.workflow import (
    build_evidence_assessment_graph,
    create_initial_state,
    workflow_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIVACY_EVIDENCE = (
    "atlasflow-security-cost-v1#data-boundary",
    "atlasflow-reliability-v1#checkpointing",
    "procurement-constraints-v1#privacy-policy",
)
COST_EVIDENCE = (
    "atlasflow-security-cost-v1#cost-profile",
    "beaconflow-security-cost-v1#cost-profile",
    "cedarflow-security-cost-v1#cost-profile",
)


def _bundle() -> EvaluationBundle:
    return load_evaluation_bundle(PROJECT_ROOT)


def _case(case_id: str) -> WorkflowCase:
    return next(
        case
        for case in _bundle().evaluation.cases
        if case.case_id == case_id
    )


def _executor(
    outcomes: tuple[ScriptedToolOutcome, ...],
) -> DeterministicFakeToolExecutor:
    return DeterministicFakeToolExecutor(
        sources=_bundle().sources,
        outcomes=outcomes,
    )


def _assessor(policy: EvidencePolicy) -> DeterministicEvidenceAssessor:
    return DeterministicEvidenceAssessor(
        sources=_bundle().sources,
        policy=policy,
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
    executor: DeterministicFakeToolExecutor,
    assessor: DeterministicEvidenceAssessor,
) -> RuntimeState:
    config = workflow_config(f"thread-{case.case_id}")
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_evidence_assessment_graph(
            checkpointer=saver,
            tool_calls=calls,
            executor=executor,
            assessor=assessor,
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


def _cost_call(
    *,
    call_id: str,
    case: WorkflowCase,
    evidence_ids: tuple[str, ...],
) -> ToolCall:
    candidates = tuple(
        CandidateScores(
            candidate_id=candidate_id,
            dimensions=(
                DimensionScore(
                    dimension_id="cost",
                    score=3,
                    evidence_ids=(
                        (evidence_ids[index],)
                        if len(evidence_ids) == len(case.input.candidates)
                        else evidence_ids
                    ),
                ),
            ),
        )
        for index, candidate_id in enumerate(case.input.candidates)
    )
    return ToolCall(
        call_id=call_id,
        tool_name=ToolName.CALCULATE_COMPARISON,
        arguments=CalculateComparisonArgs(
            weights=case.input.dimensions,
            candidates=candidates,
        ),
    )


def _offline_policy() -> EvidencePolicy:
    return EvidencePolicy(
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
    )


def test_missing_offline_proof_retrieves_twice_then_fails(
    tmp_path: Path,
) -> None:
    case = _case("missing-offline-proof")
    calls = (
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
    executor = _executor(case.tool_outcomes)

    final = _run(
        checkpoint=tmp_path / "offline.sqlite3",
        case=case,
        calls=calls,
        executor=executor,
        assessor=_assessor(_offline_policy()),
    )

    assert final.status is RuntimeStatus.FAILED
    assert final.retrieval_rounds == 2
    assert final.tool_attempts == case.expected.max_tool_attempts == 2
    assert set(case.expected.required_evidence_ids) <= set(final.evidence_ids)
    assert final.evidence_gaps == ("complete-offline-proof",)
    assert final.last_evidence_assessment is not None
    assert (
        final.last_evidence_assessment.status
        is EvidenceAssessmentStatus.INSUFFICIENT
    )
    assert final.errors[-1].code == "evidence-insufficient"
    assert final.report_revision == 0
    assert final.report_hash is None
    assert final.artifact_id is None
    assert executor.execution_count == 2


def test_conflicting_cost_evidence_does_not_invent_absolute_price(
    tmp_path: Path,
) -> None:
    case = _case("conflicting-cost-evidence")
    calls = (
        _cost_call(
            call_id="cost-compare-one",
            case=case,
            evidence_ids=COST_EVIDENCE,
        ),
        _cost_call(
            call_id="cost-compare-two",
            case=case,
            evidence_ids=("procurement-constraints-v1#cost-policy",),
        ),
    )
    policy = EvidencePolicy(
        policy_id="absolute-cost-policy",
        requirements=(
            EvidenceRequirement(
                requirement_id="cost-structure",
                description="All candidate cost structures must be present.",
                acceptable_evidence_sets=(COST_EVIDENCE,),
            ),
            EvidenceRequirement(
                requirement_id="all-scale-price-proof",
                description="All-scale absolute price ordering must be explicit.",
                acceptable_evidence_sets=(),
            ),
        ),
    )

    final = _run(
        checkpoint=tmp_path / "cost.sqlite3",
        case=case,
        calls=calls,
        executor=_executor(case.tool_outcomes),
        assessor=_assessor(policy),
    )

    assert final.status is RuntimeStatus.FAILED
    assert final.retrieval_rounds == 2
    assert final.tool_attempts == case.expected.max_tool_attempts == 2
    assert set(case.expected.required_evidence_ids) <= set(final.evidence_ids)
    assert final.evidence_gaps == ("all-scale-price-proof",)
    assert final.errors[-1].code == "evidence-insufficient"
    assert final.artifact_id is None


def test_sufficient_evidence_stops_after_first_round(
    tmp_path: Path,
) -> None:
    case = _case("privacy-durable-selection")
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
    unused = first.model_copy(update={"call_id": "unused-second-search"})
    policy = EvidencePolicy(
        policy_id="privacy-durable-policy",
        requirements=tuple(
            EvidenceRequirement(
                requirement_id=f"required-proof-{index}",
                description=f"Required fixed proof number {index}.",
                acceptable_evidence_sets=((evidence_id,),),
            )
            for index, evidence_id in enumerate(PRIVACY_EVIDENCE, start=1)
        ),
    )
    executor = _executor(case.tool_outcomes)

    final = _run(
        checkpoint=tmp_path / "sufficient.sqlite3",
        case=case,
        calls=(first, unused),
        executor=executor,
        assessor=_assessor(policy),
    )

    assert final.status is RuntimeStatus.EVIDENCE_SUFFICIENT
    assert final.retrieval_rounds == 1
    assert final.tool_attempts == case.expected.max_tool_attempts == 1
    assert final.evidence_gaps == ()
    assert set(final.evidence_ids) == set(PRIVACY_EVIDENCE)
    assert final.report_hash is None
    assert final.artifact_id is None
    assert executor.execution_count == 1


def test_checkpoint_restores_final_assessment_without_runtime_objects(
    tmp_path: Path,
) -> None:
    case = _case("missing-offline-proof")
    checkpoint = tmp_path / "assessment-checkpoint.sqlite3"
    calls = (
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
    policy = _offline_policy()
    final = _run(
        checkpoint=checkpoint,
        case=case,
        calls=calls,
        executor=_executor(case.tool_outcomes),
        assessor=_assessor(policy),
    )
    raw = checkpoint.read_bytes()

    assert b"DeterministicEvidenceAssessor" not in raw
    assert b"DeterministicFakeToolExecutor" not in raw
    assert b"private-vendor-response-body" not in raw

    restored_executor = _executor(case.tool_outcomes)
    config = workflow_config(f"thread-{case.case_id}")
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        restored_graph = build_evidence_assessment_graph(
            checkpointer=saver,
            tool_calls=calls,
            executor=restored_executor,
            assessor=_assessor(policy),
        )
        restored = _snapshot(restored_graph, config)

    assert restored == final
    assert restored_executor.execution_count == 0
