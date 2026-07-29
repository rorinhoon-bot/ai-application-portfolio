"""Unit tests for safe structured report drafting and citation binding."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_research.data_loader import EvaluationBundle, load_evaluation_bundle
from agent_research.models import GoldClaim, ResearchInput
from agent_research.report_drafting import (
    DeterministicFakeWriter,
    DraftClaim,
    DraftPolicy,
    DraftProposal,
    EvidenceCitationBinder,
    ReportDraft,
    hash_report_draft,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAIM_IDS = ("atlas-local-data", "atlas-durable-checkpoint")


def _bundle() -> EvaluationBundle:
    return load_evaluation_bundle(PROJECT_ROOT)


def _claims(*claim_ids: str) -> tuple[GoldClaim, ...]:
    wanted = set(claim_ids)
    return tuple(
        claim for claim in _bundle().gold.claims if claim.claim_id in wanted
    )


def _request() -> ResearchInput:
    case = next(
        case
        for case in _bundle().evaluation.cases
        if case.case_id == "privacy-durable-selection"
    )
    return case.input


def _policy(*claim_ids: str) -> DraftPolicy:
    return DraftPolicy(
        policy_id="privacy-draft-policy",
        allowed_claims=_claims(*claim_ids),
        allowed_recommendations=("atlasflow",),
    )


def _proposal(*claim_ids: str) -> DraftProposal:
    claims = _claims(*claim_ids)
    return DraftProposal(
        writer_id="deterministic-writer-v1",
        executive_summary=(
            "AtlasFlow best matches local data and durable recovery constraints."
        ),
        claims=tuple(
            DraftClaim.model_validate(claim.model_dump(mode="json"))
            for claim in claims
        ),
        recommendation_candidate_id="atlasflow",
        limitations=("Only the fixed synthetic snapshot was evaluated.",),
    )


def _binder(*claim_ids: str) -> EvidenceCitationBinder:
    return EvidenceCitationBinder(
        sources=_bundle().sources,
        policy=_policy(*claim_ids),
    )


def test_binder_adds_trusted_source_metadata_and_stable_hash() -> None:
    proposal = _proposal(*CLAIM_IDS)
    writer = DeterministicFakeWriter(proposal)
    draft = _binder(*CLAIM_IDS).bind(
        proposal=writer.write(),
        confirmed_requirements=_request(),
        available_evidence_ids=tuple(
            evidence_id
            for claim in proposal.claims
            for evidence_id in claim.evidence_ids
        ),
        revision=1,
    )

    assert writer.write_count == 1
    assert draft.recommendation_candidate_id == "atlasflow"
    assert {citation.evidence_id for citation in draft.citations} == {
        evidence_id
        for claim in proposal.claims
        for evidence_id in claim.evidence_ids
    }
    assert all(citation.source_title for citation in draft.citations)
    assert all(citation.source_version == "1.0.0" for citation in draft.citations)
    assert hash_report_draft(draft) == hash_report_draft(draft)
    assert hash_report_draft(draft) == hash_report_draft(
        draft.model_copy(update={"revision": 2})
    )


def test_binder_rejects_uncollected_evidence() -> None:
    proposal = _proposal(*CLAIM_IDS)

    with pytest.raises(
        ValueError,
        match="DRAFT_CLAIM_USES_UNCOLLECTED_EVIDENCE",
    ):
        _binder(*CLAIM_IDS).bind(
            proposal=proposal,
            confirmed_requirements=_request(),
            available_evidence_ids=(
                "atlasflow-security-cost-v1#data-boundary",
            ),
            revision=1,
        )


def test_binder_rejects_changed_allowed_claim() -> None:
    proposal = _proposal(*CLAIM_IDS)
    changed = proposal.model_copy(
        update={
            "claims": (
                proposal.claims[0].model_copy(
                    update={"statement": "Unsupported stronger statement."}
                ),
                proposal.claims[1],
            )
        }
    )

    with pytest.raises(
        ValueError,
        match="DRAFT_CLAIM_DIFFERS_FROM_ALLOWED_FACT",
    ):
        _binder(*CLAIM_IDS).bind(
            proposal=changed,
            confirmed_requirements=_request(),
            available_evidence_ids=tuple(
                evidence_id
                for claim in changed.claims
                for evidence_id in claim.evidence_ids
            ),
            revision=1,
        )


def test_binder_rejects_dimension_outside_confirmed_request() -> None:
    claim_id = "atlas-explicit-graph"
    proposal = _proposal(claim_id)

    with pytest.raises(
        ValueError,
        match="DRAFT_CLAIM_DIMENSION_OUTSIDE_APPROVED_SCOPE",
    ):
        _binder(claim_id).bind(
            proposal=proposal,
            confirmed_requirements=_request(),
            available_evidence_ids=proposal.claims[0].evidence_ids,
            revision=1,
        )


def test_binder_rejects_policy_with_unknown_evidence() -> None:
    unknown_claim = GoldClaim(
        claim_id="unknown-proof",
        candidate_id="atlasflow",
        dimension_id="privacy",
        statement="Unknown evidence must not enter a draft policy.",
        evidence_ids=("unknown-source#unknown-section",),
        strength="factual",
    )
    policy = DraftPolicy(
        policy_id="unknown-draft-policy",
        allowed_claims=(unknown_claim,),
        allowed_recommendations=("atlasflow",),
    )

    with pytest.raises(
        ValueError,
        match="DRAFT_POLICY_REFERENCES_UNKNOWN_EVIDENCE",
    ):
        EvidenceCitationBinder(
            sources=_bundle().sources,
            policy=policy,
        )


def test_draft_proposal_rejects_secret_shaped_text() -> None:
    proposal = _proposal(*CLAIM_IDS).model_dump(mode="json")
    proposal["executive_summary"] = (
        "Authorization: Bearer private-vendor-secret-token"
    )

    with pytest.raises(ValidationError, match="secret-shaped"):
        DraftProposal.model_validate(proposal)


def test_checkpoint_report_draft_rejects_secret_shaped_text() -> None:
    proposal = _proposal(*CLAIM_IDS)
    draft = _binder(*CLAIM_IDS).bind(
        proposal=proposal,
        confirmed_requirements=_request(),
        available_evidence_ids=tuple(
            evidence_id
            for claim in proposal.claims
            for evidence_id in claim.evidence_ids
        ),
        revision=1,
    )
    payload = draft.model_dump(mode="json")
    payload["limitations"] = ["api_key=sk-test-report-secret"]

    with pytest.raises(ValidationError, match="secret-shaped"):
        ReportDraft.model_validate(payload)


def test_draft_contracts_reject_unknown_fields() -> None:
    payload = _proposal(*CLAIM_IDS).model_dump(mode="json")
    payload["output_path"] = "C:/untrusted/report.md"

    with pytest.raises(ValidationError, match="Extra inputs"):
        DraftProposal.model_validate(payload)
