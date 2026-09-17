"""Explicitly scripted approvals; demonstration never claims human quality grading."""
import argparse
import json
from pathlib import Path
import tempfile

from common import write_once
from workflow_runtime import initialize, Runtime, LIMITATIONS


def run_demo(output=None):
    with tempfile.TemporaryDirectory(prefix="graduation-demo-") as directory:
        root, first = initialize(Path(directory))
        assert first["status"] == "NEEDS_HUMAN"
        assert first["model_call_count"] == 0
        with Runtime(root) as runtime:
            second = runtime.decide("approve", first["request_hash"], actor="scripted-test")
        assert second["status"] == "REPORT_NEEDS_HUMAN", second.get("errors")
        assert not list((root / "artifacts").glob("*.md"))
        with Runtime(root) as runtime:
            final = runtime.decide("approve", second["report_hash"], actor="scripted-test")
            delivery = runtime.delivery()
        with Runtime(root) as runtime:
            replay = runtime.decide("approve", second["report_hash"], actor="scripted-test")
        assert final["status"] == replay["status"] == "COMPLETED"
        assert final["model_call_count"] == replay["model_call_count"]
        assert len(list((root / "artifacts").glob("*.md"))) == 1
        result = {"schema_version": "graduation-demo-v1", "workflow": [first["status"],second["status"],final["status"]],
                  "approval_actor": "scripted-test", "evidence_count": len(final["evidence"]),
                  "mcp_calls": len(delivery["tool_events"]), "scripted_model_calls": final["model_call_count"],
                  "real_model_calls": 0, "cost_minor_units": 0, "artifact_count_after_replay": 1,
                  "report_hash": final["report_hash"], "content_quality_passed": False, "limitations": LIMITATIONS}
        if output:
            output.mkdir(exist_ok=False)
            write_once(output / "result.json", result)
            write_once(output / "delivery.json", delivery)
            (output / "report.md").write_bytes((root / "artifacts" / delivery["artifact_name"]).read_bytes())
            (output / "delivery-report.md").write_bytes((root / "delivery-report.md").read_bytes())
            # Preserve receipts referenced by the delivery for independent hash verification.
            (output / "mcp-audit").mkdir()
            for path in (root / "mcp-audit").glob("*.json"):
                (output / "mcp-audit" / path.name).write_bytes(path.read_bytes())
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(run_demo(args.output), ensure_ascii=False, indent=2))
