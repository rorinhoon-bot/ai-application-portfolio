"""Deterministic report review contracts and bounded fake revision."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from agent_research.models import Identifier, ResearchInput, Sha256, StrictModel
from agent_research.report_drafting import (
    DraftProposal,
    MAX_REPORT_REVISIONS,
    ReportDraft,
    hash_report_draft,
)
from agent_research.tool_contracts import (
    SOURCE_SNAPSHOT_V1,
    SourceSnapshotIdV1,
)


MAX_REVIEW_ROUNDS = 2
MAX_REVIEW_FINDINGS = 32

_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(authorization\s*:|cookie\s*:|set-cookie\s*:|"
    r"bearer\s+[a-z0-9._~+/=-]{8,}|"
    r"(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret)\s*[:=]\s*\S+)"
)


class ReviewFindingCode(StrEnum):
    CITATION_INTEGRITY = "citation-integrity"
    MISSING_CANDIDATE_COVERAGE = "missing-candidate-coverage"
    MISSING_DIMENSION_COVERAGE = "missing-dimension-coverage"
    FORBIDDEN_ASSERTION = "forbidden-assertion"


class ReviewOutcome(StrEnum):
    PASS = "PASS"
    REVISE = "REVISE"
    FAIL = "FAIL"


class ReviewFinding(StrictModel):
    finding_id: Identifier
    code: ReviewFindingCode
    severity: Literal["error"] = "error"
    safe_summary: Annotated[str, Field(min_length=3, max_length=240)]
    candidate_id: Identifier | None = None
    dimension_id: Identifier | None = None

    @field_validator("safe_summary")
    @classmethod
    def reject_secret_shaped_summary(cls, value: str) -> str:
        if _SENSITIVE_VALUE_PATTERN.search(value):
            raise ValueError(
                "review finding must not contain secret-shaped text"
            )
        return value


class ReviewPolicy(StrictModel):
    """Frozen deterministic checks for one approved report slice."""

    schema_version: Literal["review-policy-v1"] = "review-policy-v1"
    policy_id: Identifier
    source_snapshot_id: SourceSnapshotIdV1 = SOURCE_SNAPSHOT_V1
    max_review_rounds: Literal[2] = MAX_REVIEW_ROUNDS
    required_candidate_ids: Annotated[
        tuple[Identifier, ...],
        Field(min_length=1, max_length=4),
    ]
    required_dimension_ids: Annotated[
        tuple[Identifier, ...],
        Field(min_length=1, max_length=8),
    ]
    forbidden_statements: Annotated[
        tuple[Annotated[str, Field(min_length=3, max_length=300)], ...],
        Field(max_length=16),
    ] = ()

    @model_validator(mode="after")
    def validate_unique_policy_values(self) -> Self:
        collections = (
            self.required_candidate_ids,
            self.required_dimension_ids,
            self.forbidden_statements,
        )
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("review policy collections must be unique")
        return self


class ReviewResult(StrictModel):
    """Checkpoint-safe result bound to one report revision and content hash."""

    schema_version: Literal["review-result-v1"] = "review-result-v1"
    policy_id: Identifier
    source_snapshot_id: SourceSnapshotIdV1 = SOURCE_SNAPSHOT_V1
    report_revision: Annotated[
        int,
        Field(ge=1, le=MAX_REPORT_REVISIONS),
    ]
    report_hash: Sha256
    review_round: Annotated[int, Field(ge=0, le=MAX_REVIEW_ROUNDS)]
    outcome: ReviewOutcome
    findings: Annotated[
        tuple[ReviewFinding, ...],
        Field(max_length=MAX_REVIEW_FINDINGS),
    ] = ()

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> Self:
        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("review finding IDs must be unique")
        if self.outcome is ReviewOutcome.PASS and self.findings:
            raise ValueError("passing review cannot contain findings")
        if self.outcome is not ReviewOutcome.PASS and not self.findings:
            raise ValueError("non-passing review requires findings")
        if (
            self.outcome is ReviewOutcome.REVISE
            and self.review_round >= MAX_REVIEW_ROUNDS
        ):
            raise ValueError("final review round cannot request revision")
        if (
            self.outcome is ReviewOutcome.FAIL
            and self.review_round < MAX_REVIEW_ROUNDS
        ):
            raise ValueError("review fails only after revision limit")
        return self


class DeterministicReportReviewer:
    """Run fixed structural and forbidden-assertion checks without a model."""

    def __init__(self, policy: ReviewPolicy) -> None:
        self.policy = policy
        self.review_count = 0

    def review(
        self,
        *,
        draft: ReportDraft,
        confirmed_requirements: ResearchInput,
        review_round: int,
    ) -> ReviewResult:
        self.review_count += 1
        approved_candidates = set(confirmed_requirements.candidates)
        approved_dimensions = {
            dimension.dimension_id
            for dimension in confirmed_requirements.dimensions
        }
        if not set(self.policy.required_candidate_ids) <= approved_candidates:
            raise ValueError("REVIEW_POLICY_CANDIDATE_OUTSIDE_APPROVED_SCOPE")
        if not set(self.policy.required_dimension_ids) <= approved_dimensions:
            raise ValueError("REVIEW_POLICY_DIMENSION_OUTSIDE_APPROVED_SCOPE")

        findings: list[ReviewFinding] = []
        claimed_evidence = {
            evidence_id
            for claim in draft.claims
            for evidence_id in claim.evidence_ids
        }
        citation_evidence = {
            citation.evidence_id for citation in draft.citations
        }
        if claimed_evidence != citation_evidence:
            findings.append(
                ReviewFinding(
                    finding_id="citation-integrity",
                    code=ReviewFindingCode.CITATION_INTEGRITY,
                    safe_summary="claim evidence and bound citations differ",
                )
            )

        covered_candidates = {claim.candidate_id for claim in draft.claims}
        for index, candidate_id in enumerate(
            self.policy.required_candidate_ids,
            start=1,
        ):
            if candidate_id not in covered_candidates:
                findings.append(
                    ReviewFinding(
                        finding_id=f"missing-candidate-{index}",
                        code=(
                            ReviewFindingCode.MISSING_CANDIDATE_COVERAGE
                        ),
                        safe_summary="required candidate lacks a reviewed claim",
                        candidate_id=candidate_id,
                    )
                )

        covered_dimensions = {claim.dimension_id for claim in draft.claims}
        for index, dimension_id in enumerate(
            self.policy.required_dimension_ids,
            start=1,
        ):
            if dimension_id not in covered_dimensions:
                findings.append(
                    ReviewFinding(
                        finding_id=f"missing-dimension-{index}",
                        code=(
                            ReviewFindingCode.MISSING_DIMENSION_COVERAGE
                        ),
                        safe_summary="required dimension lacks a reviewed claim",
                        dimension_id=dimension_id,
                    )
                )

        text = "\n".join(
            (
                draft.executive_summary,
                *(claim.statement for claim in draft.claims),
                *draft.limitations,
            )
        ).casefold()
        for index, forbidden in enumerate(
            self.policy.forbidden_statements,
            start=1,
        ):
            if forbidden.casefold() in text:
                findings.append(
                    ReviewFinding(
                        finding_id=f"forbidden-assertion-{index}",
                        code=ReviewFindingCode.FORBIDDEN_ASSERTION,
                        safe_summary=(
                            "draft contains a forbidden fixed assertion"
                        ),
                    )
                )

        if not findings:
            outcome = ReviewOutcome.PASS
        elif review_round < self.policy.max_review_rounds:
            outcome = ReviewOutcome.REVISE
        else:
            outcome = ReviewOutcome.FAIL
        return ReviewResult(
            policy_id=self.policy.policy_id,
            report_revision=draft.revision,
            report_hash=hash_report_draft(draft),
            review_round=review_round,
            outcome=outcome,
            findings=tuple(findings),
        )


class DeterministicDraftReviser:
    """Select scripted replacement proposal by persisted review round."""

    def __init__(self, proposals: tuple[DraftProposal, ...]) -> None:
        if not 1 <= len(proposals) <= MAX_REVIEW_ROUNDS:
            raise ValueError("REVISION_SCRIPT_REQUIRES_ONE_OR_TWO_PROPOSALS")
        self._proposals = proposals
        self.revision_count = 0

    def revise(self, *, next_review_round: int) -> DraftProposal:
        if not 1 <= next_review_round <= len(self._proposals):
            raise ValueError("REVISION_SCRIPT_HAS_NO_MATCHING_ROUND")
        self.revision_count += 1
        return self._proposals[next_review_round - 1]
