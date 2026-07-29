"""Minimal LangGraph for requirement validation and human confirmation."""

from __future__ import annotations

import hashlib
from functools import partial
from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_research.evidence_assessment import (
    DeterministicEvidenceAssessor,
    EvidenceAssessmentStatus,
    MAX_RETRIEVAL_ROUNDS,
)
from agent_research.fake_tools import DeterministicFakeToolExecutor
from agent_research.models import (
    HumanActionKind,
    ResearchInput,
    ToolOutcomeKind,
)
from agent_research.report_drafting import (
    DeterministicFakeWriter,
    EvidenceCitationBinder,
    hash_report_draft,
)
from agent_research.report_review import (
    DeterministicDraftReviser,
    DeterministicReportReviewer,
    MAX_REVIEW_ROUNDS,
    ReviewOutcome,
)
from agent_research.runtime_state import (
    MissingRequirement,
    RequirementsDecision,
    RequirementsPause,
    RuntimeNode,
    RuntimeState,
    RuntimeStatus,
    SafeStateError,
    hash_research_input,
)
from agent_research.tool_contracts import ToolCall


class HumanDecisionError(ValueError):
    """Raised when a resume decision does not match the persisted revision."""


def _validated_update(
    state: RuntimeState,
    **updates: object,
) -> dict[str, object]:
    """Validate each partial node output as a complete state transition."""

    merged = state.model_dump(mode="json")
    merged.update(updates)
    validated = RuntimeState.model_validate(merged).model_dump(mode="json")
    return {field: validated[field] for field in updates}


def create_initial_state(
    *,
    run_id: str,
    thread_id: str,
    request: ResearchInput | dict[str, object],
) -> dict[str, object]:
    """Validate external input before any value can reach a checkpoint."""

    state = RuntimeState(
        run_id=run_id,
        thread_id=thread_id,
        raw_request=ResearchInput.model_validate(request),
    )
    return state.model_dump(mode="json")


def workflow_config(thread_id: str) -> dict[str, dict[str, str]]:
    """Build the stable LangGraph checkpoint identity."""

    return {"configurable": {"thread_id": thread_id}}


def validate_request(state: RuntimeState) -> dict[str, object]:
    """Find missing research scope without guessing candidates or dimensions."""

    missing: list[str] = []
    if not state.raw_request.candidates:
        missing.append(MissingRequirement.CANDIDATES.value)
    if not state.raw_request.dimensions:
        missing.append(MissingRequirement.DIMENSIONS.value)

    return _validated_update(
        state,
        status=RuntimeStatus.VALIDATED.value,
        current_node=RuntimeNode.CONFIRM_REQUIREMENTS.value,
        missing_requirements=missing,
    )


def confirm_requirements(state: RuntimeState) -> dict[str, object]:
    """Persist an explicit human-waiting revision before interrupting."""

    return _validated_update(
        state,
        status=RuntimeStatus.NEEDS_HUMAN.value,
        current_node=RuntimeNode.AWAIT_HUMAN_REQUIREMENTS.value,
        human_confirmation_revision=(
            state.human_confirmation_revision + 1
        ),
        confirmation_request_hash=hash_research_input(state.raw_request),
    )


def _validate_decision_binding(
    state: RuntimeState,
    decision: RequirementsDecision,
) -> None:
    if decision.run_id != state.run_id:
        raise HumanDecisionError("HUMAN_DECISION_RUN_ID_MISMATCH")
    if decision.thread_id != state.thread_id:
        raise HumanDecisionError("HUMAN_DECISION_THREAD_ID_MISMATCH")
    if decision.expected_revision != state.human_confirmation_revision:
        raise HumanDecisionError("HUMAN_DECISION_STALE_REVISION")
    if decision.expected_request_hash != state.confirmation_request_hash:
        raise HumanDecisionError("HUMAN_DECISION_STALE_REQUEST_HASH")


def await_human_requirements(state: RuntimeState) -> dict[str, object]:
    """Pause, validate a revision-bound response, then update business state."""

    if state.confirmation_request_hash is None:
        raise HumanDecisionError("HUMAN_DECISION_MISSING_REQUEST_HASH")

    pause = RequirementsPause(
        run_id=state.run_id,
        thread_id=state.thread_id,
        revision=state.human_confirmation_revision,
        request_hash=state.confirmation_request_hash,
        missing_requirements=state.missing_requirements,
        request=state.raw_request,
    )
    raw_decision = interrupt(pause.model_dump(mode="json"))
    decision = RequirementsDecision.model_validate(raw_decision)
    _validate_decision_binding(state, decision)

    if decision.action is HumanActionKind.APPROVE:
        if state.missing_requirements:
            raise HumanDecisionError(
                "HUMAN_APPROVAL_INCOMPLETE_REQUIREMENTS"
            )
        return _validated_update(
            state,
            status=RuntimeStatus.REQUIREMENTS_CONFIRMED.value,
            current_node=RuntimeNode.PLAN_RESEARCH.value,
            confirmed_requirements=state.raw_request.model_dump(mode="json"),
            last_human_action=HumanActionKind.APPROVE.value,
        )

    if decision.action is HumanActionKind.EDIT:
        if decision.edited_request is None:  # guarded by Pydantic
            raise HumanDecisionError("HUMAN_EDIT_MISSING_REQUEST")
        return _validated_update(
            state,
            status=RuntimeStatus.NEW.value,
            current_node=RuntimeNode.VALIDATE_REQUEST.value,
            raw_request=decision.edited_request.model_dump(mode="json"),
            confirmed_requirements=None,
            confirmation_request_hash=None,
            missing_requirements=[],
            last_human_action=HumanActionKind.EDIT.value,
            plan_id=None,
        )

    if decision.action is HumanActionKind.REJECT:
        return _validated_update(
            state,
            status=RuntimeStatus.REJECTED.value,
            current_node=RuntimeNode.END.value,
            confirmed_requirements=None,
            last_human_action=HumanActionKind.REJECT.value,
        )

    if decision.action is HumanActionKind.CANCEL:
        return _validated_update(
            state,
            status=RuntimeStatus.CANCELLED.value,
            current_node=RuntimeNode.END.value,
            confirmed_requirements=None,
            last_human_action=HumanActionKind.CANCEL.value,
        )

    raise HumanDecisionError("HUMAN_DECISION_UNSUPPORTED_ACTION")


def _route_after_human(
    state: RuntimeState,
) -> Literal["plan", "edit", "terminal"]:
    if state.status is RuntimeStatus.REQUIREMENTS_CONFIRMED:
        return "plan"
    if state.status is RuntimeStatus.NEW:
        return "edit"
    if state.status in {RuntimeStatus.REJECTED, RuntimeStatus.CANCELLED}:
        return "terminal"
    raise HumanDecisionError("HUMAN_DECISION_INVALID_ROUTE")


def plan_research(state: RuntimeState) -> dict[str, object]:
    """Deterministic placeholder; retrieval and report generation stay out of scope."""

    if state.confirmation_request_hash is None:
        raise ValueError("PLAN_REQUIRES_CONFIRMED_REQUEST_HASH")
    plan_id = hashlib.sha256(
        (
            f"{state.run_id}:{state.confirmation_request_hash}:"
            "requirements-confirmation-v1"
        ).encode("utf-8")
    ).hexdigest()
    return _validated_update(
        state,
        status=RuntimeStatus.PLANNED.value,
        current_node=RuntimeNode.PLAN_RESEARCH.value,
        plan_id=plan_id,
    )


def plan_tool_call(
    state: RuntimeState,
    *,
    tool_call: ToolCall,
) -> dict[str, object]:
    """Persist one deterministic validated call for the minimal tool slice."""

    if state.confirmation_request_hash is None:
        raise ValueError("PLAN_REQUIRES_CONFIRMED_REQUEST_HASH")
    plan_id = hashlib.sha256(
        (
            f"{state.run_id}:{state.confirmation_request_hash}:"
            "tool-execution-v1"
        ).encode("utf-8")
    ).hexdigest()
    retrieval_rounds = (
        1
        if tool_call.tool_name.value in {"search_sources", "read_source"}
        else state.retrieval_rounds
    )
    return _validated_update(
        state,
        graph_version="tool-execution-v1",
        status=RuntimeStatus.TOOL_READY.value,
        current_node=RuntimeNode.EXECUTE_TOOLS.value,
        plan_id=plan_id,
        pending_tool_call=tool_call.model_dump(mode="json"),
        last_tool_result=None,
        tool_attempts=0,
        retrieval_rounds=retrieval_rounds,
    )


def plan_evidence_round(
    state: RuntimeState,
    *,
    tool_calls: tuple[ToolCall, ...],
    assessor: DeterministicEvidenceAssessor,
) -> dict[str, object]:
    """Persist the next frozen call without exceeding two retrieval rounds."""

    if state.confirmation_request_hash is None:
        raise ValueError("PLAN_REQUIRES_CONFIRMED_REQUEST_HASH")
    if state.retrieval_rounds >= MAX_RETRIEVAL_ROUNDS:
        raise ValueError("RETRIEVAL_ROUND_LIMIT_REACHED")

    next_round = state.retrieval_rounds + 1
    tool_call = tool_calls[next_round - 1]
    plan_id = hashlib.sha256(
        (
            f"{state.run_id}:{state.confirmation_request_hash}:"
            f"{assessor.policy.policy_id}:evidence-assessment-v1"
        ).encode("utf-8")
    ).hexdigest()
    return _validated_update(
        state,
        graph_version="evidence-assessment-v1",
        status=RuntimeStatus.TOOL_READY.value,
        current_node=RuntimeNode.EXECUTE_TOOLS.value,
        plan_id=plan_id,
        pending_tool_call=tool_call.model_dump(mode="json"),
        last_tool_result=None,
        retrieval_rounds=next_round,
        evidence_policy_id=assessor.policy.policy_id,
        evidence_gaps=[],
        last_evidence_assessment=None,
    )


def _safe_error(
    *,
    code: str,
    summary: str,
    retryable: bool,
    node: RuntimeNode = RuntimeNode.EXECUTE_TOOLS,
) -> dict[str, object]:
    return SafeStateError(
        code=code,
        node=node,
        safe_summary=summary,
        retryable=retryable,
    ).model_dump(mode="json")


def execute_tools(
    state: RuntimeState,
    *,
    executor: DeterministicFakeToolExecutor,
    continue_to_assessment: bool = False,
) -> dict[str, object]:
    """Execute one allowlisted call with persisted attempt and stop rules."""

    if state.pending_tool_call is None:
        raise ValueError("TOOL_EXECUTION_REQUIRES_PENDING_CALL")
    if state.confirmed_requirements is None:
        raise ValueError("TOOL_EXECUTION_REQUIRES_CONFIRMED_REQUIREMENTS")

    attempt = state.tool_attempts + 1
    result = executor.execute(
        call=state.pending_tool_call,
        confirmed=state.confirmed_requirements,
        source_snapshot_id=state.source_snapshot_id,
        attempt=attempt,
    )
    common: dict[str, object] = {
        "tool_attempts": attempt,
        "last_tool_result": result.model_dump(mode="json"),
    }

    if result.outcome is ToolOutcomeKind.SUCCESS:
        evidence_ids = tuple(
            dict.fromkeys((*state.evidence_ids, *result.evidence_ids))
        )
        return _validated_update(
            state,
            **common,
            status=(
                RuntimeStatus.EVIDENCE_PENDING_ASSESSMENT.value
                if continue_to_assessment
                else RuntimeStatus.EVIDENCE_READY.value
            ),
            current_node=(
                RuntimeNode.ASSESS_EVIDENCE.value
                if continue_to_assessment
                else RuntimeNode.END.value
            ),
            evidence_ids=evidence_ids,
        )

    if result.outcome is ToolOutcomeKind.TRANSIENT_ERROR:
        retryable = attempt < state.tool_call_budget
        code = (
            result.error_code
            if retryable
            else "tool-retry-exhausted"
        )
        summary = (
            result.safe_summary
            if retryable
            else "tool retry budget exhausted"
        )
        errors = (
            *state.errors,
            _safe_error(
                code=code or "transient-tool-error",
                summary=summary or "transient tool error",
                retryable=retryable,
            ),
        )
        return _validated_update(
            state,
            **common,
            status=(
                RuntimeStatus.TOOL_RETRY.value
                if retryable
                else RuntimeStatus.FAILED.value
            ),
            current_node=(
                RuntimeNode.RETRY_TOOL.value
                if retryable
                else RuntimeNode.END.value
            ),
            errors=errors,
        )

    errors = (
        *state.errors,
        _safe_error(
            code=result.error_code or "deterministic-tool-error",
            summary=result.safe_summary or "deterministic tool error",
            retryable=False,
        ),
    )
    return _validated_update(
        state,
        **common,
        status=RuntimeStatus.FAILED.value,
        current_node=RuntimeNode.END.value,
        errors=errors,
    )


def retry_tool(state: RuntimeState) -> dict[str, object]:
    """Route one persisted transient failure back to the same logical call."""

    return _validated_update(
        state,
        status=RuntimeStatus.TOOL_READY.value,
        current_node=RuntimeNode.EXECUTE_TOOLS.value,
    )


def assess_evidence(
    state: RuntimeState,
    *,
    assessor: DeterministicEvidenceAssessor,
) -> dict[str, object]:
    """Evaluate frozen evidence and either stop or request the final round."""

    if state.evidence_policy_id != assessor.policy.policy_id:
        raise ValueError("EVIDENCE_POLICY_ID_MISMATCH")
    assessment = assessor.assess(
        evidence_ids=state.evidence_ids,
        retrieval_round=state.retrieval_rounds,
    )
    common: dict[str, object] = {
        "last_evidence_assessment": assessment.model_dump(mode="json"),
        "evidence_gaps": assessment.gap_requirement_ids,
    }

    if assessment.status is EvidenceAssessmentStatus.SUFFICIENT:
        return _validated_update(
            state,
            **common,
            status=RuntimeStatus.EVIDENCE_SUFFICIENT.value,
            current_node=RuntimeNode.END.value,
        )

    if assessment.status is EvidenceAssessmentStatus.NEEDS_MORE_EVIDENCE:
        return _validated_update(
            state,
            **common,
            status=RuntimeStatus.EVIDENCE_NEEDS_MORE.value,
            current_node=RuntimeNode.PLAN_RESEARCH.value,
        )

    errors = (
        *state.errors,
        _safe_error(
            code="evidence-insufficient",
            summary="fixed evidence remains insufficient after final retrieval",
            retryable=False,
            node=RuntimeNode.ASSESS_EVIDENCE,
        ),
    )
    return _validated_update(
        state,
        **common,
        status=RuntimeStatus.FAILED.value,
        current_node=RuntimeNode.END.value,
        errors=errors,
    )


def draft_report(
    state: RuntimeState,
    *,
    writer: DeterministicFakeWriter,
    binder: EvidenceCitationBinder,
    continue_to_review: bool = False,
    review_policy_id: str | None = None,
) -> dict[str, object]:
    """Create one structured draft only after sufficient evidence."""

    if state.status is not RuntimeStatus.EVIDENCE_SUFFICIENT:
        raise ValueError("DRAFT_REQUIRES_SUFFICIENT_EVIDENCE")
    if state.confirmed_requirements is None:
        raise ValueError("DRAFT_REQUIRES_CONFIRMED_REQUIREMENTS")
    if (
        state.last_evidence_assessment is None
        or state.last_evidence_assessment.status
        is not EvidenceAssessmentStatus.SUFFICIENT
    ):
        raise ValueError("DRAFT_REQUIRES_SUFFICIENT_ASSESSMENT")
    if binder.policy.source_snapshot_id != state.source_snapshot_id:
        raise ValueError("DRAFT_POLICY_SNAPSHOT_MISMATCH")
    if continue_to_review and review_policy_id is None:
        raise ValueError("DRAFT_REVIEW_REQUIRES_POLICY_ID")

    proposal = writer.write()
    try:
        draft = binder.bind(
            proposal=proposal,
            confirmed_requirements=state.confirmed_requirements,
            available_evidence_ids=state.evidence_ids,
            revision=state.report_revision + 1,
        )
    except ValueError:
        errors = (
            *state.errors,
            _safe_error(
                code="invalid-draft-proposal",
                summary="draft proposal failed evidence or research scope checks",
                retryable=False,
                node=RuntimeNode.DRAFT_REPORT,
            ),
        )
        return _validated_update(
            state,
            graph_version=(
                "report-review-v1"
                if continue_to_review
                else "draft-report-v1"
            ),
            status=RuntimeStatus.FAILED.value,
            current_node=RuntimeNode.END.value,
            errors=errors,
        )
    return _validated_update(
        state,
        graph_version=(
            "report-review-v1" if continue_to_review else "draft-report-v1"
        ),
        status=(
            RuntimeStatus.REVIEW_READY.value
            if continue_to_review
            else RuntimeStatus.DRAFTED.value
        ),
        current_node=(
            RuntimeNode.REVIEW_REPORT.value
            if continue_to_review
            else RuntimeNode.END.value
        ),
        report_draft=draft.model_dump(mode="json"),
        report_revision=draft.revision,
        report_hash=hash_report_draft(draft),
        review_policy_id=review_policy_id,
    )


def review_report(
    state: RuntimeState,
    *,
    reviewer: DeterministicReportReviewer,
) -> dict[str, object]:
    """Review current draft and route by persisted revision budget."""

    if state.status is not RuntimeStatus.REVIEW_READY:
        raise ValueError("REVIEW_REQUIRES_READY_DRAFT")
    if state.report_draft is None or state.confirmed_requirements is None:
        raise ValueError("REVIEW_REQUIRES_DRAFT_AND_REQUIREMENTS")

    try:
        if (
            state.review_policy_id != reviewer.policy.policy_id
            or reviewer.policy.source_snapshot_id != state.source_snapshot_id
        ):
            raise ValueError("REVIEW_POLICY_ID_OR_SNAPSHOT_MISMATCH")
        result = reviewer.review(
            draft=state.report_draft,
            confirmed_requirements=state.confirmed_requirements,
            review_round=state.review_rounds,
        )
    except ValueError:
        errors = (
            *state.errors,
            _safe_error(
                code="invalid-review-policy",
                summary="review policy exceeds approved research scope",
                retryable=False,
                node=RuntimeNode.REVIEW_REPORT,
            ),
        )
        return _validated_update(
            state,
            status=RuntimeStatus.FAILED.value,
            current_node=RuntimeNode.END.value,
            last_review_result=None,
            errors=errors,
        )

    common: dict[str, object] = {
        "last_review_result": result.model_dump(mode="json"),
    }
    if result.outcome is ReviewOutcome.PASS:
        return _validated_update(
            state,
            **common,
            status=RuntimeStatus.REVIEWED.value,
            current_node=RuntimeNode.END.value,
        )
    if result.outcome is ReviewOutcome.REVISE:
        return _validated_update(
            state,
            **common,
            status=RuntimeStatus.REVIEW_REVISE.value,
            current_node=RuntimeNode.REVISE_REPORT.value,
        )

    errors = (
        *state.errors,
        _safe_error(
            code="review-limit-exhausted",
            summary="report still has review findings after revision limit",
            retryable=False,
            node=RuntimeNode.REVIEW_REPORT,
        ),
    )
    return _validated_update(
        state,
        **common,
        status=RuntimeStatus.FAILED.value,
        current_node=RuntimeNode.END.value,
        errors=errors,
    )


def revise_report(
    state: RuntimeState,
    *,
    reviser: DeterministicDraftReviser,
    binder: EvidenceCitationBinder,
) -> dict[str, object]:
    """Create the next bound draft revision within the hard limit."""

    if state.status is not RuntimeStatus.REVIEW_REVISE:
        raise ValueError("REVISION_REQUIRES_REVIEW_FINDINGS")
    if state.confirmed_requirements is None:
        raise ValueError("REVISION_REQUIRES_CONFIRMED_REQUIREMENTS")
    if state.review_rounds >= MAX_REVIEW_ROUNDS:
        raise ValueError("REVISION_LIMIT_REACHED")

    next_round = state.review_rounds + 1
    try:
        if (
            state.report_draft is None
            or state.report_draft.draft_policy_id != binder.policy.policy_id
        ):
            raise ValueError("REVISION_DRAFT_POLICY_ID_MISMATCH")
        proposal = reviser.revise(next_review_round=next_round)
        draft = binder.bind(
            proposal=proposal,
            confirmed_requirements=state.confirmed_requirements,
            available_evidence_ids=state.evidence_ids,
            revision=state.report_revision + 1,
        )
    except ValueError:
        errors = (
            *state.errors,
            _safe_error(
                code="invalid-revised-draft",
                summary="revised draft failed evidence or scope checks",
                retryable=False,
                node=RuntimeNode.REVISE_REPORT,
            ),
        )
        return _validated_update(
            state,
            status=RuntimeStatus.FAILED.value,
            current_node=RuntimeNode.END.value,
            last_review_result=None,
            errors=errors,
        )

    return _validated_update(
        state,
        status=RuntimeStatus.REVIEW_READY.value,
        current_node=RuntimeNode.REVIEW_REPORT.value,
        report_draft=draft.model_dump(mode="json"),
        report_revision=draft.revision,
        report_hash=hash_report_draft(draft),
        review_rounds=next_round,
        last_review_result=None,
    )


def _route_after_tool(
    state: RuntimeState,
) -> Literal["success", "retry", "failed"]:
    if state.status is RuntimeStatus.EVIDENCE_READY:
        return "success"
    if state.status is RuntimeStatus.TOOL_RETRY:
        return "retry"
    if state.status is RuntimeStatus.FAILED:
        return "failed"
    raise ValueError("TOOL_EXECUTION_INVALID_ROUTE")


def _route_after_evidence_tool(
    state: RuntimeState,
) -> Literal["assess", "retry", "failed"]:
    if state.status is RuntimeStatus.EVIDENCE_PENDING_ASSESSMENT:
        return "assess"
    if state.status is RuntimeStatus.TOOL_RETRY:
        return "retry"
    if state.status is RuntimeStatus.FAILED:
        return "failed"
    raise ValueError("EVIDENCE_TOOL_INVALID_ROUTE")


def _route_after_assessment(
    state: RuntimeState,
) -> Literal["retrieve", "sufficient", "failed"]:
    if state.status is RuntimeStatus.EVIDENCE_NEEDS_MORE:
        return "retrieve"
    if state.status is RuntimeStatus.EVIDENCE_SUFFICIENT:
        return "sufficient"
    if state.status is RuntimeStatus.FAILED:
        return "failed"
    raise ValueError("EVIDENCE_ASSESSMENT_INVALID_ROUTE")


def _route_after_draft(
    state: RuntimeState,
) -> Literal["review", "stop"]:
    if state.status is RuntimeStatus.REVIEW_READY:
        return "review"
    if state.status in {RuntimeStatus.DRAFTED, RuntimeStatus.FAILED}:
        return "stop"
    raise ValueError("DRAFT_INVALID_ROUTE")


def _route_after_review(
    state: RuntimeState,
) -> Literal["revise", "stop"]:
    if state.status is RuntimeStatus.REVIEW_REVISE:
        return "revise"
    if state.status in {RuntimeStatus.REVIEWED, RuntimeStatus.FAILED}:
        return "stop"
    raise ValueError("REVIEW_INVALID_ROUTE")


def _route_after_revision(
    state: RuntimeState,
) -> Literal["review", "stop"]:
    if state.status is RuntimeStatus.REVIEW_READY:
        return "review"
    if state.status is RuntimeStatus.FAILED:
        return "stop"
    raise ValueError("REVISION_INVALID_ROUTE")


def _requirements_builder(plan_node: object) -> StateGraph:
    builder = StateGraph(RuntimeState)
    builder.add_node("validate_request", validate_request)
    builder.add_node("confirm_requirements", confirm_requirements)
    builder.add_node(
        "await_human_requirements",
        await_human_requirements,
    )
    builder.add_node("plan_research", plan_node)

    builder.add_edge(START, "validate_request")
    builder.add_edge("validate_request", "confirm_requirements")
    builder.add_edge(
        "confirm_requirements",
        "await_human_requirements",
    )
    builder.add_conditional_edges(
        "await_human_requirements",
        _route_after_human,
        {
            "plan": "plan_research",
            "edit": "validate_request",
            "terminal": END,
        },
    )
    return builder


def build_requirements_graph(checkpointer: BaseCheckpointSaver):
    """Compile the requirements-only graph from the previous stage."""

    builder = _requirements_builder(plan_research)
    builder.add_edge("plan_research", END)
    return builder.compile(checkpointer=checkpointer)


def build_tool_execution_graph(
    *,
    checkpointer: BaseCheckpointSaver,
    tool_call: ToolCall,
    executor: DeterministicFakeToolExecutor,
):
    """Compile the next explicit slice through safe tool execution."""

    builder = _requirements_builder(
        partial(plan_tool_call, tool_call=tool_call)
    )
    builder.add_node(
        "execute_tools",
        partial(execute_tools, executor=executor),
    )
    builder.add_node("retry_tool", retry_tool)
    builder.add_edge("plan_research", "execute_tools")
    builder.add_conditional_edges(
        "execute_tools",
        _route_after_tool,
        {
            "success": END,
            "retry": "retry_tool",
            "failed": END,
        },
    )
    builder.add_edge("retry_tool", "execute_tools")
    return builder.compile(checkpointer=checkpointer)


def _evidence_builder(
    *,
    tool_calls: tuple[ToolCall, ToolCall],
    executor: DeterministicFakeToolExecutor,
    assessor: DeterministicEvidenceAssessor,
) -> StateGraph:
    """Build shared evidence nodes without choosing the post-assessment stop."""

    if len(tool_calls) != MAX_RETRIEVAL_ROUNDS:
        raise ValueError("EVIDENCE_GRAPH_REQUIRES_TWO_FROZEN_TOOL_CALLS")

    builder = _requirements_builder(
        partial(
            plan_evidence_round,
            tool_calls=tool_calls,
            assessor=assessor,
        )
    )
    builder.add_node(
        "execute_tools",
        partial(
            execute_tools,
            executor=executor,
            continue_to_assessment=True,
        ),
    )
    builder.add_node("retry_tool", retry_tool)
    builder.add_node(
        "assess_evidence",
        partial(assess_evidence, assessor=assessor),
    )
    builder.add_edge("plan_research", "execute_tools")
    builder.add_conditional_edges(
        "execute_tools",
        _route_after_evidence_tool,
        {
            "assess": "assess_evidence",
            "retry": "retry_tool",
            "failed": END,
        },
    )
    builder.add_edge("retry_tool", "execute_tools")
    return builder


def build_evidence_assessment_graph(
    *,
    checkpointer: BaseCheckpointSaver,
    tool_calls: tuple[ToolCall, ToolCall],
    executor: DeterministicFakeToolExecutor,
    assessor: DeterministicEvidenceAssessor,
):
    """Compile the bounded evidence-only slice from the previous stage."""

    builder = _evidence_builder(
        tool_calls=tool_calls,
        executor=executor,
        assessor=assessor,
    )
    builder.add_conditional_edges(
        "assess_evidence",
        _route_after_assessment,
        {
            "retrieve": "plan_research",
            "sufficient": END,
            "failed": END,
        },
    )
    return builder.compile(checkpointer=checkpointer)


def build_draft_report_graph(
    *,
    checkpointer: BaseCheckpointSaver,
    tool_calls: tuple[ToolCall, ToolCall],
    executor: DeterministicFakeToolExecutor,
    assessor: DeterministicEvidenceAssessor,
    writer: DeterministicFakeWriter,
    binder: EvidenceCitationBinder,
):
    """Compile the evidence gate plus one safe deterministic draft node."""

    builder = _evidence_builder(
        tool_calls=tool_calls,
        executor=executor,
        assessor=assessor,
    )
    builder.add_node(
        "draft_report",
        partial(draft_report, writer=writer, binder=binder),
    )
    builder.add_conditional_edges(
        "assess_evidence",
        _route_after_assessment,
        {
            "retrieve": "plan_research",
            "sufficient": "draft_report",
            "failed": END,
        },
    )
    builder.add_edge("draft_report", END)
    return builder.compile(checkpointer=checkpointer)


def build_report_review_graph(
    *,
    checkpointer: BaseCheckpointSaver,
    tool_calls: tuple[ToolCall, ToolCall],
    executor: DeterministicFakeToolExecutor,
    assessor: DeterministicEvidenceAssessor,
    writer: DeterministicFakeWriter,
    binder: EvidenceCitationBinder,
    reviewer: DeterministicReportReviewer,
    reviser: DeterministicDraftReviser,
):
    """Compile evidence, drafting, and at most two automatic revisions."""

    builder = _evidence_builder(
        tool_calls=tool_calls,
        executor=executor,
        assessor=assessor,
    )
    builder.add_node(
        "draft_report",
        partial(
            draft_report,
            writer=writer,
            binder=binder,
            continue_to_review=True,
            review_policy_id=reviewer.policy.policy_id,
        ),
    )
    builder.add_node(
        "review_report",
        partial(review_report, reviewer=reviewer),
    )
    builder.add_node(
        "revise_report",
        partial(revise_report, reviser=reviser, binder=binder),
    )
    builder.add_conditional_edges(
        "assess_evidence",
        _route_after_assessment,
        {
            "retrieve": "plan_research",
            "sufficient": "draft_report",
            "failed": END,
        },
    )
    builder.add_conditional_edges(
        "draft_report",
        _route_after_draft,
        {
            "review": "review_report",
            "stop": END,
        },
    )
    builder.add_conditional_edges(
        "review_report",
        _route_after_review,
        {
            "revise": "revise_report",
            "stop": END,
        },
    )
    builder.add_conditional_edges(
        "revise_report",
        _route_after_revision,
        {
            "review": "review_report",
            "stop": END,
        },
    )
    return builder.compile(checkpointer=checkpointer)
