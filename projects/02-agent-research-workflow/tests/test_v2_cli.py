"""CLI smoke test for the offline, two-gate user path."""

from __future__ import annotations

import json
import importlib.util
from types import SimpleNamespace
import pytest
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "run_research_v2.py"


@pytest.mark.parametrize("command", ["resume", "recover"])
def test_live_resume_rejects_alternate_or_missing_total_ledger(tmp_path, monkeypatch, command):
    spec = importlib.util.spec_from_file_location("cli_budget_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    args = SimpleNamespace(mode="live", command=command,
                           total_budget_file=str(tmp_path / "another.json"),
                           total_budget_ledger=str(tmp_path / "another.sqlite3"))
    with pytest.raises(ValueError, match="LIVE_TOTAL_BUDGET_PATH_MISMATCH"):
        module._total_budget(args)
    root = tmp_path / ".runtime" / "p2-budget"
    args.total_budget_file = str(root / "authorization.json")
    args.total_budget_ledger = str(root / "total.sqlite3")
    with pytest.raises(ValueError, match="LIVE_TOTAL_BUDGET_INITIALIZATION_REQUIRED"):
        module._total_budget(args)


def _isolated_env() -> dict[str, str]:
    return {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("DEEPSEEK_", "LANGSMITH_", "LANGCHAIN_"))
    } | {"LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}


def _run(runtime: Path, *args: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--env-file", str(runtime / "absent.env"),
         "--runtime-root", str(runtime), *args],
        env=_isolated_env(),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def test_offline_cli_runs_two_gates_and_exports_once(tmp_path: Path) -> None:
    first = _run(tmp_path / "runtime", "start")
    assert first["status"] == "NEEDS_HUMAN"
    thread_id = str(first["thread_id"])
    polled = _run(tmp_path / "runtime", "status", "--thread-id", thread_id)
    assert polled["status"] == first["status"]

    second = _run(tmp_path / "runtime", "resume", "--thread-id", thread_id, "--action", "approve")
    assert second["status"] == "REPORT_NEEDS_HUMAN"

    final = _run(tmp_path / "runtime", "resume", "--thread-id", thread_id, "--action", "approve")
    assert final["status"] == "COMPLETED"
    assert final["artifact_id"]
    assert len(tuple((tmp_path / "runtime" / "artifacts").glob("*.md"))) == 1


def test_offline_cli_accepts_public_revision_feedback(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    first = _run(runtime, "start")
    thread = first["thread_id"]
    _run(runtime, "resume", "--thread-id", thread, "--action", "approve")
    revised = _run(runtime, "resume", "--thread-id", thread, "--action", "request-changes",
                   "--feedback", "核对配置前提，并区分事实与待验证建议。")
    assert revised["status"] == "REPORT_NEEDS_HUMAN"
    assert revised["report_revision"] == 2
    assert revised["artifact_id"] is None


@pytest.mark.parametrize("feedback,action,status", [
    ("x" * 901, "request-changes", "REPORT_NEEDS_HUMAN"),
    ("   ", "request-changes", "REPORT_NEEDS_HUMAN"),
    ("feedback", "approve", "REPORT_NEEDS_HUMAN"),
    ("feedback", "request-changes", "NEEDS_HUMAN"),
])
def test_cli_rejects_invalid_feedback_before_resume(feedback, action, status):
    spec = importlib.util.spec_from_file_location("cli_feedback_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="REPORT_FEEDBACK_INVALID"):
        module._decision({"status": status}, action=action, edit_request=None, feedback=feedback)


def test_model_config_command_never_needs_network_or_a_key(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--env-file", str(tmp_path / "absent.env"),
         "--mode", "live", "model-config"],
        env=_isolated_env(),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = json.loads(completed.stdout)
    assert output["provider"] == "deepseek"
    assert output["model_id"] == "deepseek-flash"
    assert len(output["model_config_hash"]) == 64
    assert output["network_accessed"] is False


def test_live_cli_loads_only_p2_env_file_without_printing_key(tmp_path: Path) -> None:
    env_file = tmp_path / "p2.env"
    env_file.write_text("DEEPSEEK_API_KEY=fixture-key\n", encoding="utf-8")
    budget_file = tmp_path / "budget.json"
    total_budget_file = tmp_path / "total-budget.json"
    total_budget_ledger = tmp_path / "total-budget.sqlite3"
    price_card_file = tmp_path / "price-card.json"
    budget_file.write_text(
        json.dumps(
            {
                "authorization_id": "budget-live",
                "max_cost_minor_units": 500,
                "max_model_calls": 3,
                "max_input_tokens": 1000,
                "max_output_tokens": 1000,
                "expires_at": "2099-01-01T00:00:00Z",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )
    price_card_file.write_text(
        json.dumps(
            {
                "price_page_url": "https://api.example.invalid/pricing",
                "price_page_checked_at": "2026-09-14T00:00:00Z",
                "fx_safety_ceiling_cny_per_usd": 10,
                "input_cache_hit_minor_per_million": 14,
                "input_cache_miss_minor_per_million": 440,
                "output_minor_per_million": 1320,
            }
        ),
        encoding="utf-8",
    )
    total_budget_file.write_text(
        json.dumps(
            {
                "authorization_id": "budget-p2-total",
                "max_cost_minor_units": 500,
                "max_model_calls": 100,
                "max_input_tokens": 1_000_000,
                "max_output_tokens": 100_000,
                "expires_at": "2099-01-01T00:00:00Z",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "live",
            "--env-file",
            str(env_file),
            "--budget-file",
            str(budget_file),
            "--price-card-file",
            str(price_card_file),
            "--total-budget-file",
            str(total_budget_file),
            "--total-budget-ledger",
            str(total_budget_ledger),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "start",
        ],
        env=_isolated_env(),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = json.loads(completed.stdout)
    assert output["errors"] == ["BUDGET_AUTHORIZATION_MISMATCH"]
    assert "fixture-key" not in completed.stdout
    assert "fixture-key" not in completed.stderr


def test_live_cli_requires_shared_p2_total_budget_before_any_network(tmp_path: Path) -> None:
    env_file = tmp_path / "p2.env"
    env_file.write_text("DEEPSEEK_API_KEY=fixture-key\n", encoding="utf-8")
    budget_file = tmp_path / "budget.json"
    budget_file.write_text(
        json.dumps(
            {
                "authorization_id": "budget-live",
                "max_cost_minor_units": 500,
                "max_model_calls": 3,
                "max_input_tokens": 1000,
                "max_output_tokens": 1000,
                "expires_at": "2099-01-01T00:00:00Z",
                "approved": True,
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable, str(SCRIPT), "--mode", "live", "--env-file", str(env_file),
            "--budget-file", str(budget_file), "start",
        ],
        env=_isolated_env(), cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert completed.returncode == 2
    assert "LIVE_TOTAL_BUDGET_FILE_REQUIRED" in completed.stderr
    assert "fixture-key" not in completed.stderr


def test_live_preflight_checks_a_p2_env_file_without_network(tmp_path: Path) -> None:
    env_file = tmp_path / "p2.env"
    env_file.write_text("DEEPSEEK_API_KEY=fixture-key\n", encoding="utf-8")
    price_card_file = tmp_path / "price-card.json"
    price_card_file.write_text(
        json.dumps(
            {
                "price_page_url": "https://api.example.invalid/pricing",
                "price_page_checked_at": "2026-09-14T00:00:00Z",
                "fx_safety_ceiling_cny_per_usd": 10,
                "input_cache_hit_minor_per_million": 14,
                "input_cache_miss_minor_per_million": 440,
                "output_minor_per_million": 1320,
            }
        ),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "live",
            "--env-file",
            str(env_file),
            "--price-card-file",
            str(price_card_file),
            "live-preflight",
        ],
        env=_isolated_env(),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = json.loads(completed.stdout)
    assert output["api_key_present"] is True
    assert output["network_accessed"] is False
    assert "fixture-key" not in completed.stdout
