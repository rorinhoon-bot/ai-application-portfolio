"""Offline LangGraph tests for tool retry and deterministic stop paths."""

from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent_research.data_loader import load_evaluation_bundle
from agent_research.fake_tools import DeterministicFakeToolExecutor
from agent_research.models import (
    HumanActionKind,
    ScriptedToolOutcome,
    ToolOutcomeKind,
    WorkflowCase,
)
from agent_research.runtime_state import RuntimeState, RuntimeStatus
from agent_research.tool_contracts import (
    ReadSourceArgs,
    SearchSourcesArgs,
    ToolCall,
    ToolName,
)
from agent_research.workflow import (
    build_tool_execution_graph,
    create_initial_state,
    workflow_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _case(case_id: str) -> WorkflowCase:
    bundle = load_evaluation_bundle(PROJECT_ROOT)
    return next(
        case for case in bundle.evaluation.cases if case.case_id == case_id
    )


def _executor(
    outcomes: tuple[ScriptedToolOutcome, ...],
) -> DeterministicFakeToolExecutor:
    bundle = load_evaluation_bundle(PROJECT_ROOT)
    return DeterministicFakeToolExecutor(
        sources=bundle.sources,
        outcomes=outcomes,
    )


def _decision(state: RuntimeState) -> dict[str, object]:
    return {
        "schema_version": "requirements-decision-v1",
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "expected_revision": state.human_confirmation_revision,
        "expected_request_hash": state.confirmation_request_hash,
        "action": HumanActionKind.APPROVE.value,
    }


def _snapshot(graph: object, config: dict[str, object]) -> RuntimeState:
    state = graph.get_state(config)  # type: ignore[attr-defined]
    return RuntimeState.model_validate(state.values)


def _run_approved(
    *,
    checkpoint: Path,
    case: WorkflowCase,
    tool_call: ToolCall,
    executor: DeterministicFakeToolExecutor,
) -> RuntimeState:
    config = workflow_config(f"thread-{case.case_id}")
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_tool_execution_graph(
            checkpointer=saver,
            tool_call=tool_call,
            executor=executor,
        )
        graph.invoke(
            create_initial_state(
                run_id=f"run-{case.case_id}",
                thread_id=f"thread-{case.case_id}",
                request=case.input,
            ),
            config,
        )
        waiting = _snapshot(graph, config)
        graph.invoke(Command(resume=_decision(waiting)), config)
        final = _snapshot(graph, config)
        assert graph.get_state(config).next == ()
        return final


def test_workflow_v1_transient_tool_case_retries_then_stops_at_evidence(
    tmp_path: Path,
) -> None:
    case = _case("transient-search-recovers")
    call = ToolCall(
        call_id="reliability-search",
        tool_name=ToolName.SEARCH_SOURCES,
        arguments=SearchSourcesArgs(
            query="checkpoint recovery",
            candidate_ids=case.input.candidates,
            source_types=("reliability",),
            top_k=2,
        ),
    )
    executor = _executor(case.tool_outcomes)

    final = _run_approved(
        checkpoint=tmp_path / "transient.sqlite3",
        case=case,
        tool_call=call,
        executor=executor,
    )

    assert final.status is RuntimeStatus.EVIDENCE_READY
    assert final.tool_attempts == case.expected.max_tool_attempts == 2
    assert set(case.expected.required_evidence_ids) <= set(final.evidence_ids)
    assert final.last_tool_result is not None
    assert final.last_tool_result.outcome is ToolOutcomeKind.SUCCESS
    assert len(final.errors) == 1
    assert final.errors[0].code == "source-timeout"
    assert final.errors[0].retryable is True
    assert executor.execution_count == 2


def test_workflow_v1_invalid_arguments_fail_once_without_execution(
    tmp_path: Path,
) -> None:
    case = _case("invalid-tool-arguments")
    call = ToolCall(
        call_id="invalid-read",
        tool_name=ToolName.READ_SOURCE,
        arguments=ReadSourceArgs(
            source_id="unknown-source",
            section_id="unknown-section",
        ),
    )
    executor = _executor(case.tool_outcomes)

    final = _run_approved(
        checkpoint=tmp_path / "invalid.sqlite3",
        case=case,
        tool_call=call,
        executor=executor,
    )

    assert final.status is RuntimeStatus.FAILED
    assert final.tool_attempts == case.expected.max_tool_attempts == 1
    assert final.evidence_ids == ()
    assert final.errors[-1].code == "invalid-arguments"
    assert final.errors[-1].retryable is False
    assert executor.execution_count == 0


def test_transient_errors_stop_at_hard_retry_limit(
    tmp_path: Path,
) -> None:
    case = _case("transient-search-recovers")
    outcomes = tuple(
        ScriptedToolOutcome(
            call_id=f"timeout-{attempt}",
            tool_name="search_sources",
            outcome=ToolOutcomeKind.TRANSIENT_ERROR,
            error_code="source-timeout",
        )
        for attempt in range(1, 4)
    )
    executor = _executor(outcomes)
    call = ToolCall(
        call_id="exhausted-search",
        tool_name=ToolName.SEARCH_SOURCES,
        arguments=SearchSourcesArgs(
            query="checkpoint recovery",
            candidate_ids=case.input.candidates,
            source_types=("reliability",),
            top_k=2,
        ),
    )

    final = _run_approved(
        checkpoint=tmp_path / "exhausted.sqlite3",
        case=case,
        tool_call=call,
        executor=executor,
    )

    assert final.status is RuntimeStatus.FAILED
    assert final.tool_attempts == final.tool_call_budget == 3
    assert len(final.errors) == 3
    assert final.errors[-1].code == "tool-retry-exhausted"
    assert final.errors[-1].retryable is False
    assert executor.execution_count == 3


def test_checkpoint_contains_safe_tool_state_not_runtime_executor(
    tmp_path: Path,
) -> None:
    case = _case("transient-search-recovers")
    checkpoint = tmp_path / "checkpoint-safe.sqlite3"
    executor = _executor(case.tool_outcomes)
    call = ToolCall(
        call_id="safe-search",
        tool_name=ToolName.SEARCH_SOURCES,
        arguments=SearchSourcesArgs(
            query="checkpoint recovery",
            candidate_ids=case.input.candidates,
            source_types=("reliability",),
            top_k=2,
        ),
    )

    final = _run_approved(
        checkpoint=checkpoint,
        case=case,
        tool_call=call,
        executor=executor,
    )
    raw = checkpoint.read_bytes()

    assert final.last_tool_result is not None
    assert final.last_tool_result.safe_summary is None
    assert b"DeterministicFakeToolExecutor" not in raw
    assert b"private-vendor-response-body" not in raw

    config = workflow_config(f"thread-{case.case_id}")
    restored_executor = _executor(case.tool_outcomes)
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        restored_graph = build_tool_execution_graph(
            checkpointer=saver,
            tool_call=call,
            executor=restored_executor,
        )
        restored = _snapshot(restored_graph, config)

    assert restored == final
    assert restored_executor.execution_count == 0
