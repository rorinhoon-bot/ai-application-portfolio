"""Strict, answer-independent contracts for P2 V2."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Identifier = Annotated[
    str,
    StringConstraints(
        min_length=2,
        max_length=80,
        pattern=r"^[a-z][a-z0-9-]*$",
        strip_whitespace=True,
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
EvidenceId = Annotated[
    str,
    StringConstraints(
        min_length=5,
        max_length=160,
        pattern=r"^[a-z][a-z0-9-]*#[a-z][a-z0-9-]*$",
    ),
]
HashableText = Annotated[str, Field(min_length=1, max_length=256)]
ProviderResponseId = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=256,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$",
        strip_whitespace=True,
    ),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class CostStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not-applicable"


class CallStatus(StrEnum):
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DecisionStatus(StrEnum):
    RECOMMENDED = "recommended"
    CONDITIONAL = "conditional"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class RunStatus(StrEnum):
    NEW = "NEW"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    RUNNING = "RUNNING"
    REPORT_NEEDS_HUMAN = "REPORT_NEEDS_HUMAN"
    EXPORT_READY = "EXPORT_READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RECOVERY_REVIEW = "RECOVERY_REVIEW"


class HumanAction(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REQUEST_CHANGES = "request-changes"
    REJECT = "reject"
    CANCEL = "cancel"


class CandidateSpec(StrictModel):
    candidate_id: Identifier
    name: Annotated[str, Field(min_length=2, max_length=120)]
    scope_note: Annotated[str, Field(min_length=2, max_length=300)] = "general scope"


class DimensionSpec(StrictModel):
    dimension_id: Identifier
    question: Annotated[str, Field(min_length=2, max_length=240)]
    weight_percent: Annotated[int, Field(ge=0, le=100)] = 0


class ResearchRequestV2(StrictModel):
    schema_version: Literal["research-request-v2"] = "research-request-v2"
    research_question: Annotated[str, Field(min_length=10, max_length=700)]
    audience: Annotated[str, Field(min_length=2, max_length=180)]
    candidates: tuple[CandidateSpec, ...]
    dimensions: tuple[DimensionSpec, ...]
    hard_constraints: tuple[
        Annotated[str, Field(min_length=2, max_length=300)], ...
    ] = ()
    preferences: tuple[Annotated[str, Field(min_length=2, max_length=300)], ...] = ()
    source_snapshot_id: Identifier
    model_config_hash: Sha256
    budget_authorization_id: Identifier
    allow_insufficient_evidence: bool = True

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        candidate_ids = [item.candidate_id for item in self.candidates]
        dimension_ids = [item.dimension_id for item in self.dimensions]
        if not 2 <= len(candidate_ids) <= 4:
            raise ValueError("V2 requires 2 to 4 candidates")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate IDs must be unique")
        if not 3 <= len(dimension_ids) <= 5:
            raise ValueError("V2 requires 3 to 5 dimensions")
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("dimension IDs must be unique")
        if sum(item.weight_percent for item in self.dimensions) != 100:
            raise ValueError("dimension weights must sum to 100")
        return self

    def content_hash(self) -> str:
        return hashlib.sha256(
            canonical_json(self.model_dump(mode="json")).encode("utf-8")
        ).hexdigest()


class SourceEntryV2(StrictModel):
    source_id: Identifier
    candidate_id: Identifier | None = None
    title: Annotated[str, Field(min_length=3, max_length=180)]
    canonical_url: Annotated[str, Field(min_length=8, max_length=500)]
    version: Annotated[str, Field(min_length=1, max_length=120)]
    accessed_at: Annotated[str, Field(min_length=10, max_length=40)]
    license_id: Annotated[str, Field(min_length=2, max_length=80)]
    license_url: Annotated[str, Field(min_length=8, max_length=500)] | None = None
    relative_path: Annotated[str, Field(min_length=5, max_length=240)]
    raw_sha256: Sha256
    normalized_sha256: Sha256
    size_bytes: Annotated[int, Field(gt=0, le=5 * 1024 * 1024)]


class SourceSnapshotV2(StrictModel):
    schema_version: Literal["source-snapshot-v2"] = "source-snapshot-v2"
    snapshot_id: Identifier
    entries: tuple[SourceEntryV2, ...]
    total_size_bytes: Annotated[int, Field(gt=0, le=5 * 1024 * 1024)]

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        source_ids = [item.source_id for item in self.entries]
        paths = [item.relative_path for item in self.entries]
        if not source_ids:
            raise ValueError("source snapshot cannot be empty")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source IDs must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("source paths must be unique")
        if self.total_size_bytes != sum(item.size_bytes for item in self.entries):
            raise ValueError("source total size mismatch")
        return self


class EvidenceRecord(StrictModel):
    evidence_id: EvidenceId
    source_id: Identifier
    candidate_id: Identifier | None = None
    dimension_id: Identifier | None = None
    section_id: Identifier
    locator: Annotated[str, Field(min_length=2, max_length=300)]
    excerpt: Annotated[str, Field(min_length=1, max_length=2400)]
    content_sha256: Sha256
    source_snapshot_id: Identifier


class EvidenceCell(StrictModel):
    candidate_id: Identifier
    dimension_id: Identifier
    status: Literal["supported", "contradicted", "unknown"]
    claim: Annotated[str, Field(min_length=1, max_length=900)]
    evidence_ids: tuple[EvidenceId, ...] = ()
    caveat: Annotated[str, Field(max_length=500)] = ""

    @model_validator(mode="after")
    def validate_evidence_scope(self) -> Self:
        if self.status == "unknown" and self.evidence_ids:
            raise ValueError("unknown evidence cell cannot cite evidence")
        if self.status != "unknown" and not self.evidence_ids:
            raise ValueError("supported or contradicted cell requires evidence")
        return self


class Usage(StrictModel):
    input_tokens: Annotated[int, Field(ge=0)] | None = None
    output_tokens: Annotated[int, Field(ge=0)] | None = None
    reasoning_tokens: Annotated[int, Field(ge=0)] | None = None
    cost_minor_units: Annotated[int, Field(ge=0)] | None = None
    currency: Literal["CNY"] = "CNY"
    cost_status: CostStatus = CostStatus.UNKNOWN

    @model_validator(mode="after")
    def validate_cost(self) -> Self:
        if self.cost_status is CostStatus.KNOWN and self.cost_minor_units is None:
            raise ValueError("known cost requires cost_minor_units")
        if self.cost_status is not CostStatus.KNOWN and self.cost_minor_units is not None:
            raise ValueError("unknown cost cannot carry a numeric cost")
        return self


class ModelToolCall(StrictModel):
    tool_call_id: Identifier
    tool_name: Literal["search_sources", "read_source"]
    arguments: dict[str, object]


class ModelResult(StrictModel):
    task: Literal["plan", "evidence", "draft", "review"]
    provider: Annotated[str, Field(min_length=2, max_length=80)]
    model_id: Annotated[str, Field(min_length=2, max_length=120)]
    response_id: ProviderResponseId | None = None
    tool_calls: tuple[ModelToolCall, ...] = ()
    evidence_cells: tuple[EvidenceCell, ...] = ()
    executive_summary: Annotated[str, Field(max_length=1800)] = ""
    recommendation: Identifier | None = None
    decision_status: DecisionStatus | None = None
    limitations: tuple[Annotated[str, Field(max_length=500)], ...] = ()
    usage: Usage = Usage(cost_status=CostStatus.NOT_APPLICABLE)
    raw_response_sha256: Sha256 | None = None
    review_completed: bool = False
    review_findings: tuple[Annotated[str, Field(min_length=1, max_length=900)], ...] = ()

    @model_validator(mode="after")
    def validate_task_shape(self) -> Self:
        if self.task == "plan" and not self.tool_calls:
            raise ValueError("plan result requires at least one tool call")
        if self.task == "draft":
            if not self.evidence_cells or not self.executive_summary:
                raise ValueError("draft result requires summary and evidence cells")
            if self.decision_status is None:
                raise ValueError("draft result requires decision status")
        if self.task != "draft" and (
            self.evidence_cells or self.decision_status is not None
        ):
            raise ValueError("evidence cells and decision status belong to draft")
        if self.task == "review" and not self.review_completed:
            raise ValueError("review result requires review_completed")
        if self.task != "review" and (self.review_completed or self.review_findings):
            raise ValueError("review fields belong to review")
        return self


class BudgetAuthorization(StrictModel):
    authorization_id: Identifier
    currency: Literal["CNY"] = "CNY"
    max_cost_minor_units: Annotated[int, Field(ge=0)]
    max_model_calls: Annotated[int, Field(ge=1, le=100)]
    max_input_tokens: Annotated[int, Field(ge=1)]
    max_output_tokens: Annotated[int, Field(ge=1)]
    expires_at: Annotated[str, Field(min_length=10, max_length=40)]
    approved: bool = False


class CallRecord(StrictModel):
    schema_version: Literal["call-record-v2"] = "call-record-v2"
    logical_call_key: Sha256
    run_id: Identifier
    node: Identifier
    attempt: Annotated[int, Field(ge=1, le=20)]
    status: CallStatus
    provider: Annotated[str, Field(min_length=2, max_length=80)]
    model_id: Annotated[str, Field(min_length=2, max_length=120)]
    request_hash: Sha256
    response_hash: Sha256 | None = None
    usage: Usage | None = None
    error_code: Annotated[str, Field(min_length=2, max_length=100)] | None = None


class RuntimeStateV2(StrictModel):
    schema_version: Literal["runtime-state-v2"] = "runtime-state-v2"
    graph_version: Literal["research-workflow-v2"] = "research-workflow-v2"
    run_id: Identifier
    thread_id: Identifier
    status: RunStatus = RunStatus.NEW
    current_node: Identifier = "validate-request"
    request: ResearchRequestV2
    request_revision: Annotated[int, Field(ge=0, le=4)] = 0
    request_hash: Sha256 | None = None
    report_revision: Annotated[int, Field(ge=0, le=3)] = 0
    report_hash: Sha256 | None = None
    evidence: tuple[EvidenceRecord, ...] = ()
    evidence_cells: tuple[EvidenceCell, ...] = ()
    report: ModelResult | None = None
    review_findings: tuple[Annotated[str, Field(min_length=1, max_length=900)], ...] = ()
    pending_tool_calls: tuple[ModelToolCall, ...] = ()
    errors: tuple[Annotated[str, Field(min_length=2, max_length=100)], ...] = ()
    model_call_count: Annotated[int, Field(ge=0, le=100)] = 0
    tool_call_count: Annotated[int, Field(ge=0, le=100)] = 0
    unknown_call_count: Annotated[int, Field(ge=0, le=100)] = 0
    approved_request_revision: int | None = None
    approved_request_hash: Sha256 | None = None
    approved_report_revision: int | None = None
    approved_report_hash: Sha256 | None = None
    artifact_id: Sha256 | None = None

    @model_validator(mode="after")
    def validate_bindings(self) -> Self:
        if self.approved_request_revision is not None:
            if self.approved_request_hash is None:
                raise ValueError("approved request revision requires hash")
        if self.approved_report_revision is not None:
            if self.approved_report_hash is None or self.report is None:
                raise ValueError("approved report requires hash and report")
        if self.status is RunStatus.COMPLETED and self.artifact_id is None:
            raise ValueError("completed state requires artifact_id")
        return self


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
