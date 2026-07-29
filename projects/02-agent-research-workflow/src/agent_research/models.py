"""Strict contracts for synthetic sources and fixed workflow evaluations."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


Identifier = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=64,
        pattern=r"^[a-z][a-z0-9-]*$",
        strip_whitespace=True,
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
EvidenceId = Annotated[
    str,
    StringConstraints(
        min_length=7,
        max_length=130,
        pattern=r"^[a-z][a-z0-9-]*#[a-z][a-z0-9-]*$",
    ),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )


class SourceType(StrEnum):
    OVERVIEW = "overview"
    RELIABILITY = "reliability"
    SECURITY_AND_COST = "security-and-cost"
    CONSTRAINTS = "constraints"


class CaseCategory(StrEnum):
    SUCCESS = "success"
    REQUIREMENTS_INCOMPLETE = "requirements-incomplete"
    EVIDENCE_INSUFFICIENT = "evidence-insufficient"
    TOOL_FAILURE = "tool-failure"
    HUMAN_REVISION = "human-revision"
    RECOVERY_IDEMPOTENCY = "recovery-idempotency"


class RunStatus(StrEnum):
    NEEDS_HUMAN = "NEEDS_HUMAN"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ToolOutcomeKind(StrEnum):
    SUCCESS = "success"
    TRANSIENT_ERROR = "transient-error"
    DETERMINISTIC_ERROR = "deterministic-error"


class HumanGate(StrEnum):
    REQUIREMENTS = "requirements"
    REPORT = "report"


class HumanActionKind(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REQUEST_CHANGES = "request-changes"
    REJECT = "reject"
    CANCEL = "cancel"


class SourceManifestEntry(StrictModel):
    source_id: Identifier
    candidate_id: Identifier | None
    title: Annotated[str, Field(min_length=3, max_length=120)]
    version: Annotated[
        str,
        StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$"),
    ]
    source_type: SourceType
    relative_path: Annotated[str, Field(min_length=4, max_length=180)]
    size_bytes: Annotated[int, Field(gt=0, le=16_384)]
    sha256: Sha256
    synthetic: Literal[True]

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("relative_path must use POSIX separators")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError("relative_path must stay inside the source root")
        if path.suffix != ".md" or path.as_posix() != value:
            raise ValueError("relative_path must be a normalized Markdown path")
        return value


class SourceManifest(StrictModel):
    schema_version: Literal["source-manifest-v1"]
    snapshot_id: Sha256
    sources: Annotated[tuple[SourceManifestEntry, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_unique_sources(self) -> Self:
        source_ids = [item.source_id for item in self.sources]
        paths = [item.relative_path for item in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id values must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("relative_path values must be unique")
        return self


class EvaluationDimension(StrictModel):
    dimension_id: Identifier
    weight_percent: Annotated[int, Field(ge=0, le=100)]


class ResearchInput(StrictModel):
    research_question: Annotated[str, Field(min_length=1, max_length=500)]
    audience: Annotated[str, Field(min_length=1, max_length=120)]
    constraints: Annotated[tuple[str, ...], Field(max_length=12)]
    candidates: Annotated[tuple[Identifier, ...], Field(min_length=0, max_length=4)]
    dimensions: Annotated[
        tuple[EvaluationDimension, ...],
        Field(min_length=0, max_length=8),
    ]
    source_policy_id: Literal["synthetic-v1"]

    @model_validator(mode="after")
    def validate_input_collections(self) -> Self:
        if len(self.candidates) != len(set(self.candidates)):
            raise ValueError("candidates must be unique")
        dimension_ids = [item.dimension_id for item in self.dimensions]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("dimensions must be unique")
        if self.dimensions and sum(
            item.weight_percent for item in self.dimensions
        ) != 100:
            raise ValueError("dimension weights must sum to 100")
        return self


class ScriptedToolOutcome(StrictModel):
    call_id: Identifier
    tool_name: Literal[
        "search_sources",
        "read_source",
        "calculate_comparison",
    ]
    outcome: ToolOutcomeKind
    evidence_ids: tuple[EvidenceId, ...] = ()
    error_code: Identifier | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.outcome is ToolOutcomeKind.SUCCESS and self.error_code is not None:
            raise ValueError("successful tool outcomes cannot have error_code")
        if self.outcome is not ToolOutcomeKind.SUCCESS and self.error_code is None:
            raise ValueError("failed tool outcomes require error_code")
        return self


class ScriptedHumanAction(StrictModel):
    gate: HumanGate
    action: HumanActionKind


class ExpectedOutcome(StrictModel):
    required_path: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    status: RunStatus
    max_tool_attempts: Annotated[int, Field(ge=0, le=12)]
    required_evidence_ids: tuple[EvidenceId, ...] = ()
    forbidden_evidence_ids: tuple[EvidenceId, ...] = ()
    allowed_recommendations: tuple[Identifier, ...] = ()
    artifact_count: Literal[0, 1]

    @model_validator(mode="after")
    def validate_evidence_sets(self) -> Self:
        if set(self.required_evidence_ids) & set(self.forbidden_evidence_ids):
            raise ValueError("required and forbidden evidence must not overlap")
        if self.status is not RunStatus.COMPLETED and self.artifact_count != 0:
            raise ValueError("only completed cases may create an artifact")
        return self


class WorkflowCase(StrictModel):
    case_id: Identifier
    category: CaseCategory
    description: Annotated[str, Field(min_length=3, max_length=240)]
    input: ResearchInput
    tool_outcomes: tuple[ScriptedToolOutcome, ...] = ()
    human_actions: tuple[ScriptedHumanAction, ...] = ()
    expected: ExpectedOutcome


class WorkflowEvaluationSuite(StrictModel):
    schema_version: Literal["workflow-evaluation-v1"]
    source_snapshot_id: Sha256
    cases: Annotated[tuple[WorkflowCase, ...], Field(min_length=12, max_length=12)]

    @model_validator(mode="after")
    def validate_case_mix(self) -> Self:
        case_ids = [item.case_id for item in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id values must be unique")

        expected = Counter(
            {
                CaseCategory.SUCCESS: 4,
                CaseCategory.REQUIREMENTS_INCOMPLETE: 2,
                CaseCategory.EVIDENCE_INSUFFICIENT: 2,
                CaseCategory.TOOL_FAILURE: 2,
                CaseCategory.HUMAN_REVISION: 1,
                CaseCategory.RECOVERY_IDEMPOTENCY: 1,
            }
        )
        actual = Counter(item.category for item in self.cases)
        if actual != expected:
            raise ValueError(f"unexpected workflow case mix: {actual!r}")
        return self


class GoldClaim(StrictModel):
    claim_id: Identifier
    candidate_id: Identifier
    dimension_id: Identifier
    statement: Annotated[str, Field(min_length=3, max_length=300)]
    evidence_ids: Annotated[tuple[EvidenceId, ...], Field(min_length=1)]
    strength: Literal["factual", "limited"]


class RecommendationRule(StrictModel):
    case_id: Identifier
    allowed_candidates: Annotated[tuple[Identifier, ...], Field(min_length=0)]


class WorkflowGoldSuite(StrictModel):
    schema_version: Literal["workflow-gold-v1"]
    source_snapshot_id: Sha256
    claims: Annotated[tuple[GoldClaim, ...], Field(min_length=1)]
    forbidden_claims: Annotated[tuple[str, ...], Field(min_length=1)]
    recommendation_rules: Annotated[
        tuple[RecommendationRule, ...],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def validate_gold_ids(self) -> Self:
        claim_ids = [item.claim_id for item in self.claims]
        case_ids = [item.case_id for item in self.recommendation_rules]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("claim_id values must be unique")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("recommendation rule case_id values must be unique")
        return self


def compute_source_snapshot_id(
    schema_version: str,
    sources: tuple[SourceManifestEntry, ...],
) -> str:
    payload = {
        "schema_version": schema_version,
        "sources": [
            item.model_dump(mode="json")
            for item in sorted(sources, key=lambda entry: entry.source_id)
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
