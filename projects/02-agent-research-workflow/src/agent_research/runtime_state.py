"""Versioned, checkpoint-safe contracts for the minimal workflow runtime."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from agent_research.models import (
    EvidenceId,
    HumanActionKind,
    Identifier,
    ResearchInput,
    Sha256,
    StrictModel,
    ToolOutcomeKind,
)
from agent_research.tool_contracts import (
    MAX_TOOL_ATTEMPTS,
    SOURCE_SNAPSHOT_V1,
    SourceSnapshotIdV1,
    ToolCall,
    ToolResult,
    compute_tool_call_key,
)


MAX_CONFIRMATION_REVISIONS = 32
MAX_RETRIEVAL_ROUNDS = 2
MAX_REVIEW_ROUNDS = 2
MAX_HUMAN_REVISIONS = 2
MAX_REPORT_REVISIONS = 32

_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(authorization\s*:|cookie\s*:|set-cookie\s*:|"
    r"bearer\s+[a-z0-9._~+/=-]{8,}|"
    r"(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret)\s*[:=]\s*\S+)"
)


class RuntimeStatus(StrEnum):
    NEW = "NEW"
    VALIDATED = "VALIDATED"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    REQUIREMENTS_CONFIRMED = "REQUIREMENTS_CONFIRMED"
    PLANNED = "PLANNED"
    TOOL_READY = "TOOL_READY"
    TOOL_RETRY = "TOOL_RETRY"
    EVIDENCE_READY = "EVIDENCE_READY"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class RuntimeNode(StrEnum):
    VALIDATE_REQUEST = "validate_request"
    CONFIRM_REQUIREMENTS = "confirm_requirements"
    AWAIT_HUMAN_REQUIREMENTS = "await_human_requirements"
    PLAN_RESEARCH = "plan_research"
    EXECUTE_TOOLS = "execute_tools"
    RETRY_TOOL = "retry_tool"
    END = "end"


class MissingRequirement(StrEnum):
    CANDIDATES = "candidates"
    DIMENSIONS = "dimensions"


class SafeStateError(StrictModel):
    """Stable, redacted error data allowed in checkpoints."""

    code: Identifier
    node: RuntimeNode
    safe_summary: Annotated[str, Field(min_length=1, max_length=240)]
    retryable: bool = False

    @field_validator("safe_summary")
    @classmethod
    def reject_secret_shaped_text(cls, value: str) -> str:
        if _SENSITIVE_VALUE_PATTERN.search(value):
            raise ValueError("safe_summary must not contain secret-shaped text")
        return value


class RuntimeState(StrictModel):
    """Complete business state persisted by LangGraph checkpoints."""

    schema_version: Literal["runtime-state-v1"] = "runtime-state-v1"
    graph_version: Literal["requirements-confirmation-v1"] = (
        "requirements-confirmation-v1"
    )
    run_id: Identifier
    thread_id: Identifier
    source_snapshot_id: SourceSnapshotIdV1 = SOURCE_SNAPSHOT_V1
    status: RuntimeStatus = RuntimeStatus.NEW
    current_node: RuntimeNode = RuntimeNode.VALIDATE_REQUEST
    raw_request: ResearchInput
    confirmed_requirements: ResearchInput | None = None
    human_confirmation_revision: Annotated[
        int,
        Field(ge=0, le=MAX_CONFIRMATION_REVISIONS),
    ] = 0
    confirmation_request_hash: Sha256 | None = None
    missing_requirements: Annotated[
        tuple[MissingRequirement, ...],
        Field(max_length=2),
    ] = ()
    last_human_action: HumanActionKind | None = None
    pending_tool_call: ToolCall | None = None
    last_tool_result: ToolResult | None = None
    tool_call_budget: Annotated[
        int,
        Field(ge=1, le=MAX_TOOL_ATTEMPTS),
    ] = MAX_TOOL_ATTEMPTS
    tool_attempts: Annotated[int, Field(ge=0, le=MAX_TOOL_ATTEMPTS)] = 0
    retrieval_rounds: Annotated[
        int,
        Field(ge=0, le=MAX_RETRIEVAL_ROUNDS),
    ] = 0
    review_rounds: Annotated[int, Field(ge=0, le=MAX_REVIEW_ROUNDS)] = 0
    human_revision_count: Annotated[
        int,
        Field(ge=0, le=MAX_HUMAN_REVISIONS),
    ] = 0
    evidence_ids: Annotated[tuple[EvidenceId, ...], Field(max_length=128)] = ()
    errors: Annotated[tuple[SafeStateError, ...], Field(max_length=20)] = ()
    report_revision: Annotated[
        int,
        Field(ge=0, le=MAX_REPORT_REVISIONS),
    ] = 0
    report_hash: Sha256 | None = None
    plan_id: Sha256 | None = None
    artifact_id: Sha256 | None = None
    idempotency_key: Sha256 | None = None

    @field_validator("raw_request", "confirmed_requirements")
    @classmethod
    def reject_secret_shaped_request_text(
        cls,
        value: ResearchInput | None,
    ) -> ResearchInput | None:
        if value is None:
            return value
        persisted_text = (
            value.research_question,
            value.audience,
            *value.constraints,
        )
        if any(_SENSITIVE_VALUE_PATTERN.search(text) for text in persisted_text):
            raise ValueError(
                "checkpoint request must not contain secret-shaped text"
            )
        return value

    @model_validator(mode="after")
    def validate_state_consistency(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        if self.tool_attempts > self.tool_call_budget:
            raise ValueError("tool_attempts cannot exceed tool_call_budget")

        confirmed = self.confirmed_requirements is not None
        hashed = self.confirmation_request_hash is not None
        if confirmed != hashed and self.status in {
            RuntimeStatus.REQUIREMENTS_CONFIRMED,
            RuntimeStatus.PLANNED,
        }:
            raise ValueError(
                "confirmed requirements require their confirmation hash"
            )

        if self.status is RuntimeStatus.NEEDS_HUMAN:
            if self.current_node is not RuntimeNode.AWAIT_HUMAN_REQUIREMENTS:
                raise ValueError("NEEDS_HUMAN must wait at the human node")
            if self.human_confirmation_revision < 1 or not hashed:
                raise ValueError(
                    "NEEDS_HUMAN requires a revision and request hash"
                )

        if self.status in {
            RuntimeStatus.REQUIREMENTS_CONFIRMED,
            RuntimeStatus.PLANNED,
        } and not confirmed:
            raise ValueError("confirmed or planned state requires requirements")

        if self.status is RuntimeStatus.PLANNED and self.plan_id is None:
            raise ValueError("PLANNED requires plan_id")

        tool_statuses = {
            RuntimeStatus.TOOL_READY,
            RuntimeStatus.TOOL_RETRY,
            RuntimeStatus.EVIDENCE_READY,
        }
        if self.status in tool_statuses:
            if self.pending_tool_call is None:
                raise ValueError("tool state requires pending_tool_call")
            if self.confirmed_requirements is None or self.plan_id is None:
                raise ValueError("tool state requires confirmed plan")

        if self.last_tool_result is not None:
            if self.pending_tool_call is None:
                raise ValueError("tool result requires pending_tool_call")
            expected_key = compute_tool_call_key(
                self.pending_tool_call,
                self.source_snapshot_id,
            )
            if self.last_tool_result.logical_call_key != expected_key:
                raise ValueError("tool result logical_call_key mismatch")

        if self.status is RuntimeStatus.TOOL_READY:
            if self.current_node is not RuntimeNode.EXECUTE_TOOLS:
                raise ValueError("TOOL_READY must enter execute_tools")

        if self.status is RuntimeStatus.TOOL_RETRY:
            if self.current_node is not RuntimeNode.RETRY_TOOL:
                raise ValueError("TOOL_RETRY must enter retry_tool")
            if (
                self.last_tool_result is None
                or self.last_tool_result.outcome
                is not ToolOutcomeKind.TRANSIENT_ERROR
                or self.tool_attempts >= self.tool_call_budget
            ):
                raise ValueError(
                    "TOOL_RETRY requires retryable result and remaining budget"
                )

        if self.status is RuntimeStatus.EVIDENCE_READY:
            if self.current_node is not RuntimeNode.END:
                raise ValueError("EVIDENCE_READY must stop at end")
            if (
                self.last_tool_result is None
                or self.last_tool_result.outcome is not ToolOutcomeKind.SUCCESS
            ):
                raise ValueError("EVIDENCE_READY requires successful tool result")
            if not set(self.last_tool_result.evidence_ids) <= set(
                self.evidence_ids
            ):
                raise ValueError("successful evidence must enter runtime state")

        if self.status in {
            RuntimeStatus.REJECTED,
            RuntimeStatus.CANCELLED,
            RuntimeStatus.FAILED,
        } and self.current_node is not RuntimeNode.END:
            raise ValueError("terminal state must use the end node")

        if self.report_hash is None and self.report_revision != 0:
            raise ValueError("report_revision requires report_hash")
        if (
            self.artifact_id is not None or self.idempotency_key is not None
        ) and self.report_hash is None:
            raise ValueError("artifact fields require report_hash")
        return self


class RequirementsPause(StrictModel):
    """Serializable value shown to the human at the requirements gate."""

    schema_version: Literal["requirements-pause-v1"] = "requirements-pause-v1"
    run_id: Identifier
    thread_id: Identifier
    revision: Annotated[int, Field(ge=1, le=MAX_CONFIRMATION_REVISIONS)]
    request_hash: Sha256
    missing_requirements: tuple[MissingRequirement, ...]
    request: ResearchInput


class RequirementsDecision(StrictModel):
    """Revision-bound human response accepted when resuming an interrupt."""

    schema_version: Literal["requirements-decision-v1"] = (
        "requirements-decision-v1"
    )
    run_id: Identifier
    thread_id: Identifier
    expected_revision: Annotated[
        int,
        Field(ge=1, le=MAX_CONFIRMATION_REVISIONS),
    ]
    expected_request_hash: Sha256
    action: HumanActionKind
    edited_request: ResearchInput | None = None

    @model_validator(mode="after")
    def validate_action_payload(self) -> Self:
        allowed = {
            HumanActionKind.APPROVE,
            HumanActionKind.EDIT,
            HumanActionKind.REJECT,
            HumanActionKind.CANCEL,
        }
        if self.action not in allowed:
            raise ValueError("unsupported requirements action")
        if self.action is HumanActionKind.EDIT:
            if self.edited_request is None:
                raise ValueError("edit requires edited_request")
        elif self.edited_request is not None:
            raise ValueError("edited_request is only valid for edit")
        return self


def hash_research_input(request: ResearchInput) -> str:
    """Return a deterministic hash for binding human decisions to one revision."""

    canonical = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
