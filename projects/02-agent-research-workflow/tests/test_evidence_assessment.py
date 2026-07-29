"""Unit tests for deterministic evidence sufficiency contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_research.data_loader import load_evaluation_bundle
from agent_research.evidence_assessment import (
    DeterministicEvidenceAssessor,
    EvidenceAssessment,
    EvidenceAssessmentStatus,
    EvidencePolicy,
    EvidenceRequirement,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_EVIDENCE = "cedarflow-overview-v1#deployment-model"


def _policy() -> EvidencePolicy:
    return EvidencePolicy(
        policy_id="offline-proof-policy",
        requirements=(
            EvidenceRequirement(
                requirement_id="deployment-model",
                description="CedarFlow deployment model is documented.",
                acceptable_evidence_sets=((DEPLOYMENT_EVIDENCE,),),
            ),
            EvidenceRequirement(
                requirement_id="complete-offline-proof",
                description="Complete offline operation is explicitly proven.",
                acceptable_evidence_sets=(),
            ),
        ),
    )


def _assessor() -> DeterministicEvidenceAssessor:
    bundle = load_evaluation_bundle(PROJECT_ROOT)
    return DeterministicEvidenceAssessor(
        sources=bundle.sources,
        policy=_policy(),
    )


def test_first_round_with_gaps_requests_one_more_retrieval() -> None:
    assessment = _assessor().assess(
        evidence_ids=(DEPLOYMENT_EVIDENCE,),
        retrieval_round=1,
    )

    assert (
        assessment.status
        is EvidenceAssessmentStatus.NEEDS_MORE_EVIDENCE
    )
    assert assessment.satisfied_requirement_ids == ("deployment-model",)
    assert assessment.gap_requirement_ids == ("complete-offline-proof",)


def test_second_round_with_same_semantic_gap_is_stably_insufficient() -> None:
    assessment = _assessor().assess(
        evidence_ids=(
            DEPLOYMENT_EVIDENCE,
            "cedarflow-security-cost-v1#data-boundary",
        ),
        retrieval_round=2,
    )

    assert assessment.status is EvidenceAssessmentStatus.INSUFFICIENT
    assert assessment.gap_requirement_ids == ("complete-offline-proof",)


def test_all_requirements_satisfied_stops_without_extra_round() -> None:
    policy = EvidencePolicy(
        policy_id="deployment-only-policy",
        requirements=(
            EvidenceRequirement(
                requirement_id="deployment-model",
                description="Deployment model evidence is present.",
                acceptable_evidence_sets=((DEPLOYMENT_EVIDENCE,),),
            ),
        ),
    )
    bundle = load_evaluation_bundle(PROJECT_ROOT)
    assessor = DeterministicEvidenceAssessor(
        sources=bundle.sources,
        policy=policy,
    )

    assessment = assessor.assess(
        evidence_ids=(DEPLOYMENT_EVIDENCE,),
        retrieval_round=1,
    )

    assert assessment.status is EvidenceAssessmentStatus.SUFFICIENT
    assert assessment.gap_requirement_ids == ()


def test_policy_rejects_unknown_fixed_evidence() -> None:
    bundle = load_evaluation_bundle(PROJECT_ROOT)
    policy = EvidencePolicy(
        policy_id="unknown-evidence-policy",
        requirements=(
            EvidenceRequirement(
                requirement_id="unknown-proof",
                description="Unknown proof must not enter policy.",
                acceptable_evidence_sets=(("unknown-source#unknown-section",),),
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="EVIDENCE_POLICY_REFERENCES_UNKNOWN_EVIDENCE",
    ):
        DeterministicEvidenceAssessor(
            sources=bundle.sources,
            policy=policy,
        )


def test_assessment_rejects_final_round_needs_more_status() -> None:
    with pytest.raises(ValidationError, match="final retrieval round"):
        EvidenceAssessment(
            policy_id="offline-proof-policy",
            status=EvidenceAssessmentStatus.NEEDS_MORE_EVIDENCE,
            retrieval_round=2,
            gap_requirement_ids=("complete-offline-proof",),
        )


def test_evidence_contracts_reject_unknown_fields() -> None:
    payload = _policy().model_dump(mode="json")
    payload["api_key"] = "must-not-enter-policy"

    with pytest.raises(ValidationError, match="Extra inputs"):
        EvidencePolicy.model_validate(payload)
