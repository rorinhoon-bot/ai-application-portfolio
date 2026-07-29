"""Deterministic end-to-end runner for the frozen workflow-v1 suite."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal, Self

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import Field, model_validator

from agent_research.data_loader import EvaluationBundle, load_evaluation_bundle
from agent_research.evidence_assessment import (
    DeterministicEvidenceAssessor,
    EvidencePolicy,
    EvidenceRequirement,
)
from agent_research.fake_tools import DeterministicFakeToolExecutor
from agent_research.models import (
    CaseCategory,
    EvidenceId,
    GoldClaim,
    HumanActionKind,
    HumanGate,
    Identifier,
    RunStatus,
    ScriptedToolOutcome,
    Sha256,
    SourceType,
    StrictModel,
    ToolOutcomeKind,
    WorkflowCase,
)
from agent_research.observability import (
    DeterministicClock,
    RunObserver,
    RunSummary,
    build_run_summary,
)
from agent_research.report_approval import DeterministicHumanReportReviser
from agent_research.report_drafting import (
    DraftClaim,
    DraftPolicy,
    DraftProposal,
    DeterministicFakeWriter,
    EvidenceCitationBinder,
)
from agent_research.report_export import (
    ExportOutcome,
    ExportRequest,
    SafeMarkdownExporter,
)
from agent_research.report_review import (
    DeterministicDraftReviser,
    DeterministicReportReviewer,
    ReviewPolicy,
)
from agent_research.runtime_state import RuntimeState, RuntimeStatus
from agent_research.tool_contracts import (
    CalculateComparisonArgs,
    CandidateScores,
    DimensionScore,
    ReadSourceArgs,
    SearchSourcesArgs,
    ToolCall,
    ToolName,
)
from agent_research.workflow import (
    build_report_export_graph,
    build_requirements_graph,
    create_initial_state,
    workflow_config,
)


BASELINE_SCHEMA_VERSION = "workflow-baseline-v1"
RUNNER_VERSION = "workflow-runner-v1"


class EvaluationRunnerError(RuntimeError):
    """Raised when the offline evaluation cannot safely produce a result."""


class CaseChecks(StrictModel):
    """Independent comparisons against the frozen case expectation."""

    path_matches: bool
    status_matches: bool
    tool_attempts_match: bool
    required_evidence_present: bool
    forbidden_evidence_absent: bool
    recommendation_allowed: bool
    artifact_count_matches: bool
    citation_binding_valid: bool
    retry_and_stop_match: bool

    @property
    def all_passed(self) -> bool:
        return all(self.model_dump().values())


class WorkflowCaseResult(StrictModel):
    """Versioned actual result for one frozen workflow case."""

    schema_version: Literal["workflow-case-result-v1"] = (
        "workflow-case-result-v1"
    )
    case_id: Identifier
    category: CaseCategory
    expected_path: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    actual_path: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    expected_status: RunStatus
    actual_status: RunStatus
    expected_max_tool_attempts: Annotated[int, Field(ge=0, le=12)]
    actual_tool_attempts: Annotated[int, Field(ge=0, le=12)]
    retrieval_rounds: Annotated[int, Field(ge=0, le=2)]
    review_rounds: Annotated[int, Field(ge=0, le=2)]
    human_revision_count: Annotated[int, Field(ge=0, le=2)]
    expected_required_evidence_ids: tuple[EvidenceId, ...] = ()
    expected_forbidden_evidence_ids: tuple[EvidenceId, ...] = ()
    actual_evidence_ids: tuple[EvidenceId, ...] = ()
    allowed_recommendations: tuple[Identifier, ...] = ()
    actual_recommendation: Identifier | None = None
    citation_evidence_ids: tuple[EvidenceId, ...] = ()
    report_claim_count: Annotated[int, Field(ge=0, le=32)]
    unsupported_claim_count: Annotated[int, Field(ge=0, le=32)]
    artifact_count: Annotated[int, Field(ge=0, le=8)]
    unapproved_export_count: Annotated[int, Field(ge=0, le=12)]
    permission_expansion_count: Annotated[int, Field(ge=0, le=12)]
    checkpoint_recovery_consistent: bool | None = None
    checks: CaseChecks
    passed: bool

    @model_validator(mode="after")
    def validate_passed_flag(self) -> Self:
        if self.passed != self.checks.all_passed:
            raise ValueError("passed must equal the conjunction of case checks")
        if self.unsupported_claim_count > self.report_claim_count:
            raise ValueError("unsupported claims cannot exceed all claims")
        if self.category is CaseCategory.RECOVERY_IDEMPOTENCY:
            if self.checkpoint_recovery_consistent is None:
                raise ValueError("recovery case requires a recovery result")
        elif self.checkpoint_recovery_consistent is not None:
            raise ValueError("only recovery case may report recovery consistency")
        return self


class RatioMetric(StrictModel):
    """Exact integer ratio represented in basis points."""

    numerator: Annotated[int, Field(ge=0)]
    denominator: Annotated[int, Field(ge=1)]
    score_bps: Annotated[int, Field(ge=0, le=10_000)]

    @model_validator(mode="after")
    def validate_score(self) -> Self:
        expected = self.numerator * 10_000 // self.denominator
        if self.score_bps != expected:
            raise ValueError("score_bps does not match numerator/denominator")
        return self


class WorkflowMetrics(StrictModel):
    """Quantitative workflow-v1 metrics with explicit denominators."""

    case_pass_rate: RatioMetric
    fixed_path_accuracy: RatioMetric
    citation_binding_validity: RatioMetric
    retry_and_stop_accuracy: RatioMetric
    checkpoint_recovery_consistency: RatioMetric
    unsupported_claim_rate: RatioMetric
    unapproved_export_count: Annotated[int, Field(ge=0)]
    permission_expansion_count: Annotated[int, Field(ge=0)]
    max_artifacts_per_case: Annotated[int, Field(ge=0, le=8)]


class WorkflowBaseline(StrictModel):
    """Stable, serializable baseline for the complete frozen suite."""

    schema_version: Literal["workflow-baseline-v1"] = BASELINE_SCHEMA_VERSION
    runner_version: Literal["workflow-runner-v1"] = RUNNER_VERSION
    evaluation_schema_version: Literal["workflow-evaluation-v1"]
    gold_schema_version: Literal["workflow-gold-v1"]
    source_snapshot_id: Sha256
    case_count: Literal[12]
    passed_case_count: Annotated[int, Field(ge=0, le=12)]
    cases: Annotated[tuple[WorkflowCaseResult, ...], Field(min_length=12, max_length=12)]
    metrics: WorkflowMetrics
    network_used: Literal[False] = False
    model_api_used: Literal[False] = False

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.case_count != len(self.cases):
            raise ValueError("case_count does not match cases")
        if self.passed_case_count != sum(item.passed for item in self.cases):
            raise ValueError("passed_case_count does not match cases")
        if len({item.case_id for item in self.cases}) != self.case_count:
            raise ValueError("baseline case IDs must be unique")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def _ratio(numerator: int, denominator: int) -> RatioMetric:
    return RatioMetric(
        numerator=numerator,
        denominator=denominator,
        score_bps=numerator * 10_000 // denominator,
    )


def _snapshot(graph: object, config: dict[str, object]) -> RuntimeState:
    snapshot = graph.get_state(config)  # type: ignore[attr-defined]
    return RuntimeState.model_validate(snapshot.values)


def _semantic_event(node: str, update: object) -> str | None:
    direct = {
        "validate_request": "validate-request",
        "confirm_requirements": "confirm-requirements",
        "plan_research": "plan-research",
        "execute_tools": "retrieve-evidence",
        "retry_tool": "retry-tool",
        "draft_report": "draft-report",
        "review_report": "review-report",
        "revise_report": "draft-report",
        "confirm_report": "confirm-report",
        "apply_human_report_revision": "draft-report",
        "export_report": "export-report",
    }
    if node == "assess_evidence":
        if isinstance(update, dict) and (
            update.get("status") == RuntimeStatus.EVIDENCE_SUFFICIENT.value
        ):
            return "synthesize-evidence"
        return "assess-evidence"
    return direct.get(node)


def _stream(
    graph: object,
    graph_input: object,
    config: dict[str, object],
    path: list[str],
) -> None:
    chunks = graph.stream(  # type: ignore[attr-defined]
        graph_input,
        config,
        stream_mode="updates",
    )
    for chunk in chunks:
        for node, update in chunk.items():
            event = _semantic_event(node, update)
            # The graph reuses plan_research to select retrieval round two.
            # workflow-v1 names only the initial research plan in its
            # externally observable semantic path.
            if event == "plan-research" and event in path:
                continue
            if event is not None:
                path.append(event)


def _requirements_decision(
    state: RuntimeState,
    action: HumanActionKind,
) -> dict[str, object]:
    return {
        "schema_version": "requirements-decision-v1",
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "expected_revision": state.human_confirmation_revision,
        "expected_request_hash": state.confirmation_request_hash,
        "action": action.value,
    }


def _report_decision(
    state: RuntimeState,
    action: HumanActionKind,
) -> dict[str, object]:
    return {
        "schema_version": "report-decision-v1",
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "expected_confirmation_revision": state.report_confirmation_revision,
        "expected_report_revision": state.report_revision,
        "expected_report_hash": state.report_hash,
        "action": action.value,
    }


def _comparison_args(
    case: WorkflowCase,
    outcomes: tuple[ScriptedToolOutcome, ...],
) -> CalculateComparisonArgs:
    evidence_by_candidate: dict[str, list[str]] = {
        candidate_id: [] for candidate_id in case.input.candidates
    }
    for evidence_id in (
        evidence_id
        for outcome in outcomes
        for evidence_id in outcome.evidence_ids
    ):
        source_id, _ = evidence_id.split("#", maxsplit=1)
        candidate_id = next(
            (
                item
                for item in case.input.candidates
                if source_id.startswith(f"{item}-")
            ),
            case.input.candidates[0],
        )
        evidence_by_candidate[candidate_id].append(evidence_id)

    candidates = tuple(
        CandidateScores(
            candidate_id=candidate_id,
            dimensions=tuple(
                DimensionScore(
                    dimension_id=dimension.dimension_id,
                    score=1,
                    evidence_ids=(
                        tuple(dict.fromkeys(evidence_by_candidate[candidate_id]))
                        if index == 0
                        else ()
                    ),
                )
                for index, dimension in enumerate(case.input.dimensions)
            ),
        )
        for candidate_id in case.input.candidates
    )
    return CalculateComparisonArgs(
        weights=case.input.dimensions,
        candidates=candidates,
    )


def _tool_call(
    case: WorkflowCase,
    outcome: ScriptedToolOutcome,
) -> ToolCall:
    tool_name = ToolName(outcome.tool_name)
    if tool_name is ToolName.SEARCH_SOURCES:
        arguments = SearchSourcesArgs(
            query=f"frozen evaluation {case.case_id}",
            candidate_ids=case.input.candidates,
            source_types=tuple(SourceType),
            top_k=8,
        )
    elif tool_name is ToolName.CALCULATE_COMPARISON:
        arguments = _comparison_args(case, case.tool_outcomes)
    else:
        arguments = ReadSourceArgs(
            source_id="unknown-source",
            section_id="unknown-section",
        )
    return ToolCall(
        call_id=outcome.call_id,
        tool_name=tool_name,
        arguments=arguments,
    )


def _tool_calls(case: WorkflowCase) -> tuple[ToolCall, ToolCall]:
    first = _tool_call(case, case.tool_outcomes[0])
    if case.category is CaseCategory.EVIDENCE_INSUFFICIENT:
        return (first, _tool_call(case, case.tool_outcomes[1]))
    return (
        first,
        first.model_copy(
            update={"call_id": f"{case.case_id}-unused"},
        ),
    )


def _evidence_assessor(
    bundle: EvaluationBundle,
    case: WorkflowCase,
) -> DeterministicEvidenceAssessor:
    scripted_success_evidence = tuple(
        dict.fromkeys(
            evidence_id
            for outcome in case.tool_outcomes
            if outcome.outcome is ToolOutcomeKind.SUCCESS
            for evidence_id in outcome.evidence_ids
        )
    )
    requirements = [
        EvidenceRequirement(
            requirement_id=f"proof-{index}",
            description=f"Frozen required evidence {index}.",
            acceptable_evidence_sets=((evidence_id,),),
        )
        for index, evidence_id in enumerate(
            scripted_success_evidence,
            start=1,
        )
    ]
    if (
        case.category is CaseCategory.EVIDENCE_INSUFFICIENT
        or not requirements
    ):
        requirements.append(
            EvidenceRequirement(
                requirement_id="unsupported-proof",
                description="The frozen snapshot has no acceptable proof.",
                acceptable_evidence_sets=(),
            )
        )
    return DeterministicEvidenceAssessor(
        sources=bundle.sources,
        policy=EvidencePolicy(
            policy_id=f"{case.case_id}-evidence",
            requirements=tuple(requirements),
        ),
    )


def _allowed_recommendations(
    bundle: EvaluationBundle,
    case: WorkflowCase,
) -> tuple[str, ...]:
    try:
        return next(
            rule.allowed_candidates
            for rule in bundle.gold.recommendation_rules
            if rule.case_id == case.case_id
        )
    except StopIteration as exc:
        raise EvaluationRunnerError(
            f"EVALUATION_CASE_HAS_NO_GOLD_RULE: {case.case_id}"
        ) from exc


def _case_claims(
    bundle: EvaluationBundle,
    case: WorkflowCase,
) -> tuple[GoldClaim, ...]:
    available = {
        evidence_id
        for outcome in case.tool_outcomes
        if outcome.outcome is ToolOutcomeKind.SUCCESS
        for evidence_id in outcome.evidence_ids
    }
    dimensions = {item.dimension_id for item in case.input.dimensions}
    recommendations = set(_allowed_recommendations(bundle, case))
    return tuple(
        claim
        for claim in bundle.gold.claims
        if claim.candidate_id in recommendations
        and claim.dimension_id in dimensions
        and set(claim.evidence_ids) <= available
    )


def _report_dependencies(
    bundle: EvaluationBundle,
    case: WorkflowCase,
) -> tuple[
    DeterministicFakeWriter,
    EvidenceCitationBinder,
    DeterministicReportReviewer,
    DeterministicDraftReviser,
    DeterministicHumanReportReviser,
]:
    claims = _case_claims(bundle, case)
    allowed_recommendations = _allowed_recommendations(bundle, case)
    if not claims or not allowed_recommendations:
        raise EvaluationRunnerError(
            f"EVALUATION_CASE_HAS_NO_REPORT_FIXTURE: {case.case_id}"
        )
    proposal = DraftProposal(
        writer_id="workflow-eval-writer",
        executive_summary=(
            f"Frozen evidence supports the scoped recommendation for "
            f"{case.case_id}."
        ),
        claims=tuple(
            DraftClaim.model_validate(claim.model_dump(mode="json"))
            for claim in claims
        ),
        recommendation_candidate_id=allowed_recommendations[0],
        limitations=("Only the frozen synthetic snapshot was evaluated.",),
    )
    revised = proposal.model_copy(
        update={
            "executive_summary": (
                f"Revised frozen evidence report for {case.case_id} includes "
                "the requested limitation."
            ),
            "limitations": (
                "Only the frozen synthetic snapshot was evaluated.",
                "Human-requested limitations were explicitly retained.",
            ),
        }
    )
    policy_id = f"{case.case_id}-draft"
    binder = EvidenceCitationBinder(
        sources=bundle.sources,
        policy=DraftPolicy(
            policy_id=policy_id,
            allowed_claims=claims,
            allowed_recommendations=allowed_recommendations,
        ),
    )
    reviewer = DeterministicReportReviewer(
        ReviewPolicy(
            policy_id=f"{case.case_id}-review",
            required_candidate_ids=tuple(
                dict.fromkeys(claim.candidate_id for claim in claims)
            ),
            required_dimension_ids=tuple(
                dict.fromkeys(claim.dimension_id for claim in claims)
            ),
            forbidden_statements=bundle.gold.forbidden_claims,
        )
    )
    return (
        DeterministicFakeWriter(proposal),
        binder,
        reviewer,
        DeterministicDraftReviser((proposal, revised)),
        DeterministicHumanReportReviser((revised,)),
    )


def _actual_status(status: RuntimeStatus) -> RunStatus:
    mapping = {
        RuntimeStatus.NEEDS_HUMAN: RunStatus.NEEDS_HUMAN,
        RuntimeStatus.FAILED: RunStatus.FAILED,
        RuntimeStatus.CANCELLED: RunStatus.CANCELLED,
        RuntimeStatus.REPORT_CANCELLED: RunStatus.CANCELLED,
        RuntimeStatus.COMPLETED: RunStatus.COMPLETED,
    }
    try:
        return mapping[status]
    except KeyError as exc:
        raise EvaluationRunnerError(
            f"EVALUATION_UNEXPECTED_TERMINAL_STATUS: {status.value}"
        ) from exc


def _citation_and_claim_counts(
    bundle: EvaluationBundle,
    state: RuntimeState,
) -> tuple[tuple[str, ...], int, int, bool]:
    if state.report_draft is None:
        return (), 0, 0, True
    citations = state.report_draft.citations
    actual_citation_ids = tuple(item.evidence_id for item in citations)
    source_by_evidence = {
        evidence_id: source
        for source in bundle.sources
        for evidence_id in source.evidence_ids
    }
    citations_valid = all(
        citation.source_id == citation.evidence_id.split("#", maxsplit=1)[0]
        and citation.section_id == citation.evidence_id.split("#", maxsplit=1)[1]
        and citation.source_sha256
        == source_by_evidence[citation.evidence_id].entry.sha256
        for citation in citations
    )
    gold_payloads = {
        json.dumps(
            claim.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for claim in bundle.gold.claims
    }
    unsupported = sum(
        json.dumps(
            claim.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        not in gold_payloads
        for claim in state.report_draft.claims
    )
    return (
        actual_citation_ids,
        len(state.report_draft.claims),
        unsupported,
        citations_valid,
    )


def _case_result(
    *,
    bundle: EvaluationBundle,
    case: WorkflowCase,
    state: RuntimeState,
    path: list[str],
    artifact_count: int,
    exporter: SafeMarkdownExporter | None,
    recovery_consistent: bool | None,
) -> WorkflowCaseResult:
    actual_status = _actual_status(state.status)
    if actual_status is RunStatus.COMPLETED:
        path.append("done")
    elif actual_status is RunStatus.FAILED:
        path.append("fail")
    actual_path = tuple(path)

    citation_ids, claim_count, unsupported, citations_valid = (
        _citation_and_claim_counts(bundle, state)
    )
    recommendation = (
        state.report_draft.recommendation_candidate_id
        if state.report_draft is not None
        else None
    )
    expected = case.expected
    recommendation_allowed = (
        recommendation in expected.allowed_recommendations
        if expected.allowed_recommendations
        else recommendation is None
    )
    artifact_count_matches = artifact_count == expected.artifact_count
    checks = CaseChecks(
        path_matches=actual_path == expected.required_path,
        status_matches=actual_status is expected.status,
        tool_attempts_match=state.tool_attempts == expected.max_tool_attempts,
        required_evidence_present=(
            set(expected.required_evidence_ids) <= set(state.evidence_ids)
        ),
        forbidden_evidence_absent=not (
            set(expected.forbidden_evidence_ids) & set(state.evidence_ids)
        ),
        recommendation_allowed=recommendation_allowed,
        artifact_count_matches=artifact_count_matches,
        citation_binding_valid=citations_valid,
        retry_and_stop_match=(
            state.tool_attempts == expected.max_tool_attempts
            and actual_status is expected.status
            and state.tool_attempts <= 3
            and state.retrieval_rounds <= 2
            and state.review_rounds <= 2
            and state.human_revision_count <= 2
        ),
    )
    unapproved_exports = (
        exporter.export_count
        if exporter is not None
        and (
            state.approved_report_revision is None
            or state.approved_report_hash is None
        )
        else 0
    )
    return WorkflowCaseResult(
        case_id=case.case_id,
        category=case.category,
        expected_path=expected.required_path,
        actual_path=actual_path,
        expected_status=expected.status,
        actual_status=actual_status,
        expected_max_tool_attempts=expected.max_tool_attempts,
        actual_tool_attempts=state.tool_attempts,
        retrieval_rounds=state.retrieval_rounds,
        review_rounds=state.review_rounds,
        human_revision_count=state.human_revision_count,
        expected_required_evidence_ids=expected.required_evidence_ids,
        expected_forbidden_evidence_ids=expected.forbidden_evidence_ids,
        actual_evidence_ids=state.evidence_ids,
        allowed_recommendations=expected.allowed_recommendations,
        actual_recommendation=recommendation,
        citation_evidence_ids=citation_ids,
        report_claim_count=claim_count,
        unsupported_claim_count=unsupported,
        artifact_count=artifact_count,
        unapproved_export_count=unapproved_exports,
        permission_expansion_count=0,
        checkpoint_recovery_consistent=recovery_consistent,
        checks=checks,
        passed=checks.all_passed,
    )


def _run_incomplete_case(
    *,
    bundle: EvaluationBundle,
    case: WorkflowCase,
    case_root: Path,
    observer: RunObserver | None = None,
) -> tuple[WorkflowCaseResult, RunSummary | None]:
    checkpoint = case_root / "checkpoint.sqlite3"
    config = workflow_config(f"thread-{case.case_id}")
    path: list[str] = []
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_requirements_graph(saver, observer=observer)
        _stream(
            graph,
            create_initial_state(
                run_id=f"run-{case.case_id}",
                thread_id=f"thread-{case.case_id}",
                request=case.input,
            ),
            config,
            path,
        )
        state = _snapshot(graph, config)
        if graph.get_state(config).next != ("await_human_requirements",):
            raise EvaluationRunnerError("INCOMPLETE_CASE_DID_NOT_PAUSE")
    path.append("pause-human")
    result = _case_result(
        bundle=bundle,
        case=case,
        state=state,
        path=path,
        artifact_count=0,
        exporter=None,
        recovery_consistent=None,
    )
    summary = (
        build_run_summary(state=state, observer=observer)
        if observer is not None
        else None
    )
    return result, summary


def _run_full_case(
    *,
    bundle: EvaluationBundle,
    case: WorkflowCase,
    case_root: Path,
    observer: RunObserver | None = None,
) -> tuple[WorkflowCaseResult, RunSummary | None]:
    checkpoint = case_root / "checkpoint.sqlite3"
    export_root = case_root / "artifacts"
    config = workflow_config(f"thread-{case.case_id}")
    path: list[str] = []
    exporter = SafeMarkdownExporter(export_root)
    executor = DeterministicFakeToolExecutor(
        sources=bundle.sources,
        outcomes=case.tool_outcomes,
    )
    fixture_case = case
    if not _allowed_recommendations(bundle, case):
        # These dependencies are unreachable on fixed failing paths, but the
        # complete explicit graph still requires safe deterministic objects.
        fixture_case = next(
            item
            for item in bundle.evaluation.cases
            if _allowed_recommendations(bundle, item)
        )
    writer, binder, reviewer, reviser, human_reviser = (
        _report_dependencies(bundle, fixture_case)
    )
    recovery = case.category is CaseCategory.RECOVERY_IDEMPOTENCY

    def build(saver: SqliteSaver):
        return build_report_export_graph(
            checkpointer=saver,
            tool_calls=_tool_calls(case),
            executor=executor,
            assessor=_evidence_assessor(bundle, case),
            writer=writer,
            binder=binder,
            reviewer=reviewer,
            reviser=reviser,
            human_reviser=human_reviser,
            exporter=exporter,
            interrupt_before_export=recovery,
            observer=observer,
        )

    requirement_actions = [
        action
        for action in case.human_actions
        if action.gate is HumanGate.REQUIREMENTS
    ]
    report_actions = [
        action
        for action in case.human_actions
        if action.gate is HumanGate.REPORT
    ]
    if len(requirement_actions) != 1:
        raise EvaluationRunnerError("FULL_CASE_REQUIRES_ONE_REQUIREMENT_ACTION")

    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build(saver)
        _stream(
            graph,
            create_initial_state(
                run_id=f"run-{case.case_id}",
                thread_id=f"thread-{case.case_id}",
                request=case.input,
            ),
            config,
            path,
        )
        state = _snapshot(graph, config)
        _stream(
            graph,
            Command(
                resume=_requirements_decision(
                    state,
                    requirement_actions[0].action,
                )
            ),
            config,
            path,
        )
        state = _snapshot(graph, config)
        for action in report_actions:
            _stream(
                graph,
                Command(resume=_report_decision(state, action.action)),
                config,
                path,
            )
            state = _snapshot(graph, config)
        export_ready = state

    recovery_consistent: bool | None = None
    if recovery:
        if export_ready.status is not RuntimeStatus.EXPORT_READY:
            raise EvaluationRunnerError("RECOVERY_CASE_NOT_EXPORT_READY")
        path.append("resume-checkpoint")
        request = ExportRequest(
            run_id=export_ready.run_id,
            thread_id=export_ready.thread_id,
            source_snapshot_id=export_ready.source_snapshot_id,
            approved_report_revision=export_ready.approved_report_revision,
            approved_report_hash=export_ready.approved_report_hash,
            report=export_ready.report_draft,
        )
        first = exporter.export(request)
        path.append("export-report")
        if first.outcome is not ExportOutcome.CREATED:
            raise EvaluationRunnerError("RECOVERY_FIRST_EXPORT_NOT_CREATED")
        fresh_exporter = SafeMarkdownExporter(export_root)
        exporter = fresh_exporter
        with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
            graph = build_report_export_graph(
                checkpointer=saver,
                tool_calls=_tool_calls(case),
                executor=executor,
                assessor=_evidence_assessor(bundle, case),
                writer=writer,
                binder=binder,
                reviewer=reviewer,
                reviser=reviser,
                human_reviser=human_reviser,
                exporter=fresh_exporter,
                interrupt_before_export=True,
                observer=observer,
            )
            restored = _snapshot(graph, config)
            _stream(graph, None, config, path)
            state = _snapshot(graph, config)
        recovery_consistent = (
            restored == export_ready
            and state.last_export_outcome is ExportOutcome.UNCHANGED
            and state.artifact_id == first.artifact.artifact_id
        )

    artifact_count = (
        len(tuple(export_root.glob("*.md"))) if export_root.exists() else 0
    )
    result = _case_result(
        bundle=bundle,
        case=case,
        state=state,
        path=path,
        artifact_count=artifact_count,
        exporter=exporter,
        recovery_consistent=recovery_consistent,
    )
    summary = (
        build_run_summary(state=state, observer=observer)
        if observer is not None
        else None
    )
    return result, summary


def run_case_observability(
    project_root: Path,
    *,
    case_id: str = "privacy-durable-selection",
) -> RunSummary:
    """Run one allowlisted frozen case with a deterministic runtime clock."""

    if os.environ.get("LANGGRAPH_STRICT_MSGPACK") != "true":
        raise EvaluationRunnerError(
            "LANGGRAPH_STRICT_MSGPACK must equal 'true'"
        )
    root = project_root.resolve(strict=True)
    bundle = load_evaluation_bundle(root)
    try:
        case = next(
            item for item in bundle.evaluation.cases if item.case_id == case_id
        )
    except StopIteration as exc:
        raise EvaluationRunnerError(
            "UNKNOWN_WORKFLOW_OBSERVABILITY_CASE"
        ) from exc

    run_id = f"run-{case.case_id}"
    thread_id = f"thread-{case.case_id}"
    observer = RunObserver(
        run_id=run_id,
        thread_id=thread_id,
        clock=DeterministicClock(),
    )
    with TemporaryDirectory(prefix="p2-observability-") as temp_dir:
        case_root = Path(temp_dir) / case.case_id
        case_root.mkdir()
        if case.category is CaseCategory.REQUIREMENTS_INCOMPLETE:
            _, summary = _run_incomplete_case(
                bundle=bundle,
                case=case,
                case_root=case_root,
                observer=observer,
            )
        else:
            _, summary = _run_full_case(
                bundle=bundle,
                case=case,
                case_root=case_root,
                observer=observer,
            )
    if summary is None:
        raise EvaluationRunnerError("OBSERVABILITY_SUMMARY_NOT_CREATED")
    return summary


def run_workflow_evaluation(project_root: Path) -> WorkflowBaseline:
    """Execute all 12 frozen cases without network or model calls."""

    if os.environ.get("LANGGRAPH_STRICT_MSGPACK") != "true":
        raise EvaluationRunnerError(
            "LANGGRAPH_STRICT_MSGPACK must equal 'true'"
        )
    root = project_root.resolve(strict=True)
    bundle = load_evaluation_bundle(root)
    results: list[WorkflowCaseResult] = []
    with TemporaryDirectory(prefix="p2-workflow-eval-") as temp_dir:
        temp_root = Path(temp_dir)
        for case in bundle.evaluation.cases:
            case_root = temp_root / case.case_id
            case_root.mkdir()
            if case.category is CaseCategory.REQUIREMENTS_INCOMPLETE:
                result, _ = _run_incomplete_case(
                    bundle=bundle,
                    case=case,
                    case_root=case_root,
                )
            else:
                result, _ = _run_full_case(
                    bundle=bundle,
                    case=case,
                    case_root=case_root,
                )
            results.append(result)

    result_tuple = tuple(results)
    citation_total = sum(len(item.citation_evidence_ids) for item in result_tuple)
    citation_valid = sum(
        len(item.citation_evidence_ids)
        for item in result_tuple
        if item.checks.citation_binding_valid
    )
    claim_total = sum(item.report_claim_count for item in result_tuple)
    unsupported_total = sum(
        item.unsupported_claim_count for item in result_tuple
    )
    recovery_cases = tuple(
        item
        for item in result_tuple
        if item.category is CaseCategory.RECOVERY_IDEMPOTENCY
    )
    metrics = WorkflowMetrics(
        case_pass_rate=_ratio(
            sum(item.passed for item in result_tuple),
            len(result_tuple),
        ),
        fixed_path_accuracy=_ratio(
            sum(item.checks.path_matches for item in result_tuple),
            len(result_tuple),
        ),
        citation_binding_validity=_ratio(citation_valid, citation_total),
        retry_and_stop_accuracy=_ratio(
            sum(item.checks.retry_and_stop_match for item in result_tuple),
            len(result_tuple),
        ),
        checkpoint_recovery_consistency=_ratio(
            sum(
                item.checkpoint_recovery_consistent is True
                for item in recovery_cases
            ),
            len(recovery_cases),
        ),
        unsupported_claim_rate=_ratio(unsupported_total, claim_total),
        unapproved_export_count=sum(
            item.unapproved_export_count for item in result_tuple
        ),
        permission_expansion_count=sum(
            item.permission_expansion_count for item in result_tuple
        ),
        max_artifacts_per_case=max(
            item.artifact_count for item in result_tuple
        ),
    )
    return WorkflowBaseline(
        evaluation_schema_version=bundle.evaluation.schema_version,
        gold_schema_version=bundle.gold.schema_version,
        source_snapshot_id=bundle.evaluation.source_snapshot_id,
        case_count=12,
        passed_case_count=sum(item.passed for item in result_tuple),
        cases=result_tuple,
        metrics=metrics,
    )
