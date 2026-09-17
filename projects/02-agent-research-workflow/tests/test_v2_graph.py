"""V2 end-to-end offline graph tests."""

from __future__ import annotations

import sqlite3
import pytest
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent_research.v2.contracts import (
    BudgetAuthorization,
    DecisionStatus,
    CandidateSpec,
    DimensionSpec,
    HumanAction,
    ResearchRequestV2,
    RunStatus,
    Usage,
    ModelResult,
    ModelToolCall,
)
from agent_research.v2.exporter import V2Exporter
from agent_research.v2.graph import build_v2_graph, create_initial_state, graph_config
from agent_research.v2.ledger import OperationLedger
from agent_research.v2.model_client import ScriptedModelClient
from agent_research.v2.model_client import ModelClientError, ModelResponseContractError
from agent_research.v2.source_store import SourceStore, load_snapshot

from test_v2_source_store import _fixture


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_SNAPSHOT = PROJECT_ROOT / "tests" / "fixtures" / "official-snapshot"


def _request() -> ResearchRequestV2:
    return ResearchRequestV2(
        research_question="Choose a workflow framework for a small AI team.",
        audience="student engineering team",
        candidates=(
            CandidateSpec(candidate_id="langgraph", name="LangGraph"),
            CandidateSpec(candidate_id="pydantic-ai", name="PydanticAI"),
        ),
        dimensions=(
            DimensionSpec(dimension_id="tool-calling", question="Tools", weight_percent=34),
            DimensionSpec(dimension_id="human-approval", question="Approval", weight_percent=33),
            DimensionSpec(dimension_id="recovery", question="Recovery", weight_percent=33),
        ),
        source_snapshot_id="snapshot-v2-dev",
        model_config_hash=ScriptedModelClient().config_hash,
        budget_authorization_id="budget-dev",
    )


def _graph(
    tmp_path: Path,
    *,
    approved: bool = True,
    model=None,
    source_store=None,
    budget: BudgetAuthorization | None = None,
    total_budget_ledger: OperationLedger | None = None,
    total_budget: BudgetAuthorization | None = None,
):
    source_root = tmp_path / "coverage-sources"
    source_root.mkdir(parents=True)
    snapshot, texts = _fixture(source_root)
    budget = budget or BudgetAuthorization(
        authorization_id="budget-dev",
        max_cost_minor_units=0,
        max_model_calls=12,
        max_input_tokens=48_000,
        max_output_tokens=12_000,
        expires_at="2099-01-01T00:00:00Z",
        approved=approved,
    )
    ledger = OperationLedger(tmp_path / "runtime" / "operations.sqlite3")
    connection = sqlite3.connect(tmp_path / "runtime" / "checkpoints.sqlite3", check_same_thread=False)
    saver = SqliteSaver(connection)
    saver.setup()
    graph = build_v2_graph(
        checkpointer=saver,
        model=model or ScriptedModelClient(),
        source_store=source_store or SourceStore(snapshot, texts),
        ledger=ledger,
        budget=budget,
        exporter=V2Exporter(tmp_path / "runtime" / "artifacts"),
        total_budget_ledger=total_budget_ledger,
        total_budget=total_budget,
    )
    return graph, saver, ledger, connection


def _state(graph, config):
    return graph.get_state(config).values


def test_shared_total_budget_stops_before_third_model_send(tmp_path: Path) -> None:
    class ReservedScriptedModel(ScriptedModelClient):
        def reservation_bounds(self, *, task: str, payload: dict[str, object]) -> tuple[int, int]:
            return 1, 1

        def estimate_cost_minor_units(self, *, input_tokens: int, output_tokens: int) -> int:
            return 1

    batch_budget = BudgetAuthorization(
        authorization_id="budget-dev", max_cost_minor_units=10, max_model_calls=12,
        max_input_tokens=100, max_output_tokens=100, expires_at="2099-01-01T00:00:00Z", approved=True,
    )
    total_budget = BudgetAuthorization(
        authorization_id="budget-p2-total", max_cost_minor_units=10, max_model_calls=2,
        max_input_tokens=100, max_output_tokens=100, expires_at="2099-01-01T00:00:00Z", approved=True,
    )
    total_ledger = OperationLedger(tmp_path / "p2-total" / "operations.sqlite3")
    graph, saver, ledger, connection = _graph(
        tmp_path, model=ReservedScriptedModel(), budget=batch_budget,
        total_budget_ledger=total_ledger, total_budget=total_budget,
    )
    config = graph_config("thread-total-budget")
    try:
        graph.invoke(
            create_initial_state(run_id="run-total-budget", thread_id="thread-total-budget", request=_request()),
            config,
        )
        waiting = _state(graph, config)
        graph.invoke(
            Command(
                resume={
                    "run_id": "run-total-budget", "thread_id": "thread-total-budget",
                    "expected_request_hash": waiting["request_hash"], "action": HumanAction.APPROVE.value,
                }
            ),
            config,
        )
        state = _state(graph, config)
        assert state["status"] == RunStatus.FAILED.value
        assert state["errors"] == ["BUDGET_RESERVATION_EXHAUSTED"]
        assert len(total_ledger._connection.execute("SELECT * FROM budget_reservations").fetchall()) == 2
        assert len(ledger.records_for_run("run-total-budget")) == 3
    finally:
        total_ledger.close()
        ledger.close()
        connection.close()


def test_full_v2_offline_flow_has_two_human_gates_and_one_artifact(tmp_path: Path) -> None:
    graph, saver, ledger, connection = _graph(tmp_path)
    config = graph_config("thread-v2")
    try:
        graph.invoke(
            create_initial_state(run_id="run-v2", thread_id="thread-v2", request=_request()),
            config,
        )
        waiting = _state(graph, config)
        assert waiting["status"] == RunStatus.NEEDS_HUMAN.value
        assert waiting["current_node"] == "requirements-gate"
        graph.invoke(
            Command(
                resume={
                    "run_id": "run-v2",
                    "thread_id": "thread-v2",
                    "expected_request_hash": waiting["request_hash"],
                    "action": HumanAction.APPROVE.value,
                }
            ),
            config,
        )
        report_wait = _state(graph, config)
        assert report_wait["status"] == RunStatus.REPORT_NEEDS_HUMAN.value
        assert report_wait["report"] is not None
        assert len(report_wait["evidence_cells"]) == 6
        graph.invoke(
            Command(
                resume={
                    "run_id": "run-v2",
                    "thread_id": "thread-v2",
                    "report_revision": report_wait["report_revision"],
                    "report_hash": report_wait["report_hash"],
                    "action": HumanAction.APPROVE.value,
                }
            ),
            config,
        )
        final = _state(graph, config)
        assert final["status"] == RunStatus.COMPLETED.value
        assert final["artifact_id"]
        assert len(tuple((tmp_path / "runtime" / "artifacts").glob("*.md"))) == 1
        records = ledger.records_for_run("run-v2")
        assert len(records) == 3
        assert all(item.status.value == "succeeded" for item in records)
    finally:
        ledger.close()
        connection.close()


def test_search_covers_every_requested_candidate_and_dimension(tmp_path: Path) -> None:
    class RecordingStore(SourceStore):
        calls: list[tuple[frozenset[str] | None, str]] = []

        def search(self, *, query, request, top_k=6, candidate_ids=None):
            self.calls.append((candidate_ids, query))
            return super().search(
                query=query,
                request=request,
                top_k=top_k,
                candidate_ids=candidate_ids,
            )

    source_root = tmp_path / "sources"
    source_root.mkdir(parents=True)
    snapshot, texts = _fixture(source_root)
    store = RecordingStore(snapshot, texts)
    graph, saver, ledger, connection = _graph(tmp_path, source_store=store)
    config = graph_config("thread-coverage")
    try:
        graph.invoke(
            create_initial_state(run_id="run-coverage", thread_id="thread-coverage", request=_request()),
            config,
        )
        waiting = _state(graph, config)
        graph.invoke(Command(resume={
            "run_id": "run-coverage", "thread_id": "thread-coverage",
            "expected_request_hash": waiting["request_hash"], "action": HumanAction.APPROVE.value,
        }), config)
        assert {candidate for candidate, _ in store.calls} == {
            frozenset({"langgraph"}), frozenset({"pydantic-ai"}),
        }
        assert len(store.calls) == len(_request().candidates) * (len(_request().dimensions) + 1)
        assert all("Recovery" in query or "Approval" in query or "Tools" in query for _, query in store.calls[:6])
        assert [query for _, query in store.calls[6:]] == [_request().research_question] * 2
        evidence_ids = [item["evidence_id"] for item in _state(graph, config)["evidence"]]
        assert len(evidence_ids) == len(set(evidence_ids))
    finally:
        ledger.close()
        connection.close()


def test_real_snapshot_coverage_reaches_draft_model(tmp_path: Path) -> None:
    class CapturingModel(ScriptedModelClient):
        draft_evidence_ids: tuple[str, ...] = ()

        def generate(self, *, task: str, payload: dict[str, object]):
            if task == "draft":
                self.draft_evidence_ids = tuple(
                    str(item["evidence_id"])
                    for item in payload["evidence"]
                    if isinstance(item, dict)
                )
            return super().generate(task=task, payload=payload)

    snapshot, texts = load_snapshot(REAL_SNAPSHOT, REAL_SNAPSHOT / "manifest.json")
    model = CapturingModel()
    graph, saver, ledger, connection = _graph(
        tmp_path,
        model=model,
        source_store=SourceStore(snapshot, texts),
    )
    request = _request().model_copy(update={"source_snapshot_id": snapshot.snapshot_id})
    config = graph_config("thread-real-coverage")
    try:
        graph.invoke(
            create_initial_state(
                run_id="run-real-coverage",
                thread_id="thread-real-coverage",
                request=request,
            ),
            config,
        )
        waiting = _state(graph, config)
        graph.invoke(Command(resume={
            "run_id": "run-real-coverage", "thread_id": "thread-real-coverage",
            "expected_request_hash": waiting["request_hash"], "action": HumanAction.APPROVE.value,
        }), config)
        assert "pa-03#durable-execution" in model.draft_evidence_ids
        assert _state(graph, config)["status"] == RunStatus.REPORT_NEEDS_HUMAN.value
    finally:
        ledger.close()
        connection.close()


@pytest.mark.parametrize("summary,blocked", [
    ("本快照未提供任何恢复能力证据。", True),
    ("未知不代表本快照未提供该能力证据。", False),
    ("冻结快照中未找到 PydanticAI 的恢复证据。", True),
    ("unknown 不代表整个冻结快照缺少该能力。", False),
    ("本次提供的冻结证据中，没有可直接支持该结论的段落。", False),
    ("本次提供的整个冻结快照没有任何证据。", True),
    ("This does not mean that the whole frozen snapshot lacks evidence.", False),
    ("不代表整个冻结快照缺少能力。冻结快照中未找到恢复证据。", True),
])
def test_overbroad_frozen_snapshot_absence_claim_pauses_before_model_review(tmp_path: Path, summary, blocked) -> None:
    class OverbroadDraftModel(ScriptedModelClient):
        def generate(self, *, task: str, payload: dict[str, object]):
            result = super().generate(task=task, payload=payload)
            if task == "draft":
                return result.model_copy(update={
                    "executive_summary": summary,
                })
            return result

    graph, saver, ledger, connection = _graph(tmp_path, model=OverbroadDraftModel())
    config = graph_config("thread-scope-claim")
    try:
        graph.invoke(
            create_initial_state(
                run_id="run-scope-claim",
                thread_id="thread-scope-claim",
                request=_request(),
            ),
            config,
        )
        waiting = _state(graph, config)
        graph.invoke(Command(resume={
            "run_id": "run-scope-claim", "thread_id": "thread-scope-claim",
            "expected_request_hash": waiting["request_hash"], "action": HumanAction.APPROVE.value,
        }), config)
        report_wait = _state(graph, config)
        assert report_wait["status"] == RunStatus.REPORT_NEEDS_HUMAN.value
        assert report_wait["review_findings"] == (["REPORT_SCOPE_CLAIM_INVALID"] if blocked else [])
        assert len(ledger.records_for_run("run-scope-claim")) == (2 if blocked else 3)
    finally:
        ledger.close()
        connection.close()


def test_review_findings_pause_for_human_revision_then_clear(tmp_path: Path) -> None:
    class FindingThenClearModel(ScriptedModelClient):
        review_count = 0

        def generate(self, *, task: str, payload: dict[str, object]):
            if task == "draft" and self.review_count == 1:
                assert payload["previous_review_findings"] == [
                    "citation excerpt does not support claim", "Check the missing configuration prerequisite.",
                ]
            result = super().generate(task=task, payload=payload)
            if task == "review":
                self.review_count += 1
                return result.model_copy(update={
                    "review_findings": ("citation excerpt does not support claim",)
                    if self.review_count == 1 else (),
                })
            return result

    graph, saver, ledger, connection = _graph(tmp_path, model=FindingThenClearModel())
    config = graph_config("thread-review-findings")
    try:
        graph.invoke(create_initial_state(
            run_id="run-review-findings", thread_id="thread-review-findings", request=_request(),
        ), config)
        requirements = _state(graph, config)
        graph.invoke(Command(resume={
            "run_id": "run-review-findings", "thread_id": "thread-review-findings",
            "expected_request_hash": requirements["request_hash"], "action": HumanAction.APPROVE.value,
        }), config)
        first = _state(graph, config)
        assert first["status"] == RunStatus.REPORT_NEEDS_HUMAN.value
        assert first["review_findings"] == ["citation excerpt does not support claim"]
        graph.invoke(Command(resume={
            "run_id": "run-review-findings", "thread_id": "thread-review-findings",
            "report_revision": first["report_revision"], "report_hash": first["report_hash"],
            "action": HumanAction.REQUEST_CHANGES.value,
            "feedback": "Check the missing configuration prerequisite.",
        }), config)
        second = _state(graph, config)
        assert second["status"] == RunStatus.REPORT_NEEDS_HUMAN.value
        assert second["review_findings"] == []
        assert second["report_revision"] == 2
        assert len(ledger.records_for_run("run-review-findings")) == 5
    finally:
        ledger.close()
        connection.close()


@pytest.mark.parametrize("defect", ["summary", "caveat", "decision", "hash"])
def test_report_approval_cannot_bypass_deterministic_errors(tmp_path: Path, defect: str) -> None:
    class DefectiveModel(ScriptedModelClient):
        def generate(self, *, task, payload):
            result = super().generate(task=task, payload=payload)
            if task == "draft":
                if defect == "summary":
                    return result.model_copy(update={"executive_summary": "整个冻结快照没有任何恢复能力证据。"})
                if defect == "caveat":
                    cells = list(result.evidence_cells)
                    cells[0] = cells[0].model_copy(update={"caveat": "整个冻结快照没有任何恢复能力证据。"})
                    return result.model_copy(update={"evidence_cells": tuple(cells)})
                if defect == "decision":
                    return result.model_copy(update={"recommendation": None, "decision_status": DecisionStatus.CONDITIONAL})
            return result

    graph, _, ledger, connection = _graph(tmp_path, model=DefectiveModel())
    config = graph_config("thread-blocked-approval")
    try:
        graph.invoke(create_initial_state(run_id="run-blocked-approval", thread_id="thread-blocked-approval", request=_request()), config)
        first = _state(graph, config)
        graph.invoke(Command(resume={"run_id": first["run_id"], "thread_id": first["thread_id"],
            "expected_request_hash": first["request_hash"], "action": "approve"}), config)
        waiting = _state(graph, config)
        if defect == "hash":
            graph.update_state(config, {"report_hash": "a" * 64})
            waiting = _state(graph, config)
        count = len(ledger.records_for_run(first["run_id"]))
        graph.invoke(Command(resume={"run_id": first["run_id"], "thread_id": first["thread_id"],
            "report_hash": waiting["report_hash"], "report_revision": waiting["report_revision"],
            "action": "approve"}), config)
        final = _state(graph, config)
        assert final["status"] == "FAILED"
        assert final["errors"][-1] == ("REPORT_CONTENT_HASH_MISMATCH" if defect == "hash" else "REPORT_APPROVAL_BLOCKED")
        assert final["artifact_id"] is None
        assert not list((tmp_path / "runtime" / "artifacts").glob("*.md"))
        assert len(ledger.records_for_run(first["run_id"])) == count
    finally:
        ledger.close()
        connection.close()


@pytest.mark.parametrize("field,value", [("approved_report_hash", "b" * 64), ("approved_report_revision", 0)])
def test_export_rechecks_approval_even_when_gate_is_not_reexecuted(tmp_path: Path, field, value) -> None:
    from types import SimpleNamespace
    from agent_research.v2.graph import _export_report

    graph, _, ledger, connection = _graph(tmp_path)
    config = graph_config("thread-export-binding")
    try:
        graph.invoke(create_initial_state(run_id="run-export-binding", thread_id="thread-export-binding", request=_request()), config)
        state = _state(graph, config)
        graph.invoke(Command(resume={"run_id": state["run_id"], "thread_id": state["thread_id"],
            "expected_request_hash": state["request_hash"], "action": "approve"}), config)
        waiting = dict(_state(graph, config))
        waiting.update(approved_report_hash=waiting["report_hash"],
                       approved_report_revision=waiting["report_revision"])
        waiting[field] = value
        result = _export_report(waiting, deps=SimpleNamespace(exporter=V2Exporter(tmp_path / "runtime" / "artifacts")))
        assert result["errors"][-1] == "EXPORT_APPROVAL_BINDING_MISMATCH"
        assert result["artifact_id"] is None
        assert not list((tmp_path / "runtime" / "artifacts").glob("*.md"))
    finally:
        ledger.close()
        connection.close()


def test_unapproved_budget_stops_before_model_call(tmp_path: Path) -> None:
    graph, saver, ledger, connection = _graph(tmp_path, approved=False)
    config = graph_config("thread-unknown")
    try:
        graph.invoke(
            create_initial_state(run_id="run-unknown", thread_id="thread-unknown", request=_request()),
            config,
        )
        waiting = _state(graph, config)
        graph.invoke(
            Command(
                resume={
                    "run_id": "run-unknown",
                    "thread_id": "thread-unknown",
                    "expected_request_hash": waiting["request_hash"],
                    "action": HumanAction.APPROVE.value,
                }
            ),
            config,
        )
        assert _state(graph, config)["status"] == RunStatus.FAILED.value
        assert "BUDGET_AUTHORIZATION_REQUIRED" in _state(graph, config)["errors"]
    finally:
        ledger.close()
        connection.close()


def test_model_transport_unknown_pauses_without_follow_on_tool_execution(tmp_path: Path) -> None:
    class UnknownModel(ScriptedModelClient):
        def generate(self, *, task: str, payload: dict[str, object]):
            if task == "plan":
                raise ModelClientError("simulated transport failure")
            return super().generate(task=task, payload=payload)

    graph, saver, ledger, connection = _graph(tmp_path, model=UnknownModel())
    config = graph_config("thread-unknown-model")
    try:
        graph.invoke(
            create_initial_state(
                run_id="run-unknown-model",
                thread_id="thread-unknown-model",
                request=_request(),
            ),
            config,
        )
        waiting = _state(graph, config)
        graph.invoke(
            Command(
                resume={
                    "run_id": "run-unknown-model",
                    "thread_id": "thread-unknown-model",
                    "expected_request_hash": waiting["request_hash"],
                    "action": HumanAction.APPROVE.value,
                }
            ),
            config,
        )
        final = _state(graph, config)
        assert final["status"] == RunStatus.RECOVERY_REVIEW.value
        assert final["unknown_call_count"] == 1
        assert final["evidence"] == []
        records = ledger.records_for_run("run-unknown-model")
        assert len(records) == 1
        assert records[0].status.value == "unknown"
    finally:
        ledger.close()
        connection.close()


def test_model_adapter_error_is_redacted_in_state_and_kept_in_ledger(tmp_path: Path) -> None:
    class HttpErrorModel(ScriptedModelClient):
        def generate(self, *, task: str, payload: dict[str, object]):
            if task == "plan":
                raise ModelClientError("MODEL_HTTP_401")
            return super().generate(task=task, payload=payload)

    graph, saver, ledger, connection = _graph(tmp_path, model=HttpErrorModel())
    config = graph_config("thread-http-error")
    try:
        graph.invoke(
            create_initial_state(
                run_id="run-http-error",
                thread_id="thread-http-error",
                request=_request(),
            ),
            config,
        )
        waiting = _state(graph, config)
        graph.invoke(
            Command(
                resume={
                    "run_id": "run-http-error",
                    "thread_id": "thread-http-error",
                    "expected_request_hash": waiting["request_hash"],
                    "action": HumanAction.APPROVE.value,
                }
            ),
            config,
        )
        state = _state(graph, config)
        assert state["status"] == RunStatus.RECOVERY_REVIEW.value
        assert state["errors"] == ["MODEL_CALL_UNKNOWN_REQUIRES_REVIEW"]
        assert ledger.records_for_run("run-http-error")[0].error_code == "MODEL_HTTP_401"
    finally:
        ledger.close()
        connection.close()


def test_invalid_provider_content_keeps_known_usage_in_recovery_ledger(tmp_path: Path) -> None:
    class InvalidContentModel(ScriptedModelClient):
        def generate(self, *, task: str, payload: dict[str, object]):
            if task == "plan":
                raise ModelResponseContractError(
                    "MODEL_RESULT_CONTRACT_INVALID_tool-calls",
                    usage=Usage(
                        input_tokens=9,
                        output_tokens=4,
                        cost_minor_units=1,
                        cost_status="known",
                    ),
                )
            return super().generate(task=task, payload=payload)

    graph, saver, ledger, connection = _graph(tmp_path, model=InvalidContentModel())
    config = graph_config("thread-invalid-content")
    try:
        graph.invoke(
            create_initial_state(
                run_id="run-invalid-content",
                thread_id="thread-invalid-content",
                request=_request(),
            ),
            config,
        )
        waiting = _state(graph, config)
        graph.invoke(
            Command(
                resume={
                    "run_id": "run-invalid-content",
                    "thread_id": "thread-invalid-content",
                    "expected_request_hash": waiting["request_hash"],
                    "action": HumanAction.APPROVE.value,
                }
            ),
            config,
        )
        record = ledger.records_for_run("run-invalid-content")[0]
        assert record.status.value == "unknown"
        assert record.usage is not None
        assert record.usage.cost_minor_units == 1
    finally:
        ledger.close()
        connection.close()


def test_token_budget_stops_after_a_valid_but_over_budget_response(tmp_path: Path) -> None:
    class OverBudgetModel(ScriptedModelClient):
        def generate(self, *, task: str, payload: dict[str, object]):
            result = super().generate(task=task, payload=payload)
            return result.model_copy(
                update={
                    "usage": Usage(
                        input_tokens=48_001,
                        output_tokens=0,
                        cost_status="not-applicable",
                    )
                }
            )

    graph, saver, ledger, connection = _graph(tmp_path, model=OverBudgetModel())
    config = graph_config("thread-over-budget")
    try:
        graph.invoke(
            create_initial_state(
                run_id="run-over-budget",
                thread_id="thread-over-budget",
                request=_request(),
            ),
            config,
        )
        waiting = _state(graph, config)
        graph.invoke(
            Command(
                resume={
                    "run_id": "run-over-budget",
                    "thread_id": "thread-over-budget",
                    "expected_request_hash": waiting["request_hash"],
                    "action": HumanAction.APPROVE.value,
                }
            ),
            config,
        )
        final = _state(graph, config)
        assert final["status"] == RunStatus.FAILED.value
        assert "MODEL_INPUT_TOKEN_BUDGET_EXCEEDED" in final["errors"]
        records = ledger.records_for_run("run-over-budget")
        assert len(records) == 1
        assert records[0].status.value == "succeeded"
    finally:
        ledger.close()
        connection.close()


def test_known_cost_budget_stops_after_response_is_recorded(tmp_path: Path) -> None:
    class KnownCostModel(ScriptedModelClient):
        def generate(self, *, task: str, payload: dict[str, object]):
            result = super().generate(task=task, payload=payload)
            return result.model_copy(
                update={
                    "usage": Usage(
                        input_tokens=1,
                        output_tokens=1,
                        cost_minor_units=1,
                        cost_status="known",
                    )
                }
            )

    graph, saver, ledger, connection = _graph(tmp_path, model=KnownCostModel())
    config = graph_config("thread-cost-over-budget")
    try:
        graph.invoke(
            create_initial_state(
                run_id="run-cost-over-budget",
                thread_id="thread-cost-over-budget",
                request=_request(),
            ),
            config,
        )
        waiting = _state(graph, config)
        graph.invoke(
            Command(
                resume={
                    "run_id": "run-cost-over-budget",
                    "thread_id": "thread-cost-over-budget",
                    "expected_request_hash": waiting["request_hash"],
                    "action": HumanAction.APPROVE.value,
                }
            ),
            config,
        )
        final = _state(graph, config)
        assert final["status"] == RunStatus.FAILED.value
        assert "MODEL_COST_BUDGET_EXCEEDED" in final["errors"]
        records = ledger.records_for_run("run-cost-over-budget")
        assert len(records) == 1
        assert records[0].usage is not None
        assert records[0].usage.cost_minor_units == 1
    finally:
        ledger.close()
        connection.close()


def test_malformed_model_tool_arguments_stop_with_stable_error(tmp_path: Path) -> None:
    class MalformedToolModel(ScriptedModelClient):
        def generate(self, *, task: str, payload: dict[str, object]):
            if task == "plan":
                return ModelResult(
                    task="plan",
                    provider=self.provider,
                    model_id=self.model_id,
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id="bad-tool-call",
                            tool_name="search_sources",
                            arguments={"candidate_ids": None, "dimension_ids": [], "query": "x", "top_k": 1},
                        ),
                    ),
                )
            return super().generate(task=task, payload=payload)

    graph, saver, ledger, connection = _graph(tmp_path, model=MalformedToolModel())
    config = graph_config("thread-malformed-tool")
    try:
        graph.invoke(
            create_initial_state(
                run_id="run-malformed-tool",
                thread_id="thread-malformed-tool",
                request=_request(),
            ),
            config,
        )
        waiting = _state(graph, config)
        graph.invoke(
            Command(
                resume={
                    "run_id": "run-malformed-tool",
                    "thread_id": "thread-malformed-tool",
                    "expected_request_hash": waiting["request_hash"],
                    "action": HumanAction.APPROVE.value,
                }
            ),
            config,
        )
        final = _state(graph, config)
        assert final["status"] == RunStatus.FAILED.value
        assert "TOOL_ARGUMENTS_INVALID" in final["errors"]
    finally:
        ledger.close()
        connection.close()


def test_request_cannot_cross_snapshot_or_budget_authorization(tmp_path: Path) -> None:
    graph, saver, ledger, connection = _graph(tmp_path)
    config = graph_config("thread-mismatch")
    request = _request().model_copy(update={"source_snapshot_id": "other-snapshot"})
    try:
        graph.invoke(
            create_initial_state(
                run_id="run-mismatch",
                thread_id="thread-mismatch",
                request=request,
            ),
            config,
        )
        final = _state(graph, config)
        assert final["status"] == RunStatus.FAILED.value
        assert final["current_node"] == "end"
        assert final["errors"] == ["SOURCE_SNAPSHOT_MISMATCH"]
    finally:
        ledger.close()
        connection.close()


def test_request_cannot_cross_model_configuration(tmp_path: Path) -> None:
    graph, saver, ledger, connection = _graph(tmp_path)
    config = graph_config("thread-model-config-mismatch")
    request = _request().model_copy(update={"model_config_hash": "b" * 64})
    try:
        graph.invoke(
            create_initial_state(
                run_id="run-model-config-mismatch",
                thread_id="thread-model-config-mismatch",
                request=request,
            ),
            config,
        )
        final = _state(graph, config)
        assert final["status"] == RunStatus.FAILED.value
        assert final["errors"] == ["MODEL_CONFIGURATION_MISMATCH"]
    finally:
        ledger.close()
        connection.close()


@pytest.mark.parametrize(("decision", "choice"), [
    (DecisionStatus.CONDITIONAL, None),
    (DecisionStatus.RECOMMENDED, None),
    (DecisionStatus.INSUFFICIENT_EVIDENCE, "langgraph"),
])
def test_inconsistent_decision_pauses_without_review_or_export(tmp_path, decision, choice):
    class InconsistentModel(ScriptedModelClient):
        def generate(self, *, task, payload):
            result = super().generate(task=task, payload=payload)
            if task == "draft":
                return result.model_copy(update={"decision_status": decision, "recommendation": choice})
            assert task != "review", "Inconsistent decision reached paid model review"
            return result

    graph, saver, ledger, connection = _graph(tmp_path, model=InconsistentModel())
    config = graph_config("thread-inconsistent")
    try:
        graph.invoke(create_initial_state(
            run_id="run-inconsistent", thread_id="thread-inconsistent", request=_request(),
        ), config)
        waiting = _state(graph, config)
        graph.invoke(Command(resume={
            "run_id": "run-inconsistent", "thread_id": "thread-inconsistent",
            "expected_request_hash": waiting["request_hash"], "action": HumanAction.APPROVE.value,
        }), config)
        state = _state(graph, config)
        assert state["status"] == RunStatus.REPORT_NEEDS_HUMAN.value
        assert state["review_findings"] == ["REPORT_DECISION_INCONSISTENT"]
        assert len(ledger.records_for_run("run-inconsistent")) == 2
        assert state["artifact_id"] is None
    finally:
        ledger.close()
        connection.close()
