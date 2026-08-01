from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_research.demo_runner import (
    DEMO_CASE_IDS,
    DemoRunnerError,
    OfflineDemoBundle,
    compute_demo_bundle_hash,
    run_offline_demo,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATED_ROOT = PROJECT_ROOT / "demo" / "generated"
MANIFEST_PATH = GENERATED_ROOT / "offline-demo-v1.json"
REVIEW_REPORT_PATH = GENERATED_ROOT / "report-v2.md"
REVIEW_REPORT_HASH_PATH = GENERATED_ROOT / "report-v2.md.sha256"
SUMMARY_PATH = (
    PROJECT_ROOT
    / "evals"
    / "results"
    / "privacy-durable-run-summary.json"
)


def test_offline_demo_replays_three_fixed_stories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    run = run_offline_demo(PROJECT_ROOT)

    assert tuple(item.case_id for item in run.bundle.scenarios) == DEMO_CASE_IDS
    assert [item.actual_status.value for item in run.bundle.scenarios] == [
        "NEEDS_HUMAN",
        "COMPLETED",
        "FAILED",
    ]
    assert [item.artifact_count for item in run.bundle.scenarios] == [0, 1, 0]
    assert run.bundle.scenarios[0].tool_attempts == 0
    assert run.bundle.scenarios[1].recommendation == "atlasflow"
    assert run.bundle.scenarios[1].unsupported_claim_count == 0
    assert run.bundle.scenarios[2].retrieval_rounds == 2
    assert run.bundle.node_event_count == 13
    assert run.bundle.interrupted_node_count == 2
    assert run.bundle.model_api_used is False
    assert run.bundle.network_used is False
    assert run.bundle.known_cost_microunits == 0


def test_offline_demo_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")

    first = run_offline_demo(PROJECT_ROOT)
    second = run_offline_demo(PROJECT_ROOT)

    assert first.bundle.to_json() == second.bundle.to_json()
    assert first.report_bytes == second.report_bytes


def test_demo_bundle_rejects_unknown_fields_and_tampering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    bundle = run_offline_demo(PROJECT_ROOT).bundle
    payload = bundle.model_dump(mode="json")

    unknown = dict(payload)
    unknown["api_key"] = "not-allowed"
    with pytest.raises(ValidationError):
        OfflineDemoBundle.model_validate(unknown)

    wrong_hash = dict(payload)
    wrong_hash["node_event_count"] = 12
    with pytest.raises(ValidationError):
        OfflineDemoBundle.model_validate(wrong_hash)

    wrong_order = dict(payload)
    wrong_order["scenarios"] = tuple(reversed(bundle.scenarios))
    wrong_order["bundle_hash"] = "0" * 64
    draft = OfflineDemoBundle.model_construct(**wrong_order)
    wrong_order["bundle_hash"] = compute_demo_bundle_hash(draft)
    with pytest.raises(ValidationError):
        OfflineDemoBundle.model_validate(wrong_order)


def test_demo_requires_strict_msgpack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LANGGRAPH_STRICT_MSGPACK", raising=False)

    with pytest.raises(
        DemoRunnerError,
        match="LANGGRAPH_STRICT_MSGPACK must equal 'true'",
    ):
        run_offline_demo(PROJECT_ROOT)


def test_committed_demo_files_match_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    run = run_offline_demo(PROJECT_ROOT)
    report_path = GENERATED_ROOT / run.bundle.report_file

    assert MANIFEST_PATH.read_text(encoding="utf-8") == run.bundle.to_json()
    assert report_path.read_bytes() == run.report_bytes
    assert SUMMARY_PATH.read_text(encoding="utf-8") == run.run_summary.to_json()
    assert {item.name for item in GENERATED_ROOT.iterdir()} == {
        MANIFEST_PATH.name,
        report_path.name,
        REVIEW_REPORT_PATH.name,
        REVIEW_REPORT_HASH_PATH.name,
    }
    expected_hash = hashlib.sha256(REVIEW_REPORT_PATH.read_bytes()).hexdigest()
    assert REVIEW_REPORT_HASH_PATH.read_text(encoding="utf-8") == (
        f"{expected_hash} *{REVIEW_REPORT_PATH.name}\n"
    )


def test_demo_outputs_exclude_runtime_paths_and_sensitive_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    run = run_offline_demo(PROJECT_ROOT)
    manifest = run.bundle.to_json().lower()
    report = run.report_bytes.decode("utf-8").lower()
    summary = run.run_summary.to_json().lower()

    forbidden = (
        "checkpoint.sqlite",
        "p2-offline-demo-",
        "authorization:",
        "bearer ",
        "cookie:",
        "api_key",
        "vendor_sensitive_response",
    )
    assert not any(value in manifest for value in forbidden)
    assert not any(value in report for value in forbidden)
    assert not any(value in summary for value in forbidden)
    assert not Path(json.loads(manifest)["report_file"]).is_absolute()
