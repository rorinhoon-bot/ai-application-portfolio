import json
import os
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "data" / "retry-smoke-report.json"
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "run_retry_smoke.py"


def load_report() -> dict[str, object]:
    value = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_retry_smoke_report_freezes_policy_and_side_effects() -> None:
    report = load_report()

    assert report["slice"] == "V2-D3"
    assert report["status"] == "fake-verified"
    assert report["max_attempts"] == 2
    assert report["retryable_http_statuses"] == [
        408,
        429,
        500,
        502,
        503,
        504,
    ]
    assert report["default_retry_delay_ms"] == 250
    assert report["maximum_retry_delay_ms"] == 2000
    assert report["external_side_effects"] == {
        "network_accessed": False,
        "mimo_called": False,
        "qdrant_written": False,
        "docker_changed": False,
        "dependency_installed": False,
    }


def test_retry_smoke_report_preserves_failure_and_billing_semantics() -> None:
    scenarios = {
        item["name"]: item for item in load_report()["scenarios"]
    }

    assert scenarios["rate_limit_then_success"]["retry_delays_ms"] == [500]
    assert scenarios["connect_error_then_success"][
        "billing_uncertain_attempts"
    ] == 0
    assert scenarios["read_timeout_no_retry"] == {
        "name": "read_timeout_no_retry",
        "outcome": "error",
        "error_code": "MODEL_TIMEOUT",
        "physical_attempt_count": 1,
        "retry_count": 0,
        "retry_delays_ms": [],
        "usage_complete": False,
        "billing_uncertain_attempts": 1,
    }
    assert scenarios["invalid_model_json"]["retry_count"] == 0
    assert scenarios["server_errors_exhausted"][
        "physical_attempt_count"
    ] == 2


def test_retry_smoke_script_reproduces_committed_report() -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert json.loads(completed.stdout) == load_report()
    assert completed.stderr == ""
