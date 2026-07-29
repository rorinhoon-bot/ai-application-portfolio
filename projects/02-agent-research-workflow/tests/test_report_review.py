"""Unit tests for deterministic report review and bounded revision."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_research.data_loader import EvaluationBundle, load_evaluation_bundle
from agent_research.models import GoldClaim, ResearchInput
from agent_research.report_drafting import (
    DraftClaim,
    DraftPolicy,
    DraftProposal,
    EvidenceCitationBinder,
    ReportDraft,
)
from agent_research.report_review import (
    DeterministicDraftReviser,
    DeterministicReportReviewer,
    ReviewFindingCode,
    ReviewFinding,
    ReviewOutcome,
    ReviewPolicy,
    ReviewResult,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAIM_IDS = ("atlas-local-data", "atlas-durable-checkpoint")


def _bundle() -> EvaluationBundle:
    return load_evaluation_bundle(PROJECT_ROOT)


def _claims() -> tuple[GoldClaim, ...]:
    wanted = set(CLAIM_IDS)
    return tuple(
        claim for claim in _bundle().gold.claims if claim.claim_id in wanted
    )


def _request() -> ResearchInput:
    return next(
        case.input
        for case in _bundle().evaluation.cases
        if case.case_id == "privacy-durable-selection"
    )


def _proposal(summary: str = "AtlasFlow fits the approved constraints.") -> DraftProposal:
    return DraftProposal(
        writer_id="deterministic-writer-v1",
        executive_summary=summary,
        claims=tuple(
            DraftClaim.model_validate(claim.model_dump(mode="json"))
            for claim in _claims()
        ),
        recommendation_candidate_id="atlasflow",
        limitations=("Only the fixed synthetic snapshot was evaluated.",),
    )


def _draft(summary: str = "AtlasFlow fits the approved constraints.") -> ReportDraft:
    proposal = _proposal(summary)
    return EvidenceCitationBinder(
        sources=_bundle().sources,
        policy=DraftPolicy(
            policy_id="privacy-draft-policy",
            allowed_claims=_claims(),
            allowed_recommendations=("atlasflow",),
        ),
    ).bind(
        proposal=proposal,
        confirmed_requirements=_request(),
        available_evidence_ids=tuple(
            evidence_id
            for claim in proposal.claims
            for evidence_id in claim.evidence_ids
        ),
        revision=1,
    )


def _policy(
    *,
    candidates: tuple[str, ...] = ("atlasflow",),
    dimensions: tuple[str, ...] = ("privacy", "reliability"),
    forbidden: tuple[str, ...] = (),
) -> ReviewPolicy:
    return ReviewPolicy(
        policy_id="privacy-review-policy",
        required_candidate_ids=candidates,
        required_dimension_ids=dimensions,
        forbidden_statements=forbidden,
    )


def test_clean_draft_passes_initial_review() -> None:
    result = DeterministicReportReviewer(_policy()).review(
        draft=_draft(),
        confirmed_requirements=_request(),
        review_round=0,
    )

    assert result.outcome is ReviewOutcome.PASS
    assert result.review_round == 0
    assert result.findings == ()


def test_missing_candidate_and_dimension_request_revision() -> None:
    result = DeterministicReportReviewer(
        _policy(
            candidates=("atlasflow", "beaconflow"),
            dimensions=("privacy", "reliability", "cost"),
        )
    ).review(
        draft=_draft(),
        confirmed_requirements=_request(),
        review_round=0,
    )

    assert result.outcome is ReviewOutcome.REVISE
    assert {finding.code for finding in result.findings} == {
        ReviewFindingCode.MISSING_CANDIDATE_COVERAGE,
        ReviewFindingCode.MISSING_DIMENSION_COVERAGE,
    }


def test_same_findings_fail_after_two_automatic_revisions() -> None:
    result = DeterministicReportReviewer(
        _policy(
            candidates=("atlasflow", "beaconflow"),
            dimensions=("privacy", "reliability", "cost"),
        )
    ).review(
        draft=_draft(),
        confirmed_requirements=_request(),
        review_round=2,
    )

    assert result.outcome is ReviewOutcome.FAIL
    assert result.review_round == 2


def test_forbidden_assertion_is_detected_without_echoing_it() -> None:
    forbidden = "CedarFlow 可以完全离线运行"
    result = DeterministicReportReviewer(
        _policy(forbidden=(forbidden,))
    ).review(
        draft=_draft(f"错误结论：{forbidden}。"),
        confirmed_requirements=_request(),
        review_round=0,
    )

    assert result.outcome is ReviewOutcome.REVISE
    assert result.findings[0].code is ReviewFindingCode.FORBIDDEN_ASSERTION
    assert forbidden not in result.findings[0].safe_summary


def test_review_result_rejects_revision_request_at_limit() -> None:
    result = DeterministicReportReviewer(
        _policy(forbidden=("CedarFlow 可以完全离线运行",))
    ).review(
        draft=_draft("CedarFlow 可以完全离线运行。"),
        confirmed_requirements=_request(),
        review_round=2,
    )
    payload = result.model_dump(mode="json")
    payload["outcome"] = "REVISE"

    with pytest.raises(ValidationError, match="final review round"):
        ReviewResult.model_validate(payload)


def test_reviser_uses_persisted_round_not_memory_cursor() -> None:
    first = _proposal("First corrected draft summary.")
    second = _proposal("Second corrected draft summary.")
    restored_reviser = DeterministicDraftReviser((first, second))

    selected = restored_reviser.revise(next_review_round=2)

    assert selected == second
    assert restored_reviser.revision_count == 1


def test_review_contracts_reject_unknown_fields() -> None:
    payload = _policy().model_dump(mode="json")
    payload["api_key"] = "must-not-enter-review-policy"

    with pytest.raises(ValidationError, match="Extra inputs"):
        ReviewPolicy.model_validate(payload)


def test_review_finding_rejects_secret_shaped_summary() -> None:
    with pytest.raises(ValidationError, match="secret-shaped"):
        ReviewFinding(
            finding_id="unsafe-finding",
            code=ReviewFindingCode.FORBIDDEN_ASSERTION,
            safe_summary="Authorization: Bearer private-review-secret",
        )
