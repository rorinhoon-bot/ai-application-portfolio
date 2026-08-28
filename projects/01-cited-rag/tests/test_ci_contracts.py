import json
from pathlib import Path

import yaml

from scripts.run_ci_smoke import run_smoke


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = PROJECT_ROOT.parents[1] / ".github" / "workflows" / "p1-ci.yml"


def test_fixed_ci_smoke_revalidates_fake_provider_report() -> None:
    report = run_smoke()

    assert report.status == "passed"
    assert report.embedding_provider == "fake"
    assert report.qdrant_provider == "fake"
    assert report.model_provider == "fake"
    assert report.embedding_calls == 1
    assert report.qdrant_calls == 1
    assert report.model_calls == 1
    assert report.network_accessed is False
    assert report.dotenv_read is False
    assert report.model_downloaded is False
    assert report.mimo_called is False
    serialized = json.loads(report.model_dump_json())
    committed = json.loads(
        (PROJECT_ROOT / "data" / "ci-smoke-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert serialized == committed


def test_workflow_pins_official_actions_and_read_only_permissions() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is True
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in text
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in text
    assert "persist-credentials: false" in text
    assert "timeout-minutes:" in text


def test_workflow_runs_smoke_and_never_starts_or_pushes_services() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "scripts/run_ci_smoke.py" in text
    assert "scripts/run_retry_smoke.py" in text
    assert "docker build --tag cited-rag-api:ci" in text
    assert "docker compose up" not in text
    assert "docker push" not in text
    assert "pull_request_target" not in text
    assert "secrets." not in text
