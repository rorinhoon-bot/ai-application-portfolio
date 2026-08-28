import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = PROJECT_ROOT / "data" / "observability-ci-capability-audit.json"
DESIGN_PATH = PROJECT_ROOT / "docs" / "OBSERVABILITY_CI_DESIGN.md"


def audit() -> dict[str, object]:
    value = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_d1_audit_preserves_runtime_and_records_local_install() -> None:
    value = audit()
    baseline = value["current_baseline"]

    assert value["slice"] == "V2-D1+D2"
    assert value["status"] == "workflow-ready"
    assert isinstance(baseline, dict)
    assert baseline["offline_test_count"] == 387
    assert baseline["active_retrieval_mode"] == "hybrid-client-rrf-v1"
    assert baseline["configured_api_image"] == "cited-rag-api:v2-d1"
    assert baseline["docker_engine_running"] is True
    assert value["external_side_effects"] == {
        "python_package_installed": True,
        "collector_image_pulled": True,
        "container_changed": True,
        "qdrant_written": False,
        "mimo_called": False,
        "model_downloaded": False,
        "github_remote_changed": False,
        "cloud_resource_created": False,
    }


def test_dependency_audit_selects_stable_manual_otel_boundary() -> None:
    dependencies = audit()["python_dependency_audit"]

    assert dependencies["binary_only_dry_run_passed"] is True
    assert dependencies["selected_direct"] == {
        "opentelemetry-api": "1.44.0",
        "opentelemetry-sdk": "1.44.0",
        "opentelemetry-exporter-otlp-proto-http": "1.44.0",
    }
    assert dependencies["fastapi_auto_instrumentation"]["selected"] is False
    assert dependencies["installed"] is True


def test_collector_and_actions_are_immutable_candidates() -> None:
    value = audit()
    collector = value["collector_audit"]
    actions = value["github_actions_audit"]

    assert collector["index_digest"] == (
        "sha256:1f2c54a30e713fac6b3ae77a1ec84010c2007e29ced8ec666214fc2f6739c1cc"
    )
    assert collector["host_ports"] == ["127.0.0.1:9464"]
    assert collector["unpublished_ports"] == [4317, 4318]
    assert collector["pulled_in_this_slice"] is True
    assert len(actions["checkout"]["commit"]) == 40
    assert len(actions["setup_python"]["commit"]) == 40
    assert actions["workflow_present"] is True
    assert actions["remote_run_performed"] is False


def test_design_freezes_privacy_failure_isolation_and_approval() -> None:
    text = DESIGN_PATH.read_text(encoding="utf-8")

    assert "question、evidence text、answer" in text
    assert "Collector不加入API readiness依赖" in text
    assert "cost_available=false" in text
    assert "MiMo调用为0" in text
    assert "批准按 OBSERVABILITY_CI_DESIGN.md 第12.1节执行 V2-D1" in text
    assert "批准按 OBSERVABILITY_CI_DESIGN.md 第12.2节执行 V2-D2" in text


def test_ci_design_pins_actions_and_does_not_claim_remote_pass() -> None:
    text = DESIGN_PATH.read_text(encoding="utf-8")

    assert "3d3c42e5aac5ba805825da76410c181273ba90b1" in text
    assert "5fda3b95a4ea91299a34e894583c3862153e4b97" in text
    assert "workflow-ready" in text
    assert "remote-passed" in text
    assert "pull_request_target" in text
