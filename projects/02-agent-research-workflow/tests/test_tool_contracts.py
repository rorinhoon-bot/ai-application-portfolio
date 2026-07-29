"""Tests for strict read-only Tool Calling contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_research.models import ToolOutcomeKind
from agent_research.tool_contracts import (
    SOURCE_SNAPSHOT_V1,
    CalculateComparisonArgs,
    ReadSourceArgs,
    SearchSourcesArgs,
    ToolCall,
    ToolName,
    ToolResult,
    compute_tool_call_key,
)


def _search_call() -> ToolCall:
    return ToolCall(
        call_id="reliability-search",
        tool_name=ToolName.SEARCH_SOURCES,
        arguments=SearchSourcesArgs(
            query="checkpoint recovery",
            candidate_ids=("atlasflow", "beaconflow"),
            source_types=("reliability",),
            top_k=2,
        ),
    )


def test_all_allowlisted_tool_argument_contracts_validate() -> None:
    search = _search_call()
    read = ToolCall(
        call_id="read-checkpoint",
        tool_name=ToolName.READ_SOURCE,
        arguments=ReadSourceArgs(
            source_id="atlasflow-reliability-v1",
            section_id="checkpointing",
        ),
    )
    comparison = ToolCall(
        call_id="compare-reliability",
        tool_name=ToolName.CALCULATE_COMPARISON,
        arguments=CalculateComparisonArgs.model_validate(
            {
                "weights": [
                    {
                        "dimension_id": "reliability",
                        "weight_percent": 100,
                    }
                ],
                "candidates": [
                    {
                        "candidate_id": "atlasflow",
                        "dimensions": [
                            {
                                "dimension_id": "reliability",
                                "score": 5,
                                "evidence_ids": [
                                    "atlasflow-reliability-v1#checkpointing"
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
    )

    assert search.tool_name is ToolName.SEARCH_SOURCES
    assert read.tool_name is ToolName.READ_SOURCE
    assert comparison.tool_name is ToolName.CALCULATE_COMPARISON


def test_unknown_tool_name_is_rejected() -> None:
    payload = _search_call().model_dump(mode="json")
    payload["tool_name"] = "delete_all"

    with pytest.raises(ValidationError, match="delete_all"):
        ToolCall.model_validate(payload)


@pytest.mark.parametrize("forbidden_field", ["url", "path", "command"])
def test_search_arguments_reject_unapproved_fields(
    forbidden_field: str,
) -> None:
    payload = _search_call().model_dump(mode="json")
    payload["arguments"][forbidden_field] = "untrusted-value"

    with pytest.raises(ValidationError, match="Extra inputs"):
        ToolCall.model_validate(payload)


def test_tool_name_must_match_argument_contract() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        ToolCall(
            call_id="mismatched-call",
            tool_name=ToolName.READ_SOURCE,
            arguments=_search_call().arguments,
        )


@pytest.mark.parametrize("top_k", [0, 9])
def test_search_top_k_bounds_are_enforced(top_k: int) -> None:
    payload = _search_call().model_dump(mode="json")
    payload["arguments"]["top_k"] = top_k

    with pytest.raises(ValidationError):
        ToolCall.model_validate(payload)


def test_comparison_requires_weights_to_sum_to_100() -> None:
    with pytest.raises(ValidationError, match="sum to 100"):
        CalculateComparisonArgs.model_validate(
            {
                "weights": [
                    {"dimension_id": "cost", "weight_percent": 40},
                    {"dimension_id": "reliability", "weight_percent": 40},
                ],
                "candidates": [
                    {
                        "candidate_id": "atlasflow",
                        "dimensions": [
                            {"dimension_id": "cost", "score": 2},
                            {"dimension_id": "reliability", "score": 5},
                        ],
                    }
                ],
            }
        )


def test_failed_result_rejects_evidence_and_requires_safe_error() -> None:
    call = _search_call()
    key = compute_tool_call_key(call, SOURCE_SNAPSHOT_V1)

    with pytest.raises(ValidationError, match="cannot contain evidence"):
        ToolResult(
            logical_call_key=key,
            call_id=call.call_id,
            tool_name=call.tool_name,
            outcome=ToolOutcomeKind.TRANSIENT_ERROR,
            attempt=1,
            evidence_ids=(
                "atlasflow-reliability-v1#checkpointing",
            ),
            error_code="source-timeout",
            safe_summary="source search timed out",
        )


def test_tool_result_rejects_secret_shaped_error_summary() -> None:
    call = _search_call()

    with pytest.raises(ValidationError, match="secret-shaped"):
        ToolResult(
            logical_call_key=compute_tool_call_key(
                call,
                SOURCE_SNAPSHOT_V1,
            ),
            call_id=call.call_id,
            tool_name=call.tool_name,
            outcome=ToolOutcomeKind.DETERMINISTIC_ERROR,
            attempt=1,
            error_code="vendor-error",
            safe_summary="Authorization: Bearer secret-token-value",
        )


def test_tool_result_rejects_raw_vendor_response_field() -> None:
    call = _search_call()
    payload = ToolResult(
        logical_call_key=compute_tool_call_key(
            call,
            SOURCE_SNAPSHOT_V1,
        ),
        call_id=call.call_id,
        tool_name=call.tool_name,
        outcome=ToolOutcomeKind.SUCCESS,
        attempt=1,
        evidence_ids=(
            "atlasflow-reliability-v1#checkpointing",
        ),
    ).model_dump(mode="json")
    payload["raw_vendor_response"] = "must-not-enter-checkpoint"

    with pytest.raises(ValidationError, match="Extra inputs"):
        ToolResult.model_validate(payload)


def test_logical_call_key_is_stable_and_snapshot_bound() -> None:
    call = _search_call()

    first = compute_tool_call_key(call, SOURCE_SNAPSHOT_V1)
    second = compute_tool_call_key(call, SOURCE_SNAPSHOT_V1)
    other_snapshot = compute_tool_call_key(call, "f" * 64)

    assert first == second
    assert first != other_snapshot
