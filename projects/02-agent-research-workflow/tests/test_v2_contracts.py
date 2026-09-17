"""V2 contract and answer-independence tests."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from agent_research.v2.contracts import (
    BudgetAuthorization,
    CandidateSpec,
    DimensionSpec,
    EvidenceCell,
    ResearchRequestV2,
    Usage,
)


def _request() -> ResearchRequestV2:
    return ResearchRequestV2(
        research_question="Choose a workflow framework for a small AI team.",
        audience="student engineering team",
        candidates=(
            CandidateSpec(candidate_id="langgraph", name="LangGraph"),
            CandidateSpec(candidate_id="pydantic-ai", name="PydanticAI"),
        ),
        dimensions=(
            DimensionSpec(dimension_id="tool-calling", question="Does it support tools?", weight_percent=34),
            DimensionSpec(dimension_id="human-approval", question="Can a human approve?", weight_percent=33),
            DimensionSpec(dimension_id="recovery", question="Can it recover?", weight_percent=33),
        ),
        hard_constraints=("must run locally",),
        source_snapshot_id="snapshot-v2-dev",
        model_config_hash=hashlib.sha256(b"scripted-v2").hexdigest(),
        budget_authorization_id="budget-dev",
    )


def test_request_hash_stable_and_scope_is_strict() -> None:
    request = _request()
    assert request.content_hash() == request.model_copy().content_hash()
    with pytest.raises(ValidationError, match="2 to 4 candidates"):
        ResearchRequestV2.model_validate(
            request.model_dump(mode="json") | {"candidates": (request.candidates[0].model_dump(mode="json"),)}
        )


def test_unknown_is_not_allowed_to_carry_evidence() -> None:
    with pytest.raises(ValidationError, match="unknown evidence cell"):
        EvidenceCell(
            candidate_id="langgraph",
            dimension_id="recovery",
            status="unknown",
            claim="Unknown",
            evidence_ids=("source-one#recovery",),
        )


def test_usage_does_not_turn_unknown_cost_into_zero() -> None:
    unknown = Usage(cost_status="unknown")
    assert unknown.cost_minor_units is None
    with pytest.raises(ValidationError, match="known cost"):
        Usage(cost_status="known")


def test_budget_requires_explicit_approval() -> None:
    budget = BudgetAuthorization(
        authorization_id="budget-dev",
        max_cost_minor_units=500,
        max_model_calls=12,
        max_input_tokens=48_000,
        max_output_tokens=12_000,
        expires_at="2099-01-01T00:00:00Z",
    )
    assert budget.approved is False
