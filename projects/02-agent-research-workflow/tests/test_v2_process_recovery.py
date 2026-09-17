"""Real process exits at durable boundaries; no network or vendor model."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "run_research_v2.py"

# Each invocation imports the production CLI in a fresh process. os._exit
# bypasses finally blocks and graph checkpoint completion intentionally.
WORKER = r'''
import importlib.util, json, os, socket, sys
from pathlib import Path
cli_path, runtime, crash, command = sys.argv[1:]
def blocked(*args, **kwargs):
    raise AssertionError("NETWORK_FORBIDDEN")
socket.socket.connect = blocked
socket.create_connection = blocked
spec = importlib.util.spec_from_file_location("recovery_cli", cli_path)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
class Model(cli.ScriptedModelClient):
    def generate(self, *, task, payload):
        with open(Path(runtime) / "sends.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"task": task}) + "\n")
            f.flush()
            os.fsync(f.fileno())
        if crash == "dispatched":
            os._exit(73)
        return super().generate(task=task, payload=payload)
cli.ScriptedModelClient = Model
original_success = cli.OperationLedger.record_success
def record_success(self, **kwargs):
    value = original_success(self, **kwargs)
    if crash == "recorded":
        os._exit(73)
    return value
cli.OperationLedger.record_success = record_success
original_export = cli.V2Exporter.export
def export(self, **kwargs):
    value = original_export(self, **kwargs)
    if crash in {"published", "published_async"}:
        os._exit(73)
    return value
cli.V2Exporter.export = export
if crash == "published_async":
    original_build = cli.build_v2_graph
    def build(**kwargs):
        graph = original_build(**kwargs)
        original_invoke = graph.invoke
        def invoke(*args, **kwargs):
            kwargs["durability"] = "async"
            return original_invoke(*args, **kwargs)
        graph.invoke = invoke
        return graph
    cli.build_v2_graph = build
args = ["--env-file", str(Path(runtime) / "absent.env"), "--runtime-root", runtime,
        command, "--thread-id", "thread-process"]
if command == "start":
    args += ["--run-id", "run-process"]
if command == "resume":
    args += ["--action", "approve"]
sys.exit(cli.main(args))
'''


def run(runtime, command, crash="none"):
    runtime.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith(("DEEPSEEK_", "LANGSMITH_", "LANGCHAIN_"))}
    env.update(LANGGRAPH_STRICT_MSGPACK="true", LANGSMITH_TRACING="false")
    return subprocess.run([sys.executable, "-c", WORKER, str(CLI), str(runtime), crash, command],
                          cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=40)


def state(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def sends(runtime):
    path = runtime / "sends.jsonl"
    return [json.loads(line)["task"] for line in path.read_text().splitlines()] if path.exists() else []


@pytest.mark.parametrize("crash", ["dispatched", "recorded", "published", "published_async"])
def test_process_crash_recovers_without_duplicate_send_or_artifact(tmp_path, crash):
    runtime = tmp_path / "runtime"
    assert state(run(runtime, "start"))["status"] == "NEEDS_HUMAN"
    if crash.startswith("published"):
        assert state(run(runtime, "resume"))["status"] == "REPORT_NEEDS_HUMAN"
    assert run(runtime, "resume", crash).returncode == 73
    before = sends(runtime)
    assert before == (["plan", "draft", "review"] if crash.startswith("published") else ["plan"])
    recovered = state(run(runtime, "recover"))
    if crash == "dispatched":
        assert recovered["status"] == "RECOVERY_REVIEW"
        assert sends(runtime) == ["plan"]
        assert not list((runtime / "artifacts").glob("*.md"))
        again = state(run(runtime, "recover"))
        assert again["status"] == "RECOVERY_REVIEW"
        assert sends(runtime) == ["plan"]
    else:
        if crash == "recorded":
            assert recovered["status"] == "REPORT_NEEDS_HUMAN"
            recovered = state(run(runtime, "resume"))
        assert recovered["status"] == "COMPLETED"
        assert sends(runtime) == ["plan", "draft", "review"]
        artifacts = list((runtime / "artifacts").glob("*.md"))
        assert len(artifacts) == 1
        original = artifacts[0].read_bytes()
        assert state(run(runtime, "recover"))["artifact_id"] == recovered["artifact_id"]
        assert artifacts[0].read_bytes() == original
        assert len(list((runtime / "artifacts").glob("*.md"))) == 1
        assert sends(runtime) == ["plan", "draft", "review"]


def test_recover_cannot_approve_either_human_gate(tmp_path):
    runtime = tmp_path / "runtime"
    state(run(runtime, "start"))
    result = run(runtime, "recover")
    assert result.returncode == 2
    assert json.loads(result.stderr)["error"] == "RECOVER_REQUIRES_HUMAN_DECISION"
    assert sends(runtime) == []
    state(run(runtime, "resume"))
    result = run(runtime, "recover")
    assert result.returncode == 2
    assert json.loads(result.stderr)["error"] == "RECOVER_REQUIRES_HUMAN_DECISION"
    assert sends(runtime) == ["plan", "draft", "review"]
    assert not list((runtime / "artifacts").glob("*.md"))
