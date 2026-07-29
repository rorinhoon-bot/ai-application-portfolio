"""Deterministic evidence sufficiency contracts and evaluator."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from agent_research.data_loader import VerifiedSource
from agent_research.models import EvidenceId, Identifier, StrictModel
from agent_research.tool_contracts import (
    SOURCE_SNAPSHOT_V1,
    SourceSnapshotIdV1,
)


MAX_EVIDENCE_REQUIREMENTS = 16
MAX_ACCEPTABLE_SETS = 8
MAX_EVIDENCE_PER_SET = 16
MAX_RETRIEVAL_ROUNDS = 2


class EvidenceAssessmentStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    INSUFFICIENT = "INSUFFICIENT"


class EvidenceRequirement(StrictModel):
    """One frozen requirement and the evidence combinations that satisfy it."""

    requirement_id: Identifier
    description: Annotated[str, Field(min_length=3, max_length=240)]
    acceptable_evidence_sets: Annotated[
        tuple[tuple[EvidenceId, ...], ...],
        Field(max_length=MAX_ACCEPTABLE_SETS),
    ] = ()

    @model_validator(mode="after")
    def validate_evidence_sets(self) -> Self:
        normalized: list[tuple[str, ...]] = []
        for evidence_set in self.acceptable_evidence_sets:
            if not evidence_set:
                raise ValueError("acceptable evidence sets must not be empty")
            if len(evidence_set) > MAX_EVIDENCE_PER_SET:
                raise ValueError("acceptable evidence set is too large")
            if len(evidence_set) != len(set(evidence_set)):
                raise ValueError("acceptable evidence set must be unique")
            normalized.append(tuple(sorted(evidence_set)))
        if len(normalized) != len(set(normalized)):
            raise ValueError("acceptable evidence sets must be unique")
        return self


class EvidencePolicy(StrictModel):
    """Versioned, deterministic policy for one approved research request."""

    schema_version: Literal["evidence-policy-v1"] = "evidence-policy-v1"
    policy_id: Identifier
    source_snapshot_id: SourceSnapshotIdV1 = SOURCE_SNAPSHOT_V1
    max_retrieval_rounds: Literal[2] = MAX_RETRIEVAL_ROUNDS
    requirements: Annotated[
        tuple[EvidenceRequirement, ...],
        Field(min_length=1, max_length=MAX_EVIDENCE_REQUIREMENTS),
    ]

    @model_validator(mode="after")
    def validate_unique_requirements(self) -> Self:
        requirement_ids = [
            requirement.requirement_id for requirement in self.requirements
        ]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("evidence requirement IDs must be unique")
        return self


class EvidenceAssessment(StrictModel):
    """Checkpoint-safe result; contains no evaluator or raw source response."""

    schema_version: Literal["evidence-assessment-v1"] = (
        "evidence-assessment-v1"
    )
    policy_id: Identifier
    source_snapshot_id: SourceSnapshotIdV1 = SOURCE_SNAPSHOT_V1
    status: EvidenceAssessmentStatus
    retrieval_round: Annotated[
        int,
        Field(ge=1, le=MAX_RETRIEVAL_ROUNDS),
    ]
    satisfied_requirement_ids: Annotated[
        tuple[Identifier, ...],
        Field(max_length=MAX_EVIDENCE_REQUIREMENTS),
    ] = ()
    gap_requirement_ids: Annotated[
        tuple[Identifier, ...],
        Field(max_length=MAX_EVIDENCE_REQUIREMENTS),
    ] = ()
    evidence_ids: Annotated[
        tuple[EvidenceId, ...],
        Field(max_length=128),
    ] = ()

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        collections = (
            self.satisfied_requirement_ids,
            self.gap_requirement_ids,
            self.evidence_ids,
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("assessment collections must contain unique values")
        if set(self.satisfied_requirement_ids) & set(
            self.gap_requirement_ids
        ):
            raise ValueError("satisfied requirements and gaps must be disjoint")
        if self.status is EvidenceAssessmentStatus.SUFFICIENT:
            if self.gap_requirement_ids:
                raise ValueError("sufficient assessment cannot contain gaps")
        elif not self.gap_requirement_ids:
            raise ValueError("non-sufficient assessment requires gaps")
        if (
            self.status is EvidenceAssessmentStatus.NEEDS_MORE_EVIDENCE
            and self.retrieval_round >= MAX_RETRIEVAL_ROUNDS
        ):
            raise ValueError("final retrieval round cannot request more evidence")
        if (
            self.status is EvidenceAssessmentStatus.INSUFFICIENT
            and self.retrieval_round < MAX_RETRIEVAL_ROUNDS
        ):
            raise ValueError("insufficient is only stable after the final round")
        return self


class DeterministicEvidenceAssessor:
    """Evaluate only frozen evidence IDs against a frozen local policy."""

    def __init__(
        self,
        *,
        sources: tuple[VerifiedSource, ...],
        policy: EvidencePolicy,
    ) -> None:
        known_evidence_ids = {
            evidence_id
            for source in sources
            for evidence_id in source.evidence_ids
        }
        policy_evidence_ids = {
            evidence_id
            for requirement in policy.requirements
            for evidence_set in requirement.acceptable_evidence_sets
            for evidence_id in evidence_set
        }
        unknown = policy_evidence_ids - known_evidence_ids
        if unknown:
            raise ValueError("EVIDENCE_POLICY_REFERENCES_UNKNOWN_EVIDENCE")
        self._known_evidence_ids = frozenset(known_evidence_ids)
        self.policy = policy

    def assess(
        self,
        *,
        evidence_ids: tuple[str, ...],
        retrieval_round: int,
    ) -> EvidenceAssessment:
        """Return the same result for the same policy, IDs, and round."""

        if not set(evidence_ids) <= self._known_evidence_ids:
            raise ValueError("EVIDENCE_ASSESSMENT_RECEIVED_UNKNOWN_EVIDENCE")

        available = set(evidence_ids)
        satisfied: list[str] = []
        gaps: list[str] = []
        for requirement in self.policy.requirements:
            if any(
                set(evidence_set) <= available
                for evidence_set in requirement.acceptable_evidence_sets
            ):
                satisfied.append(requirement.requirement_id)
            else:
                gaps.append(requirement.requirement_id)

        if not gaps:
            status = EvidenceAssessmentStatus.SUFFICIENT
        elif retrieval_round < self.policy.max_retrieval_rounds:
            status = EvidenceAssessmentStatus.NEEDS_MORE_EVIDENCE
        else:
            status = EvidenceAssessmentStatus.INSUFFICIENT

        return EvidenceAssessment(
            policy_id=self.policy.policy_id,
            status=status,
            retrieval_round=retrieval_round,
            satisfied_requirement_ids=tuple(satisfied),
            gap_requirement_ids=tuple(gaps),
            evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        )
