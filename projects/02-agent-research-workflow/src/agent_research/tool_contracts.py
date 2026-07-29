"""Strict, versioned contracts for allowlisted read-only tool calls."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from agent_research.models import (
    EvaluationDimension,
    EvidenceId,
    Identifier,
    Sha256,
    SourceType,
    StrictModel,
    ToolOutcomeKind,
)


MAX_TOOL_ATTEMPTS = 3
SOURCE_SNAPSHOT_V1 = (
    "0e73ca7de985cdccb9295252fe2e7f3b2725183681a0576db2c7fb0838b44e3c"
)
SourceSnapshotIdV1 = Literal[
    "0e73ca7de985cdccb9295252fe2e7f3b2725183681a0576db2c7fb0838b44e3c"
]

_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(authorization\s*:|cookie\s*:|set-cookie\s*:|"
    r"bearer\s+[a-z0-9._~+/=-]{8,}|"
    r"(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret)\s*[:=]\s*\S+)"
)


class ToolName(StrEnum):
    SEARCH_SOURCES = "search_sources"
    READ_SOURCE = "read_source"
    CALCULATE_COMPARISON = "calculate_comparison"


class SearchSourcesArgs(StrictModel):
    schema_version: Literal["search-sources-args-v1"] = (
        "search-sources-args-v1"
    )
    query: Annotated[
        str,
        StringConstraints(min_length=1, max_length=300),
    ]
    candidate_ids: Annotated[
        tuple[Identifier, ...],
        Field(min_length=1, max_length=4),
    ]
    source_types: Annotated[
        tuple[SourceType, ...],
        Field(min_length=1, max_length=4),
    ]
    top_k: Annotated[int, Field(ge=1, le=8)]

    @model_validator(mode="after")
    def validate_unique_filters(self) -> Self:
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("candidate_ids must be unique")
        if len(self.source_types) != len(set(self.source_types)):
            raise ValueError("source_types must be unique")
        return self


class ReadSourceArgs(StrictModel):
    schema_version: Literal["read-source-args-v1"] = "read-source-args-v1"
    source_id: Identifier
    section_id: Identifier


class DimensionScore(StrictModel):
    dimension_id: Identifier
    score: Annotated[int, Field(ge=0, le=5)] | None
    evidence_ids: Annotated[
        tuple[EvidenceId, ...],
        Field(max_length=16),
    ] = ()

    @model_validator(mode="after")
    def validate_score_evidence(self) -> Self:
        if self.score is None and self.evidence_ids:
            raise ValueError("missing scores cannot claim supporting evidence")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("dimension evidence_ids must be unique")
        return self


class CandidateScores(StrictModel):
    candidate_id: Identifier
    dimensions: Annotated[
        tuple[DimensionScore, ...],
        Field(min_length=1, max_length=8),
    ]

    @model_validator(mode="after")
    def validate_unique_dimensions(self) -> Self:
        dimension_ids = [item.dimension_id for item in self.dimensions]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("candidate dimensions must be unique")
        return self


class CalculateComparisonArgs(StrictModel):
    schema_version: Literal["calculate-comparison-args-v1"] = (
        "calculate-comparison-args-v1"
    )
    weights: Annotated[
        tuple[EvaluationDimension, ...],
        Field(min_length=1, max_length=8),
    ]
    candidates: Annotated[
        tuple[CandidateScores, ...],
        Field(min_length=1, max_length=4),
    ]

    @model_validator(mode="after")
    def validate_comparison_shape(self) -> Self:
        weight_ids = [item.dimension_id for item in self.weights]
        if len(weight_ids) != len(set(weight_ids)):
            raise ValueError("comparison weights must be unique")
        if sum(item.weight_percent for item in self.weights) != 100:
            raise ValueError("comparison weights must sum to 100")

        candidate_ids = [item.candidate_id for item in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("comparison candidates must be unique")
        expected_dimensions = set(weight_ids)
        if any(
            {item.dimension_id for item in candidate.dimensions}
            != expected_dimensions
            for candidate in self.candidates
        ):
            raise ValueError(
                "every candidate must use the weighted dimension set"
            )
        return self


ToolArguments = Annotated[
    SearchSourcesArgs | ReadSourceArgs | CalculateComparisonArgs,
    Field(discriminator="schema_version"),
]


class ToolCall(StrictModel):
    schema_version: Literal["tool-call-v1"] = "tool-call-v1"
    call_id: Identifier
    tool_name: ToolName
    arguments: ToolArguments

    @model_validator(mode="after")
    def validate_name_matches_arguments(self) -> Self:
        expected_type = {
            ToolName.SEARCH_SOURCES: SearchSourcesArgs,
            ToolName.READ_SOURCE: ReadSourceArgs,
            ToolName.CALCULATE_COMPARISON: CalculateComparisonArgs,
        }[self.tool_name]
        if not isinstance(self.arguments, expected_type):
            raise ValueError("tool_name does not match arguments schema")
        return self


class ToolResult(StrictModel):
    schema_version: Literal["tool-result-v1"] = "tool-result-v1"
    logical_call_key: Sha256
    call_id: Identifier
    tool_name: ToolName
    outcome: ToolOutcomeKind
    attempt: Annotated[int, Field(ge=1, le=MAX_TOOL_ATTEMPTS)]
    evidence_ids: Annotated[
        tuple[EvidenceId, ...],
        Field(max_length=128),
    ] = ()
    error_code: Identifier | None = None
    safe_summary: Annotated[str, Field(min_length=1, max_length=240)] | None = (
        None
    )

    @field_validator("safe_summary")
    @classmethod
    def reject_secret_shaped_summary(cls, value: str | None) -> str | None:
        if value is not None and _SENSITIVE_VALUE_PATTERN.search(value):
            raise ValueError("safe_summary must not contain secret-shaped text")
        return value

    @model_validator(mode="after")
    def validate_outcome_fields(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("result evidence_ids must be unique")
        if self.outcome is ToolOutcomeKind.SUCCESS:
            if self.error_code is not None or self.safe_summary is not None:
                raise ValueError("successful results cannot contain errors")
        else:
            if self.error_code is None or self.safe_summary is None:
                raise ValueError("failed results require a safe error")
            if self.evidence_ids:
                raise ValueError("failed results cannot contain evidence")
        return self


def compute_tool_call_key(
    call: ToolCall,
    source_snapshot_id: str,
) -> str:
    """Bind one logical call to canonical parameters and one source snapshot."""

    payload = {
        "source_snapshot_id": source_snapshot_id,
        "tool_call": call.model_dump(mode="json"),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
