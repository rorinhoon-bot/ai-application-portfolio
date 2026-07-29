"""Offline tests for the unified workflow-v1 evaluation runner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_research import evaluation_runner
from agent_research.data_loader import EvaluationBundle, load_evaluation_bundle
from agent_research.evaluation_runner import (
    EvaluationRunnerError,
    WorkflowBaseline,
    WorkflowCaseResult,
    run_workflow_evaluation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = PROJECT_ROOT / "evals" / "results" / "workflow-v1-baseline.json"


@pytest.fixture(scope="module")
def actual_baseline() -> WorkflowBaseline:
    return run_workflow_evaluation(PROJECT_ROOT)


def test_runner_requires_strict_msgpack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGGRAPH_STRICT_MSGPACK", raising=False)
    with pytest.raises(
        EvaluationRunnerError,
        match="LANGGRAPH_STRICT_MSGPACK",
    ):
        run_workflow_evaluation(PROJECT_ROOT)


def test_all_frozen_cases_match_actual_workflow(
    actual_baseline: WorkflowBaseline,
) -> None:
    assert actual_baseline.case_count == 12
    assert actual_baseline.passed_case_count == 12
    assert all(item.passed for item in actual_baseline.cases)
    assert actual_baseline.metrics.case_pass_rate.score_bps == 10_000
    assert actual_baseline.metrics.fixed_path_accuracy.score_bps == 10_000
    assert actual_baseline.metrics.retry_and_stop_accuracy.score_bps == 10_000


def test_changed_expectation_does_not_drive_actual_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = load_evaluation_bundle(PROJECT_ROOT)
    original = bundle.evaluation.cases[0]
    changed_expected = original.expected.model_copy(
        update={"required_path": ("wrong-node",)}
    )
    changed_case = original.model_copy(update={"expected": changed_expected})
    changed_bundle = EvaluationBundle(
        sources=bundle.sources,
        evaluation=bundle.evaluation.model_copy(
            update={
                "cases": (
                    changed_case,
                    *bundle.evaluation.cases[1:],
                )
            }
        ),
        gold=bundle.gold,
    )
    monkeypatch.setattr(
        evaluation_runner,
        "load_evaluation_bundle",
        lambda _: changed_bundle,
    )

    result = evaluation_runner.run_workflow_evaluation(PROJECT_ROOT)
    changed = result.cases[0]

    assert changed.actual_path != changed.expected_path
    assert changed.actual_path[0] == "validate-request"
    assert changed.checks.path_matches is False
    assert changed.passed is False
    assert result.passed_case_count == 11


def test_safety_citation_and_recovery_metrics_are_measured(
    actual_baseline: WorkflowBaseline,
) -> None:
    metrics = actual_baseline.metrics
    assert metrics.citation_binding_validity.score_bps == 10_000
    assert metrics.unsupported_claim_rate.score_bps == 0
    assert metrics.unapproved_export_count == 0
    assert metrics.permission_expansion_count == 0
    assert metrics.max_artifacts_per_case == 1
    assert metrics.checkpoint_recovery_consistency.score_bps == 10_000

    recovery = next(
        item
        for item in actual_baseline.cases
        if item.case_id == "checkpoint-resume-export"
    )
    assert recovery.checkpoint_recovery_consistent is True
    assert recovery.actual_path.count("export-report") == 2
    assert recovery.artifact_count == 1


def test_committed_baseline_matches_fresh_run(
    actual_baseline: WorkflowBaseline,
) -> None:
    committed = WorkflowBaseline.model_validate_json(
        BASELINE_PATH.read_text(encoding="utf-8")
    )
    assert committed == actual_baseline
    assert committed.to_json() == BASELINE_PATH.read_text(encoding="utf-8")


def test_result_contract_rejects_unknown_fields_and_false_pass_flag(
    actual_baseline: WorkflowBaseline,
) -> None:
    payload = actual_baseline.cases[0].model_dump(mode="json")
    payload["unknown"] = "rejected"
    with pytest.raises(ValidationError, match="Extra inputs"):
        WorkflowCaseResult.model_validate(payload)

    payload.pop("unknown")
    payload["passed"] = not payload["passed"]
    with pytest.raises(ValidationError, match="passed must equal"):
        WorkflowCaseResult.model_validate(payload)

    observable_failure = actual_baseline.cases[0].model_dump(mode="json")
    observable_failure["artifact_count"] = 2
    observable_failure["checks"]["artifact_count_matches"] = False
    observable_failure["passed"] = False
    recorded = WorkflowCaseResult.model_validate(observable_failure)
    assert recorded.artifact_count == 2
    assert recorded.passed is False


def test_baseline_json_is_stable_and_contains_no_runtime_paths_or_secrets(
    actual_baseline: WorkflowBaseline,
) -> None:
    first = actual_baseline.to_json()
    second = run_workflow_evaluation(PROJECT_ROOT).to_json()
    assert first == second
    lowered = first.lower()
    for forbidden in (
        "api_key=",
        "authorization:",
        "cookie:",
        "bearer ",
        "sqlite3",
        "p2-workflow-eval-",
        str(PROJECT_ROOT).lower(),
    ):
        assert forbidden not in lowered
    assert json.loads(first)["network_used"] is False
