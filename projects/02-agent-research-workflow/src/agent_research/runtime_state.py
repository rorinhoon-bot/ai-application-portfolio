"""Versioned, checkpoint-safe contracts for the minimal workflow runtime."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from agent_research.evidence_assessment import (
    EvidenceAssessment,
    EvidenceAssessmentStatus,
)
from agent_research.models import (
    EvidenceId,
    HumanActionKind,
    Identifier,
    ResearchInput,
    Sha256,
    StrictModel,
    ToolOutcomeKind,
)
from agent_research.report_drafting import (
    MAX_REPORT_REVISIONS,
    ReportDraft,
    hash_report_draft,
)
from agent_research.report_approval import (
    MAX_HUMAN_REPORT_REVISIONS,
    MAX_REPORT_CONFIRMATION_REVISIONS,
)
from agent_research.report_review import (
    MAX_REVIEW_ROUNDS,
    ReviewOutcome,
    ReviewResult,
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
MAX_HUMAN_REVISIONS = MAX_HUMAN_REPORT_REVISIONS
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
    EVIDENCE_PENDING_ASSESSMENT = "EVIDENCE_PENDING_ASSESSMENT"
    EVIDENCE_NEEDS_MORE = "EVIDENCE_NEEDS_MORE"
    EVIDENCE_SUFFICIENT = "EVIDENCE_SUFFICIENT"
    DRAFTED = "DRAFTED"
    REVIEW_READY = "REVIEW_READY"
    REVIEW_REVISE = "REVIEW_REVISE"
    REVIEWED = "REVIEWED"
    REPORT_CONFIRMATION_READY = "REPORT_CONFIRMATION_READY"
    REPORT_NEEDS_HUMAN = "REPORT_NEEDS_HUMAN"
    REPORT_REVISION_REQUESTED = "REPORT_REVISION_REQUESTED"
    REPORT_APPROVED = "REPORT_APPROVED"
    REPORT_REJECTED = "REPORT_REJECTED"
    REPORT_CANCELLED = "REPORT_CANCELLED"
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
    ASSESS_EVIDENCE = "assess_evidence"
    DRAFT_REPORT = "draft_report"
    REVIEW_REPORT = "review_report"
    REVISE_REPORT = "revise_report"
    CONFIRM_REPORT = "confirm_report"
    AWAIT_HUMAN_REPORT = "await_human_report"
    APPLY_HUMAN_REPORT_REVISION = "apply_human_report_revision"
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
    graph_version: Literal[
        "requirements-confirmation-v1",
        "tool-execution-v1",
        "evidence-assessment-v1",
        "draft-report-v1",
        "report-review-v1",
        "report-confirmation-v1",
    ] = (
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
    evidence_policy_id: Identifier | None = None
    evidence_gaps: Annotated[
        tuple[Identifier, ...],
        Field(max_length=16),
    ] = ()
    last_evidence_assessment: EvidenceAssessment | None = None
    errors: Annotated[tuple[SafeStateError, ...], Field(max_length=20)] = ()
    report_revision: Annotated[
        int,
        Field(ge=0, le=MAX_REPORT_REVISIONS),
    ] = 0
    report_hash: Sha256 | None = None
    report_draft: ReportDraft | None = None
    review_policy_id: Identifier | None = None
    last_review_result: ReviewResult | None = None
    report_confirmation_revision: Annotated[
        int,
        Field(ge=0, le=MAX_REPORT_CONFIRMATION_REVISIONS),
    ] = 0
    last_report_action: HumanActionKind | None = None
    approved_report_revision: Annotated[
        int | None,
        Field(ge=1, le=MAX_REPORT_REVISIONS),
    ] = None
    approved_report_hash: Sha256 | None = None
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
        allowed_report_actions = {
            HumanActionKind.APPROVE,
            HumanActionKind.REQUEST_CHANGES,
            HumanActionKind.REJECT,
            HumanActionKind.CANCEL,
        }
        if (
            self.last_report_action is not None
            and self.last_report_action not in allowed_report_actions
        ):
            raise ValueError("last_report_action contains unsupported action")
        if (
            self.report_confirmation_revision > 0
            and self.graph_version != "report-confirmation-v1"
        ):
            raise ValueError(
                "report confirmation revision requires confirmation graph"
            )

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
            RuntimeStatus.EVIDENCE_PENDING_ASSESSMENT,
            RuntimeStatus.EVIDENCE_NEEDS_MORE,
            RuntimeStatus.EVIDENCE_SUFFICIENT,
            RuntimeStatus.DRAFTED,
            RuntimeStatus.REVIEW_READY,
            RuntimeStatus.REVIEW_REVISE,
            RuntimeStatus.REVIEWED,
            RuntimeStatus.REPORT_CONFIRMATION_READY,
            RuntimeStatus.REPORT_NEEDS_HUMAN,
            RuntimeStatus.REPORT_REVISION_REQUESTED,
            RuntimeStatus.REPORT_APPROVED,
            RuntimeStatus.REPORT_REJECTED,
            RuntimeStatus.REPORT_CANCELLED,
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
            if self.graph_version != "tool-execution-v1":
                raise ValueError(
                    "EVIDENCE_READY requires tool-execution graph version"
                )
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

        assessment_statuses = {
            RuntimeStatus.EVIDENCE_PENDING_ASSESSMENT,
            RuntimeStatus.EVIDENCE_NEEDS_MORE,
            RuntimeStatus.EVIDENCE_SUFFICIENT,
        }
        if self.status in assessment_statuses:
            if self.graph_version != "evidence-assessment-v1":
                raise ValueError(
                    "evidence status requires evidence-assessment graph version"
                )
            if self.evidence_policy_id is None:
                raise ValueError("evidence assessment requires policy ID")
            if self.retrieval_rounds < 1:
                raise ValueError("evidence assessment requires retrieval")

        if self.status is RuntimeStatus.EVIDENCE_PENDING_ASSESSMENT:
            if self.current_node is not RuntimeNode.ASSESS_EVIDENCE:
                raise ValueError(
                    "pending evidence assessment must enter assess_evidence"
                )

        if self.last_evidence_assessment is not None:
            assessment = self.last_evidence_assessment
            if assessment.policy_id != self.evidence_policy_id:
                raise ValueError("evidence assessment policy ID mismatch")
            if assessment.source_snapshot_id != self.source_snapshot_id:
                raise ValueError("evidence assessment snapshot mismatch")
            if assessment.retrieval_round != self.retrieval_rounds:
                raise ValueError("evidence assessment round mismatch")
            if assessment.evidence_ids != self.evidence_ids:
                raise ValueError("evidence assessment IDs mismatch")
            if assessment.gap_requirement_ids != self.evidence_gaps:
                raise ValueError("evidence assessment gaps mismatch")
            expected_runtime_statuses = {
                EvidenceAssessmentStatus.NEEDS_MORE_EVIDENCE: (
                    {RuntimeStatus.EVIDENCE_NEEDS_MORE}
                ),
                EvidenceAssessmentStatus.SUFFICIENT: (
                    {
                        RuntimeStatus.EVIDENCE_SUFFICIENT,
                        RuntimeStatus.DRAFTED,
                        RuntimeStatus.REVIEW_READY,
                        RuntimeStatus.REVIEW_REVISE,
                        RuntimeStatus.REVIEWED,
                        RuntimeStatus.REPORT_CONFIRMATION_READY,
                        RuntimeStatus.REPORT_NEEDS_HUMAN,
                        RuntimeStatus.REPORT_REVISION_REQUESTED,
                        RuntimeStatus.REPORT_APPROVED,
                        RuntimeStatus.REPORT_REJECTED,
                        RuntimeStatus.REPORT_CANCELLED,
                        RuntimeStatus.FAILED,
                    }
                ),
                EvidenceAssessmentStatus.INSUFFICIENT: {
                    RuntimeStatus.FAILED
                },
            }[assessment.status]
            if self.status not in expected_runtime_statuses:
                raise ValueError("evidence assessment status mismatch")

        if self.status is RuntimeStatus.EVIDENCE_NEEDS_MORE:
            if self.current_node is not RuntimeNode.PLAN_RESEARCH:
                raise ValueError("evidence gaps must route to plan_research")
            if (
                self.last_evidence_assessment is None
                or self.last_evidence_assessment.status
                is not EvidenceAssessmentStatus.NEEDS_MORE_EVIDENCE
            ):
                raise ValueError("evidence gaps require needs-more assessment")

        if self.status is RuntimeStatus.EVIDENCE_SUFFICIENT:
            if self.current_node is not RuntimeNode.END:
                raise ValueError("sufficient evidence must stop at end")
            if (
                self.last_evidence_assessment is None
                or self.last_evidence_assessment.status
                is not EvidenceAssessmentStatus.SUFFICIENT
            ):
                raise ValueError("sufficient state requires sufficient assessment")

        if self.status is RuntimeStatus.DRAFTED:
            if self.graph_version != "draft-report-v1":
                raise ValueError("DRAFTED requires draft-report graph version")
            if self.current_node is not RuntimeNode.END:
                raise ValueError("DRAFTED must stop at end")
            if self.report_draft is None:
                raise ValueError("DRAFTED requires report_draft")
            if self.confirmed_requirements is None:
                raise ValueError("DRAFTED requires confirmed requirements")

        review_statuses = {
            RuntimeStatus.REVIEW_READY,
            RuntimeStatus.REVIEW_REVISE,
            RuntimeStatus.REVIEWED,
            RuntimeStatus.REPORT_CONFIRMATION_READY,
            RuntimeStatus.REPORT_NEEDS_HUMAN,
            RuntimeStatus.REPORT_REVISION_REQUESTED,
            RuntimeStatus.REPORT_APPROVED,
            RuntimeStatus.REPORT_REJECTED,
            RuntimeStatus.REPORT_CANCELLED,
        }
        if self.status in review_statuses:
            if self.graph_version not in {
                "report-review-v1",
                "report-confirmation-v1",
            }:
                raise ValueError(
                    "review status requires a report graph version"
                )
            if self.report_draft is None:
                raise ValueError("review status requires report_draft")
            if self.review_policy_id is None:
                raise ValueError("review status requires review_policy_id")

        if self.status is RuntimeStatus.REVIEW_READY:
            if self.current_node is not RuntimeNode.REVIEW_REPORT:
                raise ValueError("REVIEW_READY must enter review_report")
            if self.last_review_result is not None:
                raise ValueError("REVIEW_READY must not keep stale review result")

        if self.last_review_result is not None:
            result = self.last_review_result
            if result.policy_id != self.review_policy_id:
                raise ValueError("review result policy ID mismatch")
            if result.source_snapshot_id != self.source_snapshot_id:
                raise ValueError("review result snapshot mismatch")
            if result.report_revision != self.report_revision:
                raise ValueError("review result revision mismatch")
            if result.report_hash != self.report_hash:
                raise ValueError("review result hash mismatch")
            if result.review_round != self.review_rounds:
                raise ValueError("review result round mismatch")
            expected_review_statuses = {
                ReviewOutcome.PASS: {
                    RuntimeStatus.REVIEWED,
                    RuntimeStatus.REPORT_CONFIRMATION_READY,
                    RuntimeStatus.REPORT_NEEDS_HUMAN,
                    RuntimeStatus.REPORT_REVISION_REQUESTED,
                    RuntimeStatus.REPORT_APPROVED,
                    RuntimeStatus.REPORT_REJECTED,
                    RuntimeStatus.REPORT_CANCELLED,
                    RuntimeStatus.FAILED,
                },
                ReviewOutcome.REVISE: {RuntimeStatus.REVIEW_REVISE},
                ReviewOutcome.FAIL: {RuntimeStatus.FAILED},
            }[result.outcome]
            if self.status not in expected_review_statuses:
                raise ValueError("review result status mismatch")
            if (
                result.outcome is ReviewOutcome.PASS
                and self.status is RuntimeStatus.FAILED
                and not any(
                    error.code == "human-revision-limit-exhausted"
                    for error in self.errors
                )
            ):
                raise ValueError(
                    "passing review can fail only at human revision limit"
                )

        if self.status is RuntimeStatus.REVIEW_REVISE:
            if self.current_node is not RuntimeNode.REVISE_REPORT:
                raise ValueError("REVIEW_REVISE must enter revise_report")

        if self.status is RuntimeStatus.REVIEWED:
            if self.current_node is not RuntimeNode.END:
                raise ValueError("REVIEWED must stop at end")
            if (
                self.last_review_result is None
                or self.last_review_result.outcome is not ReviewOutcome.PASS
            ):
                raise ValueError("REVIEWED requires passing review")

        if self.status is RuntimeStatus.REPORT_CONFIRMATION_READY:
            if self.graph_version != "report-confirmation-v1":
                raise ValueError(
                    "report confirmation requires confirmation graph version"
                )
            if self.current_node is not RuntimeNode.CONFIRM_REPORT:
                raise ValueError(
                    "REPORT_CONFIRMATION_READY must enter confirm_report"
                )
            if (
                self.last_review_result is None
                or self.last_review_result.outcome is not ReviewOutcome.PASS
            ):
                raise ValueError(
                    "report confirmation requires passing review"
                )

        if self.status is RuntimeStatus.REPORT_NEEDS_HUMAN:
            if self.graph_version != "report-confirmation-v1":
                raise ValueError(
                    "report human wait requires confirmation graph version"
                )
            if self.current_node is not RuntimeNode.AWAIT_HUMAN_REPORT:
                raise ValueError(
                    "REPORT_NEEDS_HUMAN must wait at the report human node"
                )
            if self.report_confirmation_revision < 1:
                raise ValueError(
                    "REPORT_NEEDS_HUMAN requires a confirmation revision"
                )
            if (
                self.last_review_result is None
                or self.last_review_result.outcome is not ReviewOutcome.PASS
            ):
                raise ValueError(
                    "report human wait requires passing review"
                )

        if self.status is RuntimeStatus.REPORT_REVISION_REQUESTED:
            if self.graph_version != "report-confirmation-v1":
                raise ValueError(
                    "human revision requires confirmation graph version"
                )
            if self.current_node is not RuntimeNode.APPLY_HUMAN_REPORT_REVISION:
                raise ValueError(
                    "REPORT_REVISION_REQUESTED must enter human revision"
                )
            if self.last_report_action is not HumanActionKind.REQUEST_CHANGES:
                raise ValueError(
                    "report revision requires request-changes action"
                )
            if self.human_revision_count >= MAX_HUMAN_REVISIONS:
                raise ValueError("report revision exceeds human revision limit")
            if (
                self.last_review_result is None
                or self.last_review_result.outcome is not ReviewOutcome.PASS
            ):
                raise ValueError(
                    "human report revision requires passing review"
                )

        if self.status is RuntimeStatus.REPORT_APPROVED:
            if self.graph_version != "report-confirmation-v1":
                raise ValueError(
                    "report approval requires confirmation graph version"
                )
            if self.current_node is not RuntimeNode.END:
                raise ValueError("REPORT_APPROVED must stop at end")
            if self.last_report_action is not HumanActionKind.APPROVE:
                raise ValueError("REPORT_APPROVED requires approve action")
            if (
                self.report_confirmation_revision < 1
                or self.last_review_result is None
                or self.last_review_result.outcome is not ReviewOutcome.PASS
            ):
                raise ValueError(
                    "REPORT_APPROVED requires reviewed human confirmation"
                )
            if (
                self.approved_report_revision != self.report_revision
                or self.approved_report_hash != self.report_hash
            ):
                raise ValueError(
                    "report approval must bind current revision and hash"
                )

        terminal_report_actions = {
            RuntimeStatus.REPORT_REJECTED: HumanActionKind.REJECT,
            RuntimeStatus.REPORT_CANCELLED: HumanActionKind.CANCEL,
        }
        if self.status in terminal_report_actions:
            if self.graph_version != "report-confirmation-v1":
                raise ValueError(
                    "terminal report decision requires confirmation graph"
                )
            if self.current_node is not RuntimeNode.END:
                raise ValueError("terminal report decision must stop at end")
            if self.last_report_action is not terminal_report_actions[self.status]:
                raise ValueError("terminal report action mismatch")
            if (
                self.report_confirmation_revision < 1
                or self.last_review_result is None
                or self.last_review_result.outcome is not ReviewOutcome.PASS
            ):
                raise ValueError(
                    "terminal report decision requires reviewed confirmation"
                )

        if self.report_draft is not None:
            draft = self.report_draft
            report_statuses = {
                RuntimeStatus.DRAFTED,
                RuntimeStatus.REVIEW_READY,
                RuntimeStatus.REVIEW_REVISE,
                RuntimeStatus.REVIEWED,
                RuntimeStatus.REPORT_CONFIRMATION_READY,
                RuntimeStatus.REPORT_NEEDS_HUMAN,
                RuntimeStatus.REPORT_REVISION_REQUESTED,
                RuntimeStatus.REPORT_APPROVED,
                RuntimeStatus.REPORT_REJECTED,
                RuntimeStatus.REPORT_CANCELLED,
                RuntimeStatus.FAILED,
            }
            if self.status not in report_statuses:
                raise ValueError("report_draft requires report workflow status")
            if draft.source_snapshot_id != self.source_snapshot_id:
                raise ValueError("report draft snapshot mismatch")
            if draft.revision != self.report_revision:
                raise ValueError("report draft revision mismatch")
            if self.report_hash != hash_report_draft(draft):
                raise ValueError("report draft hash mismatch")
            if not {
                evidence_id
                for claim in draft.claims
                for evidence_id in claim.evidence_ids
            } <= set(self.evidence_ids):
                raise ValueError("report draft uses unavailable evidence")
            if (
                self.confirmed_requirements is None
                or draft.recommendation_candidate_id
                not in self.confirmed_requirements.candidates
            ):
                raise ValueError("report recommendation outside confirmed scope")

        if self.status in {
            RuntimeStatus.REJECTED,
            RuntimeStatus.CANCELLED,
            RuntimeStatus.REPORT_APPROVED,
            RuntimeStatus.REPORT_REJECTED,
            RuntimeStatus.REPORT_CANCELLED,
            RuntimeStatus.FAILED,
        } and self.current_node is not RuntimeNode.END:
            raise ValueError("terminal state must use the end node")

        approval_parts = (
            self.approved_report_revision is not None,
            self.approved_report_hash is not None,
        )
        if any(approval_parts) and not all(approval_parts):
            raise ValueError(
                "approved report revision and hash must be stored together"
            )
        if all(approval_parts) and self.status is not RuntimeStatus.REPORT_APPROVED:
            raise ValueError("approved report binding requires approved status")

        report_parts = (
            self.report_draft is not None,
            self.report_hash is not None,
            self.report_revision != 0,
        )
        if any(report_parts) and not all(report_parts):
            raise ValueError(
                "report draft, revision, and hash must be stored together"
            )
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
