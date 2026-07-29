"""Tests for deterministic fake tool scope and result normalization."""

from __future__ import annotations

from pathlib import Path

from agent_research.data_loader import load_evaluation_bundle
from agent_research.fake_tools import DeterministicFakeToolExecutor
from agent_research.models import (
    ResearchInput,
    ScriptedToolOutcome,
    ToolOutcomeKind,
)
from agent_research.tool_contracts import (
    SOURCE_SNAPSHOT_V1,
    ReadSourceArgs,
    SearchSourcesArgs,
    ToolCall,
    ToolName,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _request() -> ResearchInput:
    return ResearchInput.model_validate(
        {
            "research_question": "比较恢复能力。",
            "audience": "开发团队",
            "constraints": ["结论必须有证据"],
            "candidates": ["atlasflow", "beaconflow"],
            "dimensions": [
                {"dimension_id": "reliability", "weight_percent": 100}
            ],
            "source_policy_id": "synthetic-v1",
        }
    )


def _search_call(
    candidates: tuple[str, ...] = ("atlasflow", "beaconflow"),
) -> ToolCall:
    return ToolCall(
        call_id="reliability-search",
        tool_name=ToolName.SEARCH_SOURCES,
        arguments=SearchSourcesArgs(
            query="checkpoint recovery",
            candidate_ids=candidates,
            source_types=("reliability",),
            top_k=2,
        ),
    )


def _executor(
    outcomes: tuple[ScriptedToolOutcome, ...],
) -> DeterministicFakeToolExecutor:
    bundle = load_evaluation_bundle(PROJECT_ROOT)
    return DeterministicFakeToolExecutor(
        sources=bundle.sources,
        outcomes=outcomes,
    )


def test_valid_scripted_search_returns_only_normalized_evidence() -> None:
    executor = _executor(
        (
            ScriptedToolOutcome(
                call_id="fixture-search",
                tool_name="search_sources",
                outcome=ToolOutcomeKind.SUCCESS,
                evidence_ids=(
                    "atlasflow-reliability-v1#checkpointing",
                ),
            ),
        )
    )

    result = executor.execute(
        call=_search_call(),
        confirmed=_request(),
        source_snapshot_id=SOURCE_SNAPSHOT_V1,
        attempt=1,
    )

    assert result.outcome is ToolOutcomeKind.SUCCESS
    assert result.evidence_ids == (
        "atlasflow-reliability-v1#checkpointing",
    )
    assert result.error_code is None
    assert executor.execution_count == 1


def test_candidate_outside_approved_scope_stops_before_execution() -> None:
    executor = _executor(())

    result = executor.execute(
        call=_search_call(("cedarflow",)),
        confirmed=_request(),
        source_snapshot_id=SOURCE_SNAPSHOT_V1,
        attempt=1,
    )

    assert result.outcome is ToolOutcomeKind.DETERMINISTIC_ERROR
    assert result.error_code == "invalid-arguments"
    assert executor.execution_count == 0


def test_unknown_source_stops_before_execution() -> None:
    executor = _executor(())
    call = ToolCall(
        call_id="unknown-source-read",
        tool_name=ToolName.READ_SOURCE,
        arguments=ReadSourceArgs(
            source_id="unknown-source",
            section_id="unknown-section",
        ),
    )

    result = executor.execute(
        call=call,
        confirmed=_request(),
        source_snapshot_id=SOURCE_SNAPSHOT_V1,
        attempt=1,
    )

    assert result.outcome is ToolOutcomeKind.DETERMINISTIC_ERROR
    assert result.error_code == "invalid-arguments"
    assert executor.execution_count == 0


def test_attempt_number_selects_script_without_mutable_cursor() -> None:
    executor = _executor(
        (
            ScriptedToolOutcome(
                call_id="fixture-timeout",
                tool_name="search_sources",
                outcome=ToolOutcomeKind.TRANSIENT_ERROR,
                error_code="source-timeout",
            ),
            ScriptedToolOutcome(
                call_id="fixture-success",
                tool_name="search_sources",
                outcome=ToolOutcomeKind.SUCCESS,
                evidence_ids=(
                    "atlasflow-reliability-v1#checkpointing",
                ),
            ),
        )
    )
    call = _search_call()

    second = executor.execute(
        call=call,
        confirmed=_request(),
        source_snapshot_id=SOURCE_SNAPSHOT_V1,
        attempt=2,
    )
    first = executor.execute(
        call=call,
        confirmed=_request(),
        source_snapshot_id=SOURCE_SNAPSHOT_V1,
        attempt=1,
    )

    assert second.outcome is ToolOutcomeKind.SUCCESS
    assert first.outcome is ToolOutcomeKind.TRANSIENT_ERROR
    assert first.logical_call_key == second.logical_call_key


def test_unknown_scripted_evidence_is_converted_to_safe_failure() -> None:
    executor = _executor(
        (
            ScriptedToolOutcome(
                call_id="fixture-unknown-evidence",
                tool_name="search_sources",
                outcome=ToolOutcomeKind.SUCCESS,
                evidence_ids=("unknown-source#unknown-section",),
            ),
        )
    )

    result = executor.execute(
        call=_search_call(),
        confirmed=_request(),
        source_snapshot_id=SOURCE_SNAPSHOT_V1,
        attempt=1,
    )

    assert result.outcome is ToolOutcomeKind.DETERMINISTIC_ERROR
    assert result.error_code == "invalid-script"
    assert result.evidence_ids == ()


def test_known_but_out_of_scope_evidence_is_rejected() -> None:
    executor = _executor(
        (
            ScriptedToolOutcome(
                call_id="fixture-out-of-scope-evidence",
                tool_name="search_sources",
                outcome=ToolOutcomeKind.SUCCESS,
                evidence_ids=(
                    "cedarflow-reliability-v1#checkpointing",
                ),
            ),
        )
    )

    result = executor.execute(
        call=_search_call(),
        confirmed=_request(),
        source_snapshot_id=SOURCE_SNAPSHOT_V1,
        attempt=1,
    )

    assert result.outcome is ToolOutcomeKind.DETERMINISTIC_ERROR
    assert result.error_code == "invalid-script"
    assert result.evidence_ids == ()


def test_script_exhaustion_is_deterministic_not_retryable() -> None:
    executor = _executor(())

    result = executor.execute(
        call=_search_call(),
        confirmed=_request(),
        source_snapshot_id=SOURCE_SNAPSHOT_V1,
        attempt=1,
    )

    assert result.outcome is ToolOutcomeKind.DETERMINISTIC_ERROR
    assert result.error_code == "script-exhausted"
