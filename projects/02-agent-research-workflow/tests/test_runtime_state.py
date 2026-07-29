"""Tests for versioned checkpoint-safe runtime contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_research.models import HumanActionKind, ResearchInput
from agent_research.runtime_state import (
    RequirementsDecision,
    RuntimeState,
    SafeStateError,
)


def _request() -> ResearchInput:
    return ResearchInput.model_validate(
        {
            "research_question": "比较 AtlasFlow 与 BeaconFlow。",
            "audience": "开发团队",
            "constraints": ["结论必须有证据"],
            "candidates": ["atlasflow", "beaconflow"],
            "dimensions": [
                {"dimension_id": "reliability", "weight_percent": 100}
            ],
            "source_policy_id": "synthetic-v1",
        }
    )


def _state_payload() -> dict[str, object]:
    return {
        "run_id": "run-state-test",
        "thread_id": "thread-state-test",
        "raw_request": _request().model_dump(mode="json"),
    }


def test_runtime_state_has_explicit_checkpoint_business_fields() -> None:
    state = RuntimeState.model_validate(_state_payload())

    assert set(state.model_dump(mode="json")) >= {
        "schema_version",
        "run_id",
        "thread_id",
        "status",
        "current_node",
        "source_snapshot_id",
        "raw_request",
        "confirmed_requirements",
        "human_confirmation_revision",
        "pending_tool_call",
        "last_tool_result",
        "tool_call_budget",
        "tool_attempts",
        "retrieval_rounds",
        "review_rounds",
        "human_revision_count",
        "evidence_ids",
        "evidence_policy_id",
        "evidence_gaps",
        "last_evidence_assessment",
        "errors",
        "report_revision",
        "report_hash",
        "report_draft",
        "review_policy_id",
        "last_review_result",
        "artifact_id",
        "idempotency_key",
    }


def test_runtime_state_rejects_unknown_fields() -> None:
    payload = _state_payload()
    payload["api_key"] = "must-not-enter-checkpoint"

    with pytest.raises(ValidationError, match="Extra inputs"):
        RuntimeState.model_validate(payload)


def test_runtime_state_rejects_another_source_snapshot() -> None:
    payload = _state_payload()
    payload["source_snapshot_id"] = "f" * 64

    with pytest.raises(ValidationError, match="source_snapshot_id"):
        RuntimeState.model_validate(payload)


def test_runtime_state_rejects_evidence_status_with_old_graph_version() -> None:
    payload = _state_payload()
    payload.update(
        {
            "status": "EVIDENCE_PENDING_ASSESSMENT",
            "current_node": "assess_evidence",
            "retrieval_rounds": 1,
            "evidence_policy_id": "test-evidence-policy",
            "pending_tool_call": {
                "schema_version": "tool-call-v1",
                "call_id": "test-search",
                "tool_name": "search_sources",
                "arguments": {
                    "schema_version": "search-sources-args-v1",
                    "query": "test evidence",
                    "candidate_ids": ["atlasflow"],
                    "source_types": ["overview"],
                    "top_k": 1,
                },
            },
            "confirmed_requirements": _request().model_dump(mode="json"),
            "plan_id": "a" * 64,
        }
    )

    with pytest.raises(ValidationError, match="graph version"):
        RuntimeState.model_validate(payload)


def test_runtime_state_rejects_assessment_disguised_as_new_state() -> None:
    payload = _state_payload()
    payload.update(
        {
            "retrieval_rounds": 2,
            "evidence_ids": [
                "cedarflow-overview-v1#deployment-model",
            ],
            "evidence_policy_id": "offline-proof-policy",
            "evidence_gaps": ["complete-offline-proof"],
            "last_evidence_assessment": {
                "policy_id": "offline-proof-policy",
                "status": "INSUFFICIENT",
                "retrieval_round": 2,
                "gap_requirement_ids": ["complete-offline-proof"],
                "evidence_ids": [
                    "cedarflow-overview-v1#deployment-model",
                ],
            },
        }
    )

    with pytest.raises(ValidationError, match="assessment status mismatch"):
        RuntimeState.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("human_confirmation_revision", 33),
        ("tool_call_budget", 4),
        ("tool_attempts", 4),
        ("retrieval_rounds", 3),
        ("review_rounds", 3),
        ("human_revision_count", 3),
        ("report_revision", 33),
    ],
)
def test_runtime_state_rejects_out_of_bounds_counts(
    field: str,
    value: int,
) -> None:
    payload = _state_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match="less than or equal"):
        RuntimeState.model_validate(payload)


def test_tool_attempts_cannot_exceed_smaller_runtime_budget() -> None:
    payload = _state_payload()
    payload["tool_call_budget"] = 2
    payload["tool_attempts"] = 3

    with pytest.raises(ValidationError, match="tool_call_budget"):
        RuntimeState.model_validate(payload)


def test_checkpoint_error_summary_rejects_secret_shaped_text() -> None:
    with pytest.raises(ValidationError, match="secret-shaped"):
        SafeStateError.model_validate(
            {
                "code": "vendor-error",
                "node": "validate_request",
                "safe_summary": "Authorization: Bearer secret-token-value",
            }
        )


def test_runtime_state_rejects_secret_shaped_request_text() -> None:
    payload = _state_payload()
    request = _request().model_dump(mode="json")
    request["constraints"] = ["api_key=sk-test-checkpoint-secret"]
    payload["raw_request"] = request

    with pytest.raises(ValidationError, match="secret-shaped"):
        RuntimeState.model_validate(payload)


def test_edit_decision_requires_a_replacement_request() -> None:
    with pytest.raises(ValidationError, match="edited_request"):
        RequirementsDecision.model_validate(
            {
                "run_id": "run-state-test",
                "thread_id": "thread-state-test",
                "expected_revision": 1,
                "expected_request_hash": "a" * 64,
                "action": HumanActionKind.EDIT,
            }
        )
