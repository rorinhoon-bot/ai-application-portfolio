"""Strict report draft contracts and deterministic citation binding."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from agent_research.data_loader import VerifiedSource
from agent_research.models import (
    EvidenceId,
    GoldClaim,
    Identifier,
    ResearchInput,
    Sha256,
    StrictModel,
)
from agent_research.tool_contracts import (
    SOURCE_SNAPSHOT_V1,
    SourceSnapshotIdV1,
)


MAX_DRAFT_CLAIMS = 32
MAX_DRAFT_CITATIONS = 128
MAX_DRAFT_LIMITATIONS = 12
MAX_REPORT_REVISIONS = 32

_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(authorization\s*:|cookie\s*:|set-cookie\s*:|"
    r"bearer\s+[a-z0-9._~+/=-]{8,}|"
    r"(?:api[_ -]?key|access[_ -]?token|client[_ -]?secret)\s*[:=]\s*\S+)"
)


class DraftClaim(StrictModel):
    """Writer-proposed claim that must exactly match one frozen allowed claim."""

    claim_id: Identifier
    candidate_id: Identifier
    dimension_id: Identifier
    statement: Annotated[str, Field(min_length=3, max_length=300)]
    evidence_ids: Annotated[
        tuple[EvidenceId, ...],
        Field(min_length=1, max_length=8),
    ]
    strength: Literal["factual", "limited"]

    @field_validator("statement")
    @classmethod
    def reject_secret_shaped_statement(cls, value: str) -> str:
        if _SENSITIVE_VALUE_PATTERN.search(value):
            raise ValueError("draft statement must not contain secret-shaped text")
        return value

    @model_validator(mode="after")
    def validate_unique_evidence(self) -> Self:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("draft claim evidence_ids must be unique")
        return self


class DraftProposal(StrictModel):
    """Structured fake-writer output before trusted citation metadata is bound."""

    schema_version: Literal["draft-proposal-v1"] = "draft-proposal-v1"
    writer_id: Identifier
    executive_summary: Annotated[str, Field(min_length=10, max_length=1_000)]
    claims: Annotated[
        tuple[DraftClaim, ...],
        Field(min_length=1, max_length=MAX_DRAFT_CLAIMS),
    ]
    recommendation_candidate_id: Identifier
    limitations: Annotated[
        tuple[Annotated[str, Field(min_length=3, max_length=300)], ...],
        Field(max_length=MAX_DRAFT_LIMITATIONS),
    ] = ()

    @field_validator("executive_summary", "limitations")
    @classmethod
    def reject_secret_shaped_text(
        cls,
        value: str | tuple[str, ...],
    ) -> str | tuple[str, ...]:
        values = (value,) if isinstance(value, str) else value
        if any(_SENSITIVE_VALUE_PATTERN.search(item) for item in values):
            raise ValueError("draft text must not contain secret-shaped text")
        return value

    @model_validator(mode="after")
    def validate_unique_content(self) -> Self:
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("draft claim IDs must be unique")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("draft limitations must be unique")
        return self


class DraftPolicy(StrictModel):
    """Frozen claims and recommendation scope for one deterministic case."""

    schema_version: Literal["draft-policy-v1"] = "draft-policy-v1"
    policy_id: Identifier
    source_snapshot_id: SourceSnapshotIdV1 = SOURCE_SNAPSHOT_V1
    allowed_claims: Annotated[
        tuple[GoldClaim, ...],
        Field(min_length=1, max_length=MAX_DRAFT_CLAIMS),
    ]
    allowed_recommendations: Annotated[
        tuple[Identifier, ...],
        Field(min_length=1, max_length=4),
    ]

    @model_validator(mode="after")
    def validate_unique_policy_values(self) -> Self:
        claim_ids = [claim.claim_id for claim in self.allowed_claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("draft policy claim IDs must be unique")
        if any(
            len(claim.evidence_ids) != len(set(claim.evidence_ids))
            for claim in self.allowed_claims
        ):
            raise ValueError("draft policy claim evidence IDs must be unique")
        if len(self.allowed_recommendations) != len(
            set(self.allowed_recommendations)
        ):
            raise ValueError("allowed recommendations must be unique")
        return self


class BoundCitation(StrictModel):
    """Trusted citation metadata derived from the verified source catalog."""

    evidence_id: EvidenceId
    source_id: Identifier
    section_id: Identifier
    source_title: Annotated[str, Field(min_length=3, max_length=120)]
    source_version: Annotated[
        str,
        Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$"),
    ]
    source_sha256: Sha256


class ReportDraft(StrictModel):
    """Checkpoint-safe structured draft; not an approved final artifact."""

    schema_version: Literal["report-draft-v1"] = "report-draft-v1"
    draft_policy_id: Identifier
    writer_id: Identifier
    source_snapshot_id: SourceSnapshotIdV1 = SOURCE_SNAPSHOT_V1
    revision: Annotated[int, Field(ge=1, le=MAX_REPORT_REVISIONS)]
    research_question: Annotated[str, Field(min_length=1, max_length=500)]
    executive_summary: Annotated[str, Field(min_length=10, max_length=1_000)]
    claims: Annotated[
        tuple[DraftClaim, ...],
        Field(min_length=1, max_length=MAX_DRAFT_CLAIMS),
    ]
    citations: Annotated[
        tuple[BoundCitation, ...],
        Field(min_length=1, max_length=MAX_DRAFT_CITATIONS),
    ]
    recommendation_candidate_id: Identifier
    limitations: Annotated[
        tuple[Annotated[str, Field(min_length=3, max_length=300)], ...],
        Field(max_length=MAX_DRAFT_LIMITATIONS),
    ] = ()

    @field_validator("executive_summary", "limitations")
    @classmethod
    def reject_secret_shaped_text(
        cls,
        value: str | tuple[str, ...],
    ) -> str | tuple[str, ...]:
        values = (value,) if isinstance(value, str) else value
        if any(_SENSITIVE_VALUE_PATTERN.search(item) for item in values):
            raise ValueError(
                "checkpoint draft must not contain secret-shaped text"
            )
        return value

    @model_validator(mode="after")
    def validate_bound_citations(self) -> Self:
        evidence_ids = [citation.evidence_id for citation in self.citations]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("bound citation evidence IDs must be unique")
        claimed = {
            evidence_id
            for claim in self.claims
            for evidence_id in claim.evidence_ids
        }
        if claimed != set(evidence_ids):
            raise ValueError("citations must exactly cover claim evidence")
        return self


class DeterministicFakeWriter:
    """Return one strict scripted proposal; never call a model or network."""

    def __init__(self, proposal: DraftProposal) -> None:
        self._proposal = proposal
        self.write_count = 0

    def write(self) -> DraftProposal:
        self.write_count += 1
        return self._proposal


class EvidenceCitationBinder:
    """Validate proposal scope, then bind trusted source metadata."""

    def __init__(
        self,
        *,
        sources: tuple[VerifiedSource, ...],
        policy: DraftPolicy,
    ) -> None:
        self.policy = policy
        self._sources_by_evidence = {
            evidence_id: source
            for source in sources
            for evidence_id in source.evidence_ids
        }
        policy_evidence_ids = {
            evidence_id
            for claim in policy.allowed_claims
            for evidence_id in claim.evidence_ids
        }
        if not policy_evidence_ids <= set(self._sources_by_evidence):
            raise ValueError("DRAFT_POLICY_REFERENCES_UNKNOWN_EVIDENCE")
        self._claims_by_id = {
            claim.claim_id: claim for claim in policy.allowed_claims
        }

    def bind(
        self,
        *,
        proposal: DraftProposal,
        confirmed_requirements: ResearchInput,
        available_evidence_ids: tuple[str, ...],
        revision: int,
    ) -> ReportDraft:
        """Reject untrusted scope changes before creating report state."""

        approved_candidates = set(confirmed_requirements.candidates)
        approved_dimensions = {
            dimension.dimension_id
            for dimension in confirmed_requirements.dimensions
        }
        available = set(available_evidence_ids)
        if not available <= set(self._sources_by_evidence):
            raise ValueError("DRAFT_RECEIVED_UNKNOWN_EVIDENCE")
        if proposal.recommendation_candidate_id not in approved_candidates:
            raise ValueError("DRAFT_RECOMMENDATION_OUTSIDE_APPROVED_SCOPE")
        if (
            proposal.recommendation_candidate_id
            not in self.policy.allowed_recommendations
        ):
            raise ValueError("DRAFT_RECOMMENDATION_NOT_ALLOWED")

        proposal_claim_ids = {claim.claim_id for claim in proposal.claims}
        if proposal_claim_ids != set(self._claims_by_id):
            raise ValueError("DRAFT_REQUIRED_CLAIM_SET_MISMATCH")

        ordered_evidence_ids: list[str] = []
        for claim in proposal.claims:
            expected = self._claims_by_id[claim.claim_id]
            if claim.model_dump(mode="json") != expected.model_dump(mode="json"):
                raise ValueError("DRAFT_CLAIM_DIFFERS_FROM_ALLOWED_FACT")
            if claim.candidate_id not in approved_candidates:
                raise ValueError("DRAFT_CLAIM_CANDIDATE_OUTSIDE_APPROVED_SCOPE")
            if claim.dimension_id not in approved_dimensions:
                raise ValueError("DRAFT_CLAIM_DIMENSION_OUTSIDE_APPROVED_SCOPE")
            if not set(claim.evidence_ids) <= available:
                raise ValueError("DRAFT_CLAIM_USES_UNCOLLECTED_EVIDENCE")
            ordered_evidence_ids.extend(claim.evidence_ids)

        citations = tuple(
            self._bind_citation(evidence_id)
            for evidence_id in dict.fromkeys(ordered_evidence_ids)
        )
        return ReportDraft(
            draft_policy_id=self.policy.policy_id,
            writer_id=proposal.writer_id,
            revision=revision,
            research_question=confirmed_requirements.research_question,
            executive_summary=proposal.executive_summary,
            claims=proposal.claims,
            citations=citations,
            recommendation_candidate_id=proposal.recommendation_candidate_id,
            limitations=proposal.limitations,
        )

    def _bind_citation(self, evidence_id: str) -> BoundCitation:
        source = self._sources_by_evidence[evidence_id]
        source_id, section_id = evidence_id.split("#", maxsplit=1)
        return BoundCitation(
            evidence_id=evidence_id,
            source_id=source_id,
            section_id=section_id,
            source_title=source.entry.title,
            source_version=source.entry.version,
            source_sha256=source.entry.sha256,
        )


def hash_report_draft(draft: ReportDraft) -> str:
    """Hash canonical structured content for revision and approval binding."""

    payload = draft.model_dump(mode="json")
    payload.pop("revision")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
