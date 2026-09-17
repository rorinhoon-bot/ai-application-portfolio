"""Independent integration behavior tests. All runtimes are newly created fixtures."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import BoundaryError, P1, P2, HERE, P1Response, clean_env, digest, worker, publish_bytes
from workflow_runtime import Runtime, initialize, validate_bridge


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    def blocked(*args, **kwargs):
        raise AssertionError("OFFLINE_NETWORK_BLOCKED")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def started(tmp_path):
    return initialize(tmp_path)


def test_start_pauses_without_model_tools_or_report(started):
    root, state = started
    assert state["status"] == "NEEDS_HUMAN"
    assert state["model_call_count"] == state["tool_call_count"] == 0
    assert not list((root / "mcp-audit").glob("*.json"))
    assert not list((root / "artifacts").glob("*.md"))
    with Runtime(root) as runtime:
        with pytest.raises(BoundaryError, match="RUN_BUSY"):
            with Runtime(root):
                raise AssertionError("second operator acquired the run")
        assert runtime.state()["model_call_count"] == 0


def test_full_real_pipeline_checkpoint_reopen_and_idempotent_delivery(started):
    root, first = started
    with Runtime(root) as runtime:
        assert runtime.state()["request_hash"] == first["request_hash"]
        with pytest.raises(BoundaryError, match="APPROVAL_HASH_MISMATCH"):
            runtime.decide("approve", "0" * 64, actor="scripted-test")
        waiting = runtime.decide("approve", first["request_hash"], actor="scripted-test")
    assert waiting["status"] == "REPORT_NEEDS_HUMAN", waiting["errors"]
    assert len(waiting["evidence"]) == 6
    assert not list((root / "artifacts").glob("*.md"))
    assert len(list((root / "mcp-audit").glob("*.json"))) >= 12
    with Runtime(root) as runtime:
        with pytest.raises(BoundaryError, match="APPROVAL_HASH_MISMATCH"):
            runtime.decide("approve", first["request_hash"], actor="scripted-test")
        final = runtime.decide("approve", waiting["report_hash"], actor="scripted-test")
        delivery = runtime.delivery()
    assert final["status"] == "COMPLETED"
    assert len(delivery["approvals"]) == 2
    assert len(delivery["tool_events"]) >= 6
    assert delivery["real_model_calls"] == delivery["cost_minor_units"] == 0
    assert delivery["content_quality_passed"] is False
    before = (root / "delivery.json").read_bytes()
    with Runtime(root) as runtime:
        replay = runtime.decide("approve", waiting["report_hash"], actor="scripted-test")
    assert replay["model_call_count"] == final["model_call_count"]
    assert (root / "delivery.json").read_bytes() == before
    assert len(list((root / "artifacts").glob("*.md"))) == 1


@pytest.mark.parametrize("action,expected", [("reject", "FAILED"), ("cancel", "CANCELLED")])
def test_request_rejection_or_cancel_no_tools_or_export(started, action, expected):
    root, first = started
    with Runtime(root) as runtime:
        state = runtime.decide(action, first["request_hash"], actor="scripted-test")
    assert state["status"] == expected
    assert state["model_call_count"] == 0
    assert not list((root / "tool-events").glob("*.json"))
    assert not list((root / "artifacts").glob("*.md"))


def test_snapshot_tamper_blocks_before_resume(started):
    root, _ = started
    note = next((root / "notes").glob("*.md"))
    note.write_bytes(b"tampered")
    with pytest.raises(BoundaryError, match="SNAPSHOT_DRIFT"):
        Runtime(root)
    assert not list((root / "artifacts").glob("*.md"))


def test_extra_snapshot_member_rejected(started):
    root, _ = started
    (root / "notes" / "extra.md").write_bytes(b"extra")
    with pytest.raises(BoundaryError, match="SNAPSHOT_MEMBER_DRIFT"):
        Runtime(root)


def test_metadata_tamper_rejected(started):
    root, _ = started
    path = root / "run.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["mode"] = "live"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(BoundaryError, match="RUN_METADATA_INVALID"):
        Runtime(root)


def test_invalid_run_path(tmp_path):
    with pytest.raises(BoundaryError, match="RUN_ID_INVALID"):
        Runtime(tmp_path)


def test_p1_actual_parser_retrieval_candidates_and_empty():
    result = P1Response.model_validate(worker(P1, "p1_worker.py", {
        "operation": "search", "query": "human approval", "candidate_ids": ["graph-plan"], "top_k": 1}))
    assert len(result.records) == 1
    record = result.records[0]
    assert record.record_id == "graph-plan-human-approval"
    assert record.block_orders
    assert hashlib.sha256(record.text.encode()).hexdigest() == record.content_sha256
    empty = P1Response.model_validate(worker(P1, "p1_worker.py", {
        "operation": "search", "query": "zzzznomatch987", "candidate_ids": ["chain-plan"], "top_k": 1}))
    assert empty.records == []


def test_p1_unknown_fields_fail():
    with pytest.raises(BoundaryError, match="ADAPTER_FAILED"):
        worker(P1, "p1_worker.py", {"operation": "catalog", "path": "../private"})


def test_bridge_schema_and_snapshot_drift():
    with pytest.raises(BoundaryError, match="MCP_OUTPUT_INVALID"):
        validate_bridge({"approved": True})
    with pytest.raises(BoundaryError, match="MCP_SNAPSHOT_DRIFT"):
        validate_bridge({"schema_version": "p3-bridge-v1", "snapshot_hash": "b" * 64, "results": []}, snapshot_hash="a" * 64)


def test_mcp_failure_stops_graph_without_report(started):
    root, first = started
    with Runtime(root) as runtime:
        with patch("workflow_runtime.p3_call", side_effect=BoundaryError("ADAPTER_TIMEOUT")):
            result = runtime.decide("approve", first["request_hash"], actor="scripted-test")
    assert result["status"] == "FAILED"
    assert "INTEGRATION_EVIDENCE_FAILED" in result["errors"]
    assert not list((root / "artifacts").glob("*.md"))


def test_delivery_before_approval_rejected(started):
    root, _ = started
    with Runtime(root) as runtime:
        with pytest.raises(BoundaryError, match="REPORT_NOT_APPROVED"):
            runtime.delivery()


def test_process_crash_after_publish_recovers_once(started):
    root, first = started
    with Runtime(root) as runtime:
        waiting = runtime.decide("approve", first["request_hash"], actor="scripted-test")
    assert waiting["status"] == "REPORT_NEEDS_HUMAN"
    code = '''
import os, sys
from workflow_runtime import Runtime, V2Exporter
original = V2Exporter.export
def crash(self, **kwargs):
    original(self, **kwargs)
    os._exit(73)
V2Exporter.export = crash
with Runtime(sys.argv[1]) as runtime:
    runtime.decide('approve', sys.argv[2], actor='scripted-test')
'''
    child = subprocess.run([str(P2 / ".venv/Scripts/python.exe"), "-c", code, str(root), waiting["report_hash"]],
                           cwd=HERE, env=clean_env(P2), capture_output=True, timeout=30)
    assert child.returncode == 73, child.stderr.decode(errors="replace")
    assert len(list((root / "artifacts").glob("*.md"))) == 1
    assert not (root / "delivery.json").exists()
    with Runtime(root) as runtime:
        recovered = runtime.recover()
        delivery = runtime.delivery()
    assert recovered["status"] == "COMPLETED"
    assert delivery["real_model_calls"] == 0
    assert recovered["model_call_count"] == waiting["model_call_count"]
    assert len(list((root / "artifacts").glob("*.md"))) == 1


def test_report_reject_does_not_export(started):
    root, first = started
    with Runtime(root) as runtime:
        waiting = runtime.decide("approve", first["request_hash"], actor="scripted-test")
        state = runtime.decide("reject", waiting["report_hash"], actor="scripted-test")
        assert state["status"] == "FAILED"
        assert "REPORT_REJECTED" in state["errors"]
        assert runtime.recover()["status"] == "FAILED"
    assert not list((root / "artifacts").glob("*.md"))
    assert not (root / "delivery-report.md").exists()


def test_receipt_tampering_blocks_delivery(started):
    root, first = started
    with Runtime(root) as runtime:
        waiting = runtime.decide("approve", first["request_hash"], actor="scripted-test")
        receipt = next((root / "mcp-audit").glob("*-end.json"))
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["result_hash"] = "0" * 64
        receipt.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(BoundaryError, match="MCP_AUDIT_INVALID"):
            runtime.decide("approve", waiting["report_hash"], actor="scripted-test")
    assert not (root / "delivery.json").exists()
    assert not list((root / "artifacts").glob("*.md"))


def test_atomic_delivery_publication_is_no_replace(tmp_path):
    path = tmp_path / "report.md"
    publish_bytes(path, b"approved")
    publish_bytes(path, b"approved")
    with pytest.raises(BoundaryError, match="ARTIFACT_CONFLICT"):
        publish_bytes(path, b"different")
    assert path.read_bytes() == b"approved"
    assert list(tmp_path.iterdir()) == [path]


def test_cli_rejects_traversal_without_opening_run():
    result = subprocess.run([str(P2 / ".venv/Scripts/python.exe"), str(HERE / "cli.py"), "status", "../outside"],
                            cwd=HERE, env=clean_env(P2), capture_output=True, timeout=15)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"error": "RUN_ID_INVALID"}
