"""Offline tests for runtime-only node events and run summaries."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from agent_research.data_loader import load_evaluation_bundle
from agent_research.evaluation_runner import run_case_observability
from agent_research.models import HumanActionKind, ToolOutcomeKind
from agent_research.observability import (
    DeterministicClock,
    NodeEvent,
    NodeOutcome,
    RunObserver,
    RunSummary,
)
from agent_research.runtime_state import RuntimeNode, RuntimeState, RuntimeStatus
from agent_research.workflow import (
    build_requirements_graph,
    create_initial_state,
    workflow_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUMMARY_PATH = (
    PROJECT_ROOT
    / "evals"
    / "results"
    / "privacy-durable-run-summary.json"
)


@pytest.fixture(scope="module")
def success_summary() -> RunSummary:
    return run_case_observability(PROJECT_ROOT)


def test_deterministic_clock_validates_bounds_and_steps() -> None:
    clock = DeterministicClock(initial_ns=10, step_ns=5)
    assert (clock.now_ns(), clock.now_ns(), clock.now_ns()) == (10, 15, 20)
    with pytest.raises(ValueError, match="CLOCK_INITIAL"):
        DeterministicClock(initial_ns=-1)
    with pytest.raises(ValueError, match="CLOCK_STEP"):
        DeterministicClock(step_ns=0)


def test_success_summary_records_nodes_actions_and_zero_model_usage(
    success_summary: RunSummary,
) -> None:
    assert success_summary.final_status is RuntimeStatus.COMPLETED
    assert success_summary.node_event_count == 13
    assert success_summary.interrupted_node_count == 2
    assert success_summary.observed_node_duration_ns == 13_000_000
    assert success_summary.tool_attempt_count == 1
    assert success_summary.retry_count == 0
    assert success_summary.review_attempt_count == 1
    assert success_summary.automatic_revision_count == 0
    assert success_summary.export_attempt_count == 1
    assert success_summary.human_actions == (
        HumanActionKind.APPROVE,
        HumanActionKind.APPROVE,
    )
    assert success_summary.model_call_count == 0
    assert success_summary.input_token_count == 0
    assert success_summary.output_token_count == 0
    assert success_summary.known_cost_microunits == 0
    assert success_summary.artifact_id is not None

    tool_event = next(
        event
        for event in success_summary.events
        if event.node is RuntimeNode.EXECUTE_TOOLS
    )
    assert tool_event.tool_outcome is ToolOutcomeKind.SUCCESS
    assert tool_event.error_code is None


def test_revision_retry_failure_and_pause_summaries_are_distinct() -> None:
    revised = run_case_observability(
        PROJECT_ROOT,
        case_id="report-revision-approved",
    )
    transient = run_case_observability(
        PROJECT_ROOT,
        case_id="transient-search-recovers",
    )
    failed = run_case_observability(
        PROJECT_ROOT,
        case_id="missing-offline-proof",
    )
    waiting = run_case_observability(
        PROJECT_ROOT,
        case_id="missing-candidates",
    )

    assert revised.human_actions == (
        HumanActionKind.APPROVE,
        HumanActionKind.REQUEST_CHANGES,
        HumanActionKind.APPROVE,
    )
    assert revised.human_revision_count == 1
    assert revised.review_attempt_count == 2
    assert revised.export_attempt_count == 1
    assert transient.tool_attempt_count == 2
    assert transient.retry_count == 1
    assert "source-timeout" in transient.error_codes
    assert failed.final_status is RuntimeStatus.FAILED
    assert failed.retrieval_rounds == 2
    assert "evidence-insufficient" in failed.error_codes
    assert waiting.final_status is RuntimeStatus.NEEDS_HUMAN
    assert waiting.interrupted_node_count == 1
    assert waiting.human_decision_count == 0


def test_failed_node_observation_does_not_store_raw_exception() -> None:
    case = load_evaluation_bundle(PROJECT_ROOT).evaluation.cases[0]
    state = RuntimeState(
        run_id="run-observer-error",
        thread_id="thread-observer-error",
        raw_request=case.input,
    )
    observer = RunObserver(
        run_id=state.run_id,
        thread_id=state.thread_id,
        clock=DeterministicClock(),
    )

    def fail(_: RuntimeState) -> dict[str, object]:
        raise ValueError("Authorization: Bearer private-vendor-value")

    with pytest.raises(ValueError, match="Authorization"):
        observer.observe(
            state,
            node=RuntimeNode.VALIDATE_REQUEST,
            operation=fail,
        )

    event = observer.events[0]
    assert event.outcome is NodeOutcome.FAILED
    assert event.error_code == "node-exception"
    assert "private-vendor-value" not in event.model_dump_json()


def test_event_and_summary_contracts_reject_tampering(
    success_summary: RunSummary,
) -> None:
    event_payload = success_summary.events[0].model_dump(mode="json")
    event_payload["unknown_payload"] = {"prompt": "must not enter trace"}
    with pytest.raises(ValidationError, match="Extra inputs"):
        NodeEvent.model_validate(event_payload)

    summary_payload = success_summary.model_dump(mode="json")
    summary_payload["tool_attempt_count"] = 12
    with pytest.raises(ValidationError, match="summary_hash"):
        RunSummary.model_validate(summary_payload)


def test_observer_identity_mismatch_stops_before_node_execution() -> None:
    case = load_evaluation_bundle(PROJECT_ROOT).evaluation.cases[0]
    state = RuntimeState(
        run_id="run-correct",
        thread_id="thread-correct",
        raw_request=case.input,
    )
    observer = RunObserver(
        run_id="run-another",
        thread_id="thread-correct",
        clock=DeterministicClock(),
    )
    called = False

    def operation(_: RuntimeState) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    with pytest.raises(ValueError, match="OBSERVER_RUN_IDENTITY_MISMATCH"):
        observer.observe(
            state,
            node=RuntimeNode.VALIDATE_REQUEST,
            operation=operation,
        )
    assert called is False
    assert observer.events == ()


def test_observer_and_sensitive_values_do_not_enter_checkpoint(
    tmp_path: Path,
) -> None:
    case = next(
        item
        for item in load_evaluation_bundle(PROJECT_ROOT).evaluation.cases
        if item.case_id == "missing-candidates"
    )
    checkpoint = tmp_path / "observed.sqlite3"
    observer = RunObserver(
        run_id="run-observed-pause",
        thread_id="thread-observed-pause",
        clock=DeterministicClock(),
    )
    config = workflow_config(observer.thread_id)

    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_requirements_graph(saver, observer=observer)
        graph.invoke(
            create_initial_state(
                run_id=observer.run_id,
                thread_id=observer.thread_id,
                request=case.input,
            ),
            config,
        )

    raw = checkpoint.read_bytes().lower()
    for forbidden in (
        b"runobserver",
        b"deterministicclock",
        b"node-event-v1",
        b"authorization: bearer",
        b"api_key=",
        b"cookie:",
        b"private-vendor-response",
    ):
        assert forbidden not in raw


def test_committed_summary_matches_fresh_deterministic_run(
    success_summary: RunSummary,
) -> None:
    committed = RunSummary.model_validate_json(
        SUMMARY_PATH.read_text(encoding="utf-8")
    )
    assert committed == success_summary
    assert committed.to_json() == SUMMARY_PATH.read_text(encoding="utf-8")
    assert run_case_observability(PROJECT_ROOT).to_json() == committed.to_json()


def test_summary_json_contains_no_runtime_paths_or_sensitive_payload(
    success_summary: RunSummary,
) -> None:
    lowered = success_summary.to_json().lower()
    for forbidden in (
        "api_key=",
        "authorization:",
        "cookie:",
        "bearer ",
        "sqlite3",
        "p2-observability-",
        str(PROJECT_ROOT).lower(),
        "prompt",
        "response",
    ):
        assert forbidden not in lowered
