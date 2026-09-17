"""Frozen content-input runner must stay usable without a live model."""

from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "run_v2_content_evaluation.py"
SNAPSHOT = PROJECT_ROOT / "tests" / "fixtures" / "official-snapshot"


def test_smaller_frozen_input_batch_preserves_denominator(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("small_evaluation_runner", SCRIPT)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    original = json.loads((PROJECT_ROOT / "evals/v2/content-inputs-v1.json").read_text())
    original["cases"] = original["cases"][:2]
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(original))
    monkeypatch.setattr(runner, "_run_command", lambda command: {"status": "COMPLETED"})
    runner.main(["--inputs", str(inputs), "--runtime-root", str(tmp_path / "run"),
                 "--sources-root", str(SNAPSHOT), "--manifest", str(SNAPSHOT / "manifest.json")])
    result = json.loads((tmp_path / "run/evaluation-manifest.json").read_text())
    assert result["cases_attempted"] == result["cases_completed"] == 2
    assert result["semantic_quality"] == "N/A_REQUIRES_HUMAN_REVIEW"


@pytest.mark.parametrize("findings", [["REPORT_SCOPE_CLAIM_INVALID"], ["Unsupported claim"], None])
def test_batch_does_not_approve_unresolved_report_or_start_next_case(tmp_path, monkeypatch, findings):
    spec = importlib.util.spec_from_file_location("evaluation_runner_test", SCRIPT)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    commands = []

    def run_command(command):
        commands.append(command)
        if len(commands) == 1:
            return {"status": "NEEDS_HUMAN"}
        assert len(commands) == 2, "Unresolved report was approved or next case started"
        state = {"status": "REPORT_NEEDS_HUMAN"}
        if findings is not None:
            state["review_findings"] = findings
        return state

    monkeypatch.setattr(runner, "_run_command", run_command)
    assert runner.main([
        "--runtime-root", str(tmp_path), "--sources-root", str(SNAPSHOT),
        "--manifest", str(SNAPSHOT / "manifest.json"),
        "--case-ids", "dev-baseline,dev-recovery-scope",
    ]) == 0
    result = json.loads((tmp_path / "evaluation-manifest.json").read_text(encoding="utf-8"))
    assert len(commands) == 2
    assert result["cases_attempted"] == 1
    assert result["cases_completed"] == 0
    assert result["results"][0]["status"] == "REPORT_NEEDS_HUMAN"
    assert result["results"][0]["review_findings"] == (findings or [])


@pytest.mark.parametrize(
    ("start_index", "expected_case"),
    [(1, "dev-baseline"), (2, "dev-approval-boundary")],
)
def test_offline_content_evaluation_runs_one_frozen_input(
    tmp_path: Path, start_index: int, expected_case: str,
) -> None:
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("DEEPSEEK_", "LANGSMITH_", "LANGCHAIN_"))
    }
    environment["LANGGRAPH_STRICT_MSGPACK"] = "true"
    completed = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--runtime-root", str(tmp_path / "runtime"),
            "--sources-root", str(SNAPSHOT), "--manifest", str(SNAPSHOT / "manifest.json"),
            "--env-file", str(tmp_path / "absent.env"), "--limit", "1",
            "--start-index", str(start_index),
        ],
        cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    result = json.loads(completed.stdout)
    assert result["cases_attempted"] == 1
    assert result["cases_completed"] == 1
    assert result["semantic_quality"] == "N/A_REQUIRES_HUMAN_REVIEW"
    assert result["results"][0]["case_id"] == expected_case
    assert result["results"][0]["citation_identity_valid"] is True


def test_offline_content_evaluation_selects_noncontiguous_cases_in_frozen_order(tmp_path: Path) -> None:
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("DEEPSEEK_", "LANGSMITH_", "LANGCHAIN_"))
    }
    environment["LANGGRAPH_STRICT_MSGPACK"] = "true"
    completed = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--runtime-root", str(tmp_path / "runtime"),
            "--sources-root", str(SNAPSHOT), "--manifest", str(SNAPSHOT / "manifest.json"),
            "--env-file", str(tmp_path / "absent.env"), "--case-ids",
            "holdout-limited-brief,dev-baseline",
        ],
        cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    result = json.loads(completed.stdout)
    assert result["cases_attempted"] == 2
    assert result["cases_completed"] == 2
    assert [item["case_id"] for item in result["results"]] == [
        "dev-baseline", "holdout-limited-brief",
    ]
