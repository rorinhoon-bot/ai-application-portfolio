"""Read-only structural verification of an exported demo; standard library only."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import stat

MAX_BYTES = 4 * 1024 * 1024
MAX_CALLS = 64


class VerificationError(ValueError):
    """Stable error code, never raw file contents or paths."""


def require(condition, code):
    if not condition:
        raise VerificationError(code)


def matches(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value) is not None


def sha(value):
    return matches(value, r"[a-f0-9]{64}")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def object_keys(value, fields):
    require(type(value) is dict and set(value) == set(fields.split()), "SCHEMA_INVALID")


def checked_path(path, directory=False):
    # Trusted OS-owned export directory; concurrent malicious path replacement is out of scope.
    for part in (path, *path.parents):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                "PATH_UNSAFE")
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode), "PATH_UNSAFE")


def read_bytes(path):
    checked_path(path)
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    require(len(data) <= MAX_BYTES, "FILE_TOO_LARGE")
    return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "JSON_INVALID")
        result[key] = value
    return result


def invalid_constant(value):
    raise VerificationError("JSON_INVALID")


def decode(data):
    try:
        return json.loads(data, object_pairs_hook=unique_object, parse_constant=invalid_constant,
                          parse_float=invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, VerificationError):
            raise
        raise VerificationError("JSON_INVALID") from None


def integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def verify_bundle(directory, expected_delivery_sha256=None):
    """Verify links and saved bytes, not semantic correctness or actor authenticity."""
    try:
        return _verify(Path(directory).absolute(), expected_delivery_sha256)
    except OSError:
        raise VerificationError("BUNDLE_IO_ERROR") from None


def _verify(root, expected):
    require(expected is None or sha(expected), "ANCHOR_INVALID")
    checked_path(root, directory=True)
    require({p.name for p in root.iterdir()} ==
            {"delivery.json", "result.json", "report.md", "delivery-report.md", "mcp-audit"},
            "BUNDLE_MEMBERS_INVALID")
    raw_delivery = read_bytes(root / "delivery.json")
    delivery_hash = hashlib.sha256(raw_delivery).hexdigest()
    require(expected is None or expected == delivery_hash, "ANCHOR_MISMATCH")
    delivery = decode(raw_delivery)
    object_keys(delivery, "schema_version run_id mode request_hash report_hash artifact_id artifact_name "
                "artifact_sha256 p1_corpus_hash p3_snapshot_hash approvals tool_events evidence_count "
                "scripted_model_calls real_model_calls cost_minor_units content_quality_passed limitations "
                "delivery_report_sha256")
    require(delivery["schema_version"] == "graduation-delivery-v1" and
            delivery["mode"] == "scripted-offline" and
            matches(delivery["run_id"], r"run-[a-f0-9]{32}"), "SCHEMA_INVALID")
    for key in ("request_hash", "report_hash", "artifact_id", "artifact_sha256", "p1_corpus_hash",
                "p3_snapshot_hash", "delivery_report_sha256"):
        require(sha(delivery[key]), "SCHEMA_INVALID")
    require(delivery["artifact_name"] == delivery["artifact_id"] + ".md", "ARTIFACT_NAME_INVALID")
    require(integer(delivery["evidence_count"], 1, MAX_CALLS) and
            integer(delivery["scripted_model_calls"], 0, 12), "SCHEMA_INVALID")
    require(integer(delivery["real_model_calls"], 0, 0) and
            integer(delivery["cost_minor_units"], 0, 0) and
            delivery["content_quality_passed"] is False, "OFFLINE_BOUNDARY_INVALID")
    limitations = delivery["limitations"]
    require(type(limitations) is list and 1 <= len(limitations) <= 20 and
            all(type(item) is str and 1 <= len(item) <= 2000 for item in limitations), "SCHEMA_INVALID")
    report = read_bytes(root / "report.md")
    wrapper = read_bytes(root / "delivery-report.md")
    require(hashlib.sha256(report).hexdigest() == delivery["artifact_sha256"] and
            hashlib.sha256(wrapper).hexdigest() == delivery["delivery_report_sha256"], "REPORT_HASH_MISMATCH")
    require(wrapper.endswith(report + b"\n"), "REPORT_EMBED_MISMATCH")

    approvals = delivery["approvals"]
    require(type(approvals) is list and len(approvals) == 2, "APPROVAL_INVALID")
    gates = set()
    actors = set()
    for approval in approvals:
        object_keys(approval, "action actor content_quality_approval event_hash expected_hash gate run_id")
        gate = approval["gate"]
        require(type(gate) is str and gate in ("NEEDS_HUMAN", "REPORT_NEEDS_HUMAN") and gate not in gates,
                "APPROVAL_INVALID")
        gates.add(gate)
        expected_hash = delivery["request_hash" if gate == "NEEDS_HUMAN" else "report_hash"]
        require(approval["action"] == "approve" and approval["actor"] in ("scripted-test", "operator-cli") and
                approval["content_quality_approval"] is False and approval["run_id"] == delivery["run_id"] and
                approval["expected_hash"] == expected_hash and
                digest({k: v for k, v in approval.items() if k != "event_hash"}) == approval["event_hash"],
                "APPROVAL_INVALID")
        actors.add(approval["actor"])

    events = delivery["tool_events"]
    require(type(events) is list and 1 <= len(events) <= MAX_CALLS, "EVENT_INVALID")
    audit_root = root / "mcp-audit"
    checked_path(audit_root, directory=True)
    calls, evidence, expected_files = set(), {}, set()
    for event in events:
        object_keys(event, "schema_version run_id request_hash p3_call_id p3_snapshot_hash query_hash "
                    "p1_source_sha256 evidence_id result_hash receipt_hash")
        call_id = event["p3_call_id"]
        require(matches(call_id, r"[a-f0-9]{32}") and call_id not in calls, "EVENT_INVALID")
        calls.add(call_id)
        require(event["schema_version"] == "integration-tool-event-v1" and
                event["run_id"] == delivery["run_id"] and event["request_hash"] == delivery["request_hash"] and
                event["p3_snapshot_hash"] == delivery["p3_snapshot_hash"] and
                matches(event["evidence_id"], r"[a-z0-9-]{1,80}#[a-z0-9-]{1,80}") and
                all(sha(event[key]) for key in ("query_hash", "p1_source_sha256", "result_hash", "receipt_hash")),
                "EVENT_INVALID")
        require(evidence.get(event["evidence_id"], event["p1_source_sha256"]) == event["p1_source_sha256"],
                "EVENT_INVALID")
        evidence[event["evidence_id"]] = event["p1_source_sha256"]
        pair = []
        for phase in ("begin", "end"):
            filename = f"audit-{call_id}-{phase}.json"
            expected_files.add(filename)
            receipt = decode(read_bytes(audit_root / filename))
            object_keys(receipt, "arguments_hash call_id content_hash error_code phase result_hash schema_version "
                        "snapshot_hash time tool")
            require(receipt["schema_version"] == "p3-audit-v2" and receipt["call_id"] == call_id and
                    receipt["phase"] == phase and receipt["tool"] == "read_note" and
                    receipt["snapshot_hash"] == delivery["p3_snapshot_hash"] and
                    sha(receipt["arguments_hash"]) and receipt["error_code"] is None and
                    digest({k: v for k, v in receipt.items() if k != "content_hash"}) == receipt["content_hash"],
                    "RECEIPT_INVALID")
            require((receipt["result_hash"] is None) if phase == "begin" else
                    (receipt["result_hash"] == event["result_hash"] and receipt["content_hash"] == event["receipt_hash"]),
                    "RECEIPT_INVALID")
            require(type(receipt["time"]) is str, "RECEIPT_INVALID")
            try:
                timestamp = datetime.fromisoformat(receipt["time"])
                require(timestamp.utcoffset() is not None, "RECEIPT_INVALID")
            except ValueError:
                raise VerificationError("RECEIPT_INVALID") from None
            pair.append((receipt, timestamp))
        require(pair[0][0]["arguments_hash"] == pair[1][0]["arguments_hash"] and pair[0][1] <= pair[1][1],
                "RECEIPT_PAIR_INVALID")
    require({p.name for p in audit_root.iterdir()} == expected_files, "AUDIT_MEMBERS_INVALID")
    require(len(evidence) == delivery["evidence_count"], "EVIDENCE_COUNT_INVALID")

    result = decode(read_bytes(root / "result.json"))
    object_keys(result, "schema_version workflow approval_actor evidence_count mcp_calls scripted_model_calls "
                "real_model_calls cost_minor_units artifact_count_after_replay report_hash content_quality_passed limitations")
    require(result["schema_version"] == "graduation-demo-v1" and
            result["workflow"] == ["NEEDS_HUMAN", "REPORT_NEEDS_HUMAN", "COMPLETED"] and
            type(result["approval_actor"]) is str and actors == {result["approval_actor"]} and
            integer(result["mcp_calls"], len(calls), len(calls)) and
            integer(result["artifact_count_after_replay"], 1, 1), "RESULT_INVALID")
    for key in ("evidence_count", "scripted_model_calls", "real_model_calls", "cost_minor_units",
                "report_hash", "content_quality_passed", "limitations"):
        require(type(result[key]) is type(delivery[key]) and result[key] == delivery[key], "RESULT_INVALID")
    return {"schema_version": "graduation-bundle-verification-v1", "bundle_consistent": True,
            "delivery_sha256": delivery_hash, "anchor_status": "matched" if expected else "unanchored",
            "run_id": delivery["run_id"], "approval_records": len(approvals), "mcp_calls": len(calls),
            "receipt_count": len(expected_files), "evidence_count": len(evidence),
            "content_quality": "not_evaluated", "actor_authenticity": "not_verified",
            "execution_replayed": False,
            "limitations": ["Checks saved bytes and cross-file links, not source or report semantics.",
                            "Request/report objects and full MCP responses are absent; their hashes are not recomputed.",
                            "Hashes are not signatures; the optional anchor must be trusted separately.",
                            "Workflow/cost/replay counts are recorded claims, not independently replayed execution."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--expected-delivery-sha256")
    args = parser.parse_args()
    try:
        result = verify_bundle(args.directory, args.expected_delivery_sha256)
    except VerificationError as error:
        print(json.dumps({"schema_version": "graduation-bundle-verification-v1",
                          "bundle_consistent": False, "error_code": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
