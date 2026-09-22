"""P2 interpreter process; imports the network-denying workflow outside HTTP."""
import argparse
import base64
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import zipfile

from domain import INTEGRATION, decode, fields, require, safe_path

sys.path.insert(0, str(INTEGRATION))
from common import P1, worker, read_json
from workflow_runtime import Runtime, initialize, LIMITATIONS
from cli import summary
from verify_bundle import verify_bundle


def existing_run(root):
    runs = [p for p in root.iterdir() if re.fullmatch(r"run-[a-f0-9]{32}", p.name)]
    require(len(runs) <= 1, "ENGINE_FAILED")
    return safe_path(runs[0], directory=True) if runs else None


def view(runtime):
    state = summary(runtime.state())
    state["approvals"] = [read_json(p) for p in sorted((runtime.root / "approvals").glob("*.json"))]
    state["tool_events"] = [read_json(p) for p in sorted((runtime.root / "tool-events").glob("*.json"))]
    state["limitations"] = LIMITATIONS
    return {"state": state}


def export(runtime):
    delivery = runtime.delivery()
    state = runtime.state()
    result = {"schema_version": "graduation-demo-v1", "workflow": ["NEEDS_HUMAN", "REPORT_NEEDS_HUMAN", "COMPLETED"],
              "approval_actor": "operator-cli", "evidence_count": len(state["evidence"]),
              "mcp_calls": len(delivery["tool_events"]), "scripted_model_calls": state["model_call_count"],
              "real_model_calls": 0, "cost_minor_units": 0, "artifact_count_after_replay": 1,
              "report_hash": state["report_hash"], "content_quality_passed": False, "limitations": LIMITATIONS}
    content = {"delivery.json": (runtime.root / "delivery.json").read_bytes(),
               "delivery-report.md": (runtime.root / "delivery-report.md").read_bytes(),
               "report.md": (runtime.root / "artifacts" / delivery["artifact_name"]).read_bytes(),
               "result.json": (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()}
    for event in delivery["tool_events"]:
        for phase in ("begin", "end"):
            name = "audit-" + event["p3_call_id"] + "-" + phase + ".json"
            content["mcp-audit/" + name] = safe_path(runtime.root / "mcp-audit" / name).read_bytes()
    with tempfile.TemporaryDirectory(prefix="course-export-") as temporary:
        folder = Path(temporary)
        for name, data in content.items():
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        verified = verify_bundle(folder)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(content.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return {"zip_base64": base64.b64encode(stream.getvalue()).decode(), "verification": verified}


def handle(root, payload):
    operation = payload.get("operation")
    if operation == "catalog":
        fields(payload, "operation")
        return worker(P1, "p1_worker.py", {"operation": "catalog"})
    require(operation in ("create", "operate", "export"))
    root = safe_path(root, directory=True)
    run = existing_run(root)
    if operation == "create":
        fields(payload, "operation question")
        if run is None:
            run, _ = initialize(root, payload["question"])
        else:
            require(read_json(run / "run.json")["question"] == payload["question"], "ENGINE_FAILED")
        with Runtime(run) as runtime:
            return view(runtime)
    if operation == "operate":
        fields(payload, "operation action expected_hash question")
        require(payload["action"] in ("approve", "reject", "cancel", "recover"))
        if run is None and payload["action"] == "recover":
            run, _ = initialize(root, payload["question"])
        require(run is not None, "ENGINE_FAILED")
        with Runtime(run) as runtime:
            if payload["action"] == "recover":
                runtime.recover()
            else:
                runtime.decide(payload["action"], payload["expected_hash"], actor="operator-cli")
            return view(runtime)
    fields(payload, "operation")
    require(run is not None, "NOT_COMPLETED")
    with Runtime(run) as runtime:
        return export(runtime)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(8193)
        require(len(raw) <= 8192)
        response = handle(args.task_root, decode(raw))
        print(json.dumps(response, ensure_ascii=False))
    except Exception:
        print('{"error":{"code":"ENGINE_FAILED"}}')
        raise SystemExit(2)
