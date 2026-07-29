"""Minimal LangGraph for requirement validation and human confirmation."""

from __future__ import annotations

import hashlib
from functools import partial
from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_research.fake_tools import DeterministicFakeToolExecutor
from agent_research.models import (
    HumanActionKind,
    ResearchInput,
    ToolOutcomeKind,
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
        status=RuntimeStatus.TOOL_READY.value,
        current_node=RuntimeNode.EXECUTE_TOOLS.value,
        plan_id=plan_id,
        pending_tool_call=tool_call.model_dump(mode="json"),
        last_tool_result=None,
        tool_attempts=0,
        retrieval_rounds=retrieval_rounds,
    )


def _safe_error(
    *,
    code: str,
    summary: str,
    retryable: bool,
) -> dict[str, object]:
    return SafeStateError(
        code=code,
        node=RuntimeNode.EXECUTE_TOOLS,
        safe_summary=summary,
        retryable=retryable,
    ).model_dump(mode="json")


def execute_tools(
    state: RuntimeState,
    *,
    executor: DeterministicFakeToolExecutor,
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
            status=RuntimeStatus.EVIDENCE_READY.value,
            current_node=RuntimeNode.END.value,
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
