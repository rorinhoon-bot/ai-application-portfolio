"""Offline tests for the minimal requirements-confirmation LangGraph."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import ValidationError

from agent_research.models import HumanActionKind, ResearchInput
from agent_research.runtime_state import RuntimeState, RuntimeStatus
from agent_research.workflow import (
    HumanDecisionError,
    build_requirements_graph,
    create_initial_state,
    workflow_config,
)


def _request(
    *,
    candidates: list[str] | None = None,
    dimensions: list[dict[str, object]] | None = None,
) -> ResearchInput:
    return ResearchInput.model_validate(
        {
            "research_question": "比较工作流方案。",
            "audience": "开发团队",
            "constraints": ["结论必须有证据"],
            "candidates": (
                ["atlasflow", "beaconflow"]
                if candidates is None
                else candidates
            ),
            "dimensions": (
                [{"dimension_id": "reliability", "weight_percent": 100}]
                if dimensions is None
                else dimensions
            ),
            "source_policy_id": "synthetic-v1",
        }
    )


def _start(
    graph: object,
    *,
    run_id: str,
    thread_id: str,
    request: ResearchInput,
) -> tuple[dict[str, object], dict[str, dict[str, str]]]:
    config = workflow_config(thread_id)
    initial = create_initial_state(
        run_id=run_id,
        thread_id=thread_id,
        request=request,
    )
    result = graph.invoke(initial, config)  # type: ignore[attr-defined]
    return result, config


def _state(graph: object, config: dict[str, object]) -> RuntimeState:
    snapshot = graph.get_state(config)  # type: ignore[attr-defined]
    return RuntimeState.model_validate(snapshot.values)


def _decision(
    state: RuntimeState,
    action: HumanActionKind,
    *,
    edited_request: ResearchInput | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "requirements-decision-v1",
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "expected_revision": state.human_confirmation_revision,
        "expected_request_hash": state.confirmation_request_hash,
        "action": action.value,
    }
    if edited_request is not None:
        payload["edited_request"] = edited_request.model_dump(mode="json")
    return payload


def test_complete_request_pauses_for_human_confirmation(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "complete.sqlite3"
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_requirements_graph(saver)
        result, config = _start(
            graph,
            run_id="run-complete",
            thread_id="thread-complete",
            request=_request(),
        )
        state = _state(graph, config)

        assert "__interrupt__" in result
        assert state.status is RuntimeStatus.NEEDS_HUMAN
        assert state.current_node == "await_human_requirements"
        assert state.human_confirmation_revision == 1
        assert state.missing_requirements == ()


@pytest.mark.parametrize(
    ("research_input", "missing"),
    [
        (_request(candidates=[]), ("candidates",)),
        (_request(dimensions=[]), ("dimensions",)),
    ],
)
def test_incomplete_request_pauses_without_guessing(
    tmp_path: Path,
    research_input: ResearchInput,
    missing: tuple[str, ...],
) -> None:
    checkpoint = tmp_path / f"{missing[0]}.sqlite3"
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_requirements_graph(saver)
        _, config = _start(
            graph,
            run_id=f"run-missing-{missing[0]}",
            thread_id=f"thread-missing-{missing[0]}",
            request=research_input,
        )
        state = _state(graph, config)

        assert state.status is RuntimeStatus.NEEDS_HUMAN
        assert tuple(item.value for item in state.missing_requirements) == missing
        assert state.confirmed_requirements is None
        assert state.raw_request.candidates == research_input.candidates
        assert state.raw_request.dimensions == research_input.dimensions
        assert state.tool_attempts == 0


def test_approval_stops_at_deterministic_planning_placeholder(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "approve.sqlite3"
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_requirements_graph(saver)
        _, config = _start(
            graph,
            run_id="run-approve",
            thread_id="thread-approve",
            request=_request(),
        )
        waiting = _state(graph, config)

        graph.invoke(
            Command(
                resume=_decision(waiting, HumanActionKind.APPROVE)
            ),
            config,
        )
        planned = _state(graph, config)

        assert planned.status is RuntimeStatus.PLANNED
        assert planned.confirmed_requirements == planned.raw_request
        assert planned.plan_id is not None
        assert planned.tool_attempts == 0
        assert planned.retrieval_rounds == 0
        assert planned.evidence_ids == ()
        assert planned.report_hash is None
        assert graph.get_state(config).next == ()


def test_edit_increments_revision_and_invalidates_old_approval(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "edit.sqlite3"
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_requirements_graph(saver)
        _, config = _start(
            graph,
            run_id="run-edit",
            thread_id="thread-edit",
            request=_request(),
        )
        revision_one = _state(graph, config)
        old_approval = _decision(
            revision_one,
            HumanActionKind.APPROVE,
        )
        edited = _request(candidates=["atlasflow"])

        second_pause = graph.invoke(
            Command(
                resume=_decision(
                    revision_one,
                    HumanActionKind.EDIT,
                    edited_request=edited,
                )
            ),
            config,
        )
        revision_two = _state(graph, config)

        assert "__interrupt__" in second_pause
        assert revision_two.status is RuntimeStatus.NEEDS_HUMAN
        assert revision_two.human_confirmation_revision == 2
        assert revision_two.raw_request == edited
        assert (
            revision_two.confirmation_request_hash
            != revision_one.confirmation_request_hash
        )

        with pytest.raises(
            HumanDecisionError,
            match="HUMAN_DECISION_STALE_REVISION",
        ):
            graph.invoke(Command(resume=old_approval), config)

        still_waiting = _state(graph, config)
        assert still_waiting.status is RuntimeStatus.NEEDS_HUMAN
        assert still_waiting.human_confirmation_revision == 2


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (HumanActionKind.REJECT, RuntimeStatus.REJECTED),
        (HumanActionKind.CANCEL, RuntimeStatus.CANCELLED),
    ],
)
def test_reject_or_cancel_reaches_stable_terminal_state(
    tmp_path: Path,
    action: HumanActionKind,
    expected: RuntimeStatus,
) -> None:
    checkpoint = tmp_path / f"{action.value}.sqlite3"
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_requirements_graph(saver)
        _, config = _start(
            graph,
            run_id=f"run-{action.value}",
            thread_id=f"thread-{action.value}",
            request=_request(),
        )
        waiting = _state(graph, config)

        graph.invoke(
            Command(resume=_decision(waiting, action)),
            config,
        )
        terminal = _state(graph, config)

        assert terminal.status is expected
        assert terminal.current_node == "end"
        assert graph.get_state(config).next == ()


def test_same_run_and_thread_resume_after_sqlite_reopen(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "reopen.sqlite3"
    config = workflow_config("thread-reopen")

    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_requirements_graph(saver)
        graph.invoke(
            create_initial_state(
                run_id="run-reopen",
                thread_id="thread-reopen",
                request=_request(),
            ),
            config,
        )
        waiting = _state(graph, config)

    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        restored_graph = build_requirements_graph(saver)
        restored = _state(restored_graph, config)
        assert restored == waiting

        restored_graph.invoke(
            Command(
                resume=_decision(restored, HumanActionKind.APPROVE)
            ),
            config,
        )
        planned = _state(restored_graph, config)

        assert planned.run_id == "run-reopen"
        assert planned.thread_id == "thread-reopen"
        assert planned.status is RuntimeStatus.PLANNED


def test_checkpoint_excludes_secrets_headers_and_vendor_response(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "safe.sqlite3"
    forbidden_values = (
        b"sk-test-checkpoint-secret",
        b"Bearer vendor-auth-token",
        b"private-vendor-response-body",
    )

    unsafe = create_initial_state(
        run_id="run-safe",
        thread_id="thread-safe",
        request=_request(),
    )
    unsafe.update(
        {
            "api_key": forbidden_values[0].decode(),
            "authorization_header": forbidden_values[1].decode(),
            "vendor_response": forbidden_values[2].decode(),
        }
    )
    with pytest.raises(ValidationError, match="Extra inputs"):
        RuntimeState.model_validate(unsafe)

    secret_request = _request().model_copy(
        update={"constraints": ("Authorization: Bearer vendor-auth-token",)}
    )
    with pytest.raises(ValidationError, match="secret-shaped"):
        create_initial_state(
            run_id="run-unsafe-request",
            thread_id="thread-unsafe-request",
            request=secret_request,
        )

    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_requirements_graph(saver)
        _start(
            graph,
            run_id="run-safe",
            thread_id="thread-safe",
            request=_request(),
        )

    raw_checkpoint = checkpoint.read_bytes()
    assert all(value not in raw_checkpoint for value in forbidden_values)
