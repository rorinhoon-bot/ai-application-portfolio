"""Safe runtime-only node events and machine-readable run summaries."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self

from langgraph.errors import GraphInterrupt
from pydantic import Field, model_validator

from agent_research.models import (
    HumanActionKind,
    Identifier,
    Sha256,
    StrictModel,
    ToolOutcomeKind,
)
from agent_research.runtime_state import RuntimeNode, RuntimeState, RuntimeStatus
from agent_research.tool_contracts import ToolResult


MAX_NODE_EVENTS = 512
MAX_OBSERVED_TIME_NS = 9_223_372_036_854_775_807


class Clock(Protocol):
    """Runtime clock boundary; clock objects never enter checkpoint state."""

    def now_ns(self) -> int:
        """Return a monotonic nanosecond reading."""


class SystemMonotonicClock:
    """Production runtime clock backed by time.monotonic_ns()."""

    def now_ns(self) -> int:
        return time.monotonic_ns()


class DeterministicClock:
    """Fixed-step clock for repeatable offline tests and demo summaries."""

    def __init__(
        self,
        *,
        initial_ns: int = 0,
        step_ns: int = 1_000_000,
    ) -> None:
        if initial_ns < 0:
            raise ValueError("CLOCK_INITIAL_NS_MUST_BE_NON_NEGATIVE")
        if step_ns <= 0:
            raise ValueError("CLOCK_STEP_NS_MUST_BE_POSITIVE")
        self._current_ns = initial_ns
        self._step_ns = step_ns

    def now_ns(self) -> int:
        value = self._current_ns
        self._current_ns += self._step_ns
        return value


class NodeOutcome(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    INTERRUPTED = "INTERRUPTED"
    FAILED = "FAILED"


class NodeEvent(StrictModel):
    """One payload-free node attempt observed outside business state."""

    schema_version: Literal["node-event-v1"] = "node-event-v1"
    sequence: Annotated[int, Field(ge=1, le=MAX_NODE_EVENTS)]
    node: RuntimeNode
    outcome: NodeOutcome
    started_offset_ns: Annotated[
        int,
        Field(ge=0, le=MAX_OBSERVED_TIME_NS),
    ]
    duration_ns: Annotated[
        int,
        Field(ge=0, le=MAX_OBSERVED_TIME_NS),
    ]
    status_before: RuntimeStatus
    status_after: RuntimeStatus | None = None
    human_action: HumanActionKind | None = None
    tool_outcome: ToolOutcomeKind | None = None
    error_code: Identifier | None = None

    @model_validator(mode="after")
    def validate_event_shape(self) -> Self:
        human_nodes = {
            RuntimeNode.AWAIT_HUMAN_REQUIREMENTS,
            RuntimeNode.AWAIT_HUMAN_REPORT,
        }
        if self.human_action is not None and self.node not in human_nodes:
            raise ValueError("human_action requires a human-wait node")
        if (
            self.tool_outcome is not None
            and self.node is not RuntimeNode.EXECUTE_TOOLS
        ):
            raise ValueError("tool_outcome requires execute_tools")
        if self.outcome is NodeOutcome.SUCCEEDED:
            if self.status_after is None:
                raise ValueError("successful node event requires status_after")
        elif self.human_action is not None or self.tool_outcome is not None:
            raise ValueError(
                "interrupted or failed event cannot contain completed output"
            )
        if (
            self.outcome is NodeOutcome.INTERRUPTED
            and self.node not in human_nodes
        ):
            raise ValueError("only human-wait nodes may be interrupted")
        if (
            self.outcome is NodeOutcome.FAILED
            and self.error_code != "node-exception"
        ):
            raise ValueError("failed node event requires stable error code")
        if (
            self.outcome is not NodeOutcome.FAILED
            and self.error_code == "node-exception"
        ):
            raise ValueError("node-exception is only valid for failed events")
        if (
            self.outcome is not NodeOutcome.FAILED
            and self.error_code is not None
            and self.node is not RuntimeNode.EXECUTE_TOOLS
        ):
            raise ValueError("non-exception error_code requires execute_tools")
        if self.tool_outcome is ToolOutcomeKind.SUCCESS:
            if self.error_code is not None:
                raise ValueError("successful tool outcome cannot have error_code")
        elif self.tool_outcome is not None and self.error_code is None:
            raise ValueError("failed tool outcome requires error_code")
        return self


class RunSummary(StrictModel):
    """Deterministic, payload-free summary derived from events and final state."""

    schema_version: Literal["run-summary-v1"] = "run-summary-v1"
    summary_hash: Sha256
    run_id: Identifier
    thread_id: Identifier
    graph_version: Identifier
    source_snapshot_id: Sha256
    final_status: RuntimeStatus
    current_node: RuntimeNode
    node_event_count: Annotated[int, Field(ge=1, le=MAX_NODE_EVENTS)]
    interrupted_node_count: Annotated[int, Field(ge=0, le=MAX_NODE_EVENTS)]
    observed_node_duration_ns: Annotated[
        int,
        Field(ge=0, le=MAX_OBSERVED_TIME_NS),
    ]
    tool_attempt_count: Annotated[int, Field(ge=0, le=12)]
    retry_count: Annotated[int, Field(ge=0, le=12)]
    retrieval_rounds: Annotated[int, Field(ge=0, le=2)]
    review_rounds: Annotated[int, Field(ge=0, le=2)]
    review_attempt_count: Annotated[int, Field(ge=0, le=32)]
    automatic_revision_count: Annotated[int, Field(ge=0, le=16)]
    export_attempt_count: Annotated[int, Field(ge=0, le=8)]
    human_decision_count: Annotated[int, Field(ge=0, le=64)]
    human_actions: Annotated[
        tuple[HumanActionKind, ...],
        Field(max_length=64),
    ] = ()
    human_revision_count: Annotated[int, Field(ge=0, le=2)]
    model_call_count: Literal[0] = 0
    input_token_count: Literal[0] = 0
    output_token_count: Literal[0] = 0
    known_cost_microunits: Literal[0] = 0
    error_codes: Annotated[tuple[Identifier, ...], Field(max_length=20)] = ()
    report_revision: Annotated[int, Field(ge=0, le=32)]
    report_hash: Sha256 | None = None
    artifact_id: Sha256 | None = None
    events: Annotated[
        tuple[NodeEvent, ...],
        Field(min_length=1, max_length=MAX_NODE_EVENTS),
    ]

    @model_validator(mode="after")
    def validate_summary_shape(self) -> Self:
        if self.node_event_count != len(self.events):
            raise ValueError("node_event_count does not match events")
        if tuple(event.sequence for event in self.events) != tuple(
            range(1, len(self.events) + 1)
        ):
            raise ValueError("node event sequence must be contiguous")
        if self.interrupted_node_count != sum(
            event.outcome is NodeOutcome.INTERRUPTED for event in self.events
        ):
            raise ValueError("interrupted_node_count does not match events")
        if self.observed_node_duration_ns != sum(
            event.duration_ns for event in self.events
        ):
            raise ValueError("observed duration does not match events")
        observed_actions = tuple(
            event.human_action
            for event in self.events
            if event.human_action is not None
        )
        if self.human_actions != observed_actions:
            raise ValueError("human_actions do not match events")
        if self.human_decision_count != len(self.human_actions):
            raise ValueError("human_decision_count does not match actions")
        if self.retry_count != sum(
            event.node is RuntimeNode.RETRY_TOOL
            and event.outcome is NodeOutcome.SUCCEEDED
            for event in self.events
        ):
            raise ValueError("retry_count does not match events")
        if self.review_attempt_count != sum(
            event.node is RuntimeNode.REVIEW_REPORT
            and event.outcome is NodeOutcome.SUCCEEDED
            for event in self.events
        ):
            raise ValueError("review_attempt_count does not match events")
        if self.automatic_revision_count != sum(
            event.node is RuntimeNode.REVISE_REPORT
            and event.outcome is NodeOutcome.SUCCEEDED
            for event in self.events
        ):
            raise ValueError("automatic_revision_count does not match events")
        if self.export_attempt_count != sum(
            event.node is RuntimeNode.EXPORT_REPORT
            and event.outcome is NodeOutcome.SUCCEEDED
            for event in self.events
        ):
            raise ValueError("export_attempt_count does not match events")
        if self.summary_hash != compute_run_summary_hash(self):
            raise ValueError("summary_hash does not match summary content")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class RunObserver:
    """Runtime collector that records safe node metadata, never node payloads."""

    def __init__(
        self,
        *,
        run_id: str,
        thread_id: str,
        clock: Clock | None = None,
    ) -> None:
        self.run_id = run_id
        self.thread_id = thread_id
        self._clock = clock or SystemMonotonicClock()
        self._origin_ns = self._clock.now_ns()
        self._events: list[NodeEvent] = []

    @property
    def events(self) -> tuple[NodeEvent, ...]:
        return tuple(self._events)

    def observe(
        self,
        state: RuntimeState,
        *,
        node: RuntimeNode,
        operation: Callable[[RuntimeState], dict[str, object]],
    ) -> dict[str, object]:
        if state.run_id != self.run_id or state.thread_id != self.thread_id:
            raise ValueError("OBSERVER_RUN_IDENTITY_MISMATCH")
        if len(self._events) >= MAX_NODE_EVENTS:
            raise ValueError("OBSERVER_EVENT_LIMIT_REACHED")

        started_ns = self._clock.now_ns()
        try:
            update = operation(state)
        except GraphInterrupt:
            ended_ns = self._clock.now_ns()
            self._append(
                node=node,
                outcome=NodeOutcome.INTERRUPTED,
                started_ns=started_ns,
                ended_ns=ended_ns,
                status_before=state.status,
                status_after=state.status,
            )
            raise
        except Exception:
            ended_ns = self._clock.now_ns()
            self._append(
                node=node,
                outcome=NodeOutcome.FAILED,
                started_ns=started_ns,
                ended_ns=ended_ns,
                status_before=state.status,
                error_code="node-exception",
            )
            raise

        ended_ns = self._clock.now_ns()
        status_after = RuntimeStatus(update.get("status", state.status))
        human_action = update.get("last_human_action")
        if human_action is None:
            human_action = update.get("last_report_action")
        tool_result = update.get("last_tool_result")
        normalized_tool_result = (
            ToolResult.model_validate(tool_result)
            if tool_result is not None
            else None
        )
        self._append(
            node=node,
            outcome=NodeOutcome.SUCCEEDED,
            started_ns=started_ns,
            ended_ns=ended_ns,
            status_before=state.status,
            status_after=status_after,
            human_action=(
                HumanActionKind(human_action)
                if human_action is not None
                else None
            ),
            tool_outcome=(
                normalized_tool_result.outcome
                if normalized_tool_result is not None
                else None
            ),
            error_code=(
                normalized_tool_result.error_code
                if normalized_tool_result is not None
                else None
            ),
        )
        return update

    def _append(
        self,
        *,
        node: RuntimeNode,
        outcome: NodeOutcome,
        started_ns: int,
        ended_ns: int,
        status_before: RuntimeStatus,
        status_after: RuntimeStatus | None = None,
        human_action: HumanActionKind | None = None,
        tool_outcome: ToolOutcomeKind | None = None,
        error_code: str | None = None,
    ) -> None:
        if ended_ns < started_ns or started_ns < self._origin_ns:
            raise ValueError("OBSERVER_CLOCK_NOT_MONOTONIC")
        self._events.append(
            NodeEvent(
                sequence=len(self._events) + 1,
                node=node,
                outcome=outcome,
                started_offset_ns=started_ns - self._origin_ns,
                duration_ns=ended_ns - started_ns,
                status_before=status_before,
                status_after=status_after,
                human_action=human_action,
                tool_outcome=tool_outcome,
                error_code=error_code,
            )
        )


def observed_node(
    *,
    node: RuntimeNode,
    operation: Callable[[RuntimeState], dict[str, object]],
    observer: RunObserver | None,
) -> Callable[[RuntimeState], dict[str, object]]:
    """Return original node or a runtime-observed wrapper."""

    if observer is None:
        return operation

    def wrapped(state: RuntimeState) -> dict[str, object]:
        return observer.observe(state, node=node, operation=operation)

    return wrapped


def compute_run_summary_hash(summary: RunSummary) -> str:
    payload = summary.model_dump(mode="json")
    payload.pop("summary_hash")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_run_summary(
    *,
    state: RuntimeState,
    observer: RunObserver,
) -> RunSummary:
    if state.run_id != observer.run_id or state.thread_id != observer.thread_id:
        raise ValueError("RUN_SUMMARY_IDENTITY_MISMATCH")
    events = observer.events
    if not events:
        raise ValueError("RUN_SUMMARY_REQUIRES_NODE_EVENTS")
    human_actions = tuple(
        event.human_action
        for event in events
        if event.human_action is not None
    )
    payload = {
        "summary_hash": "0" * 64,
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "graph_version": state.graph_version,
        "source_snapshot_id": state.source_snapshot_id,
        "final_status": state.status,
        "current_node": state.current_node,
        "node_event_count": len(events),
        "interrupted_node_count": sum(
            event.outcome is NodeOutcome.INTERRUPTED for event in events
        ),
        "observed_node_duration_ns": sum(
            event.duration_ns for event in events
        ),
        "tool_attempt_count": state.tool_attempts,
        "retry_count": sum(
            event.node is RuntimeNode.RETRY_TOOL
            and event.outcome is NodeOutcome.SUCCEEDED
            for event in events
        ),
        "retrieval_rounds": state.retrieval_rounds,
        "review_rounds": state.review_rounds,
        "review_attempt_count": sum(
            event.node is RuntimeNode.REVIEW_REPORT
            and event.outcome is NodeOutcome.SUCCEEDED
            for event in events
        ),
        "automatic_revision_count": sum(
            event.node is RuntimeNode.REVISE_REPORT
            and event.outcome is NodeOutcome.SUCCEEDED
            for event in events
        ),
        "export_attempt_count": sum(
            event.node is RuntimeNode.EXPORT_REPORT
            and event.outcome is NodeOutcome.SUCCEEDED
            for event in events
        ),
        "human_decision_count": len(human_actions),
        "human_actions": human_actions,
        "human_revision_count": state.human_revision_count,
        "error_codes": tuple(error.code for error in state.errors),
        "report_revision": state.report_revision,
        "report_hash": state.report_hash,
        "artifact_id": state.artifact_id,
        "events": events,
    }
    draft = RunSummary.model_construct(**payload)
    payload["summary_hash"] = compute_run_summary_hash(draft)
    return RunSummary.model_validate(payload)
