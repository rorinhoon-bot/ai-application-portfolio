"""Mutate copies of the recorded export; never invoke project services or databases."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from verify_bundle import VerificationError, digest, verify_bundle, MAX_BYTES

BUNDLE = HERE / "demo/offline-20260917"
ANCHOR = "52d2ccab7f6972507255190763fca9b01b04ac5acfd7b94eb89b8c2e5f73e2db"


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="graduation-review-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "export"
        shutil.copytree(BUNDLE, self.root)
        for target in ("socket.socket.connect", "socket.socket.bind", "socket.getaddrinfo"):
            blocked = patch(target, side_effect=AssertionError("OFFLINE_NETWORK_BLOCKED"))
            blocked.start()
            self.addCleanup(blocked.stop)

    def read(self, name="delivery.json"):
        return json.loads((self.root / name).read_bytes())

    def write(self, value, name="delivery.json"):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    def fails(self, code):
        with self.assertRaisesRegex(VerificationError, "^" + code + "$"):
            verify_bundle(self.root)

    def receipt_path(self, phase="end"):
        return "mcp-audit/audit-" + self.read()["tool_events"][0]["p3_call_id"] + "-" + phase + ".json"

    def test_recorded_bundle_and_anchor_read_only(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = verify_bundle(self.root, ANCHOR)
        self.assertTrue(result["bundle_consistent"])
        self.assertEqual(result["anchor_status"], "matched")
        self.assertEqual((result["approval_records"], result["mcp_calls"], result["receipt_count"]), (2, 8, 16))
        self.assertEqual(result["content_quality"], "not_evaluated")
        self.assertFalse(result["execution_replayed"])
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_unanchored_is_explicit(self):
        self.assertEqual(verify_bundle(self.root)["anchor_status"], "unanchored")

    def test_report_byte_tamper(self):
        with (self.root / "report.md").open("ab") as stream:
            stream.write(b"forged")
        self.fails("REPORT_HASH_MISMATCH")

    def test_delivery_report_byte_tamper(self):
        (self.root / "delivery-report.md").write_bytes(b"replacement")
        self.fails("REPORT_HASH_MISMATCH")

    def test_missing_approval(self):
        value = self.read()
        value["approvals"].pop()
        self.write(value)
        self.fails("APPROVAL_INVALID")

    def test_duplicate_gate(self):
        value = self.read()
        value["approvals"][1] = value["approvals"][0].copy()
        self.write(value)
        self.fails("APPROVAL_INVALID")

    def test_rehashed_approval_other_run(self):
        value = self.read()
        approval = value["approvals"][0]
        approval["run_id"] = "run-" + "0" * 32
        approval["event_hash"] = digest({k: v for k, v in approval.items() if k != "event_hash"})
        self.write(value)
        self.fails("APPROVAL_INVALID")

    def test_rehashed_approval_wrong_expected_hash(self):
        value = self.read()
        approval = value["approvals"][0]
        approval["expected_hash"] = "0" * 64
        approval["event_hash"] = digest({k: v for k, v in approval.items() if k != "event_hash"})
        self.write(value)
        self.fails("APPROVAL_INVALID")

    def test_receipt_missing(self):
        (self.root / self.receipt_path()).unlink()
        self.fails("BUNDLE_IO_ERROR")

    def test_receipt_extra(self):
        (self.root / "mcp-audit/unreferenced.json").write_bytes(b"{}")
        self.fails("AUDIT_MEMBERS_INVALID")

    def test_receipt_self_hash_tamper(self):
        name = self.receipt_path()
        value = self.read(name)
        value["arguments_hash"] = "0" * 64
        self.write(value, name)
        self.fails("RECEIPT_INVALID")

    def test_rehashed_begin_arguments_mismatch(self):
        name = self.receipt_path("begin")
        value = self.read(name)
        value["arguments_hash"] = "0" * 64
        value["content_hash"] = digest({k: v for k, v in value.items() if k != "content_hash"})
        self.write(value, name)
        self.fails("RECEIPT_PAIR_INVALID")

    def test_rehashed_receipt_wrong_snapshot(self):
        name = self.receipt_path()
        value = self.read(name)
        value["snapshot_hash"] = "0" * 64
        value["content_hash"] = digest({k: v for k, v in value.items() if k != "content_hash"})
        self.write(value, name)
        self.fails("RECEIPT_INVALID")

    def test_duplicate_call_id(self):
        value = self.read()
        value["tool_events"].append(value["tool_events"][0].copy())
        self.write(value)
        self.fails("EVENT_INVALID")

    def test_call_path_traversal_rejected_before_read(self):
        value = self.read()
        value["tool_events"][0]["p3_call_id"] = "../../secret"
        self.write(value)
        self.fails("EVENT_INVALID")

    def test_manifest_artifact_path_never_followed(self):
        value = self.read()
        value["artifact_name"] = "../../secret"
        self.write(value)
        self.fails("ARTIFACT_NAME_INVALID")

    def test_extra_env_file_not_read(self):
        (self.root / ".env").write_bytes(b"synthetic-test-marker")
        original_open = Path.open
        def guarded_open(path, *args, **kwargs):
            if path.name == ".env":
                self.fail("Verifier attempted to read an environment file")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", guarded_open):
            self.fails("BUNDLE_MEMBERS_INVALID")

    def test_oversized_file(self):
        (self.root / "delivery.json").write_bytes(b" " * (MAX_BYTES + 1))
        self.fails("FILE_TOO_LARGE")

    def test_duplicate_json_key(self):
        (self.root / "delivery.json").write_bytes(b'{"x":1,"x":2}')
        self.fails("JSON_INVALID")

    def test_nonfinite_json(self):
        for token in (b"NaN", b"Infinity", b"1e999"):
            with self.subTest(token=token):
                (self.root / "delivery.json").write_bytes(b'{"x":' + token + b'}')
                self.fails("JSON_INVALID")

    def test_type_confusion_bool_cost(self):
        value = self.read()
        value["cost_minor_units"] = False
        self.write(value)
        self.fails("OFFLINE_BOUNDARY_INVALID")

    def test_fabricated_quality_pass_rejected(self):
        value = self.read()
        value["content_quality_passed"] = True
        self.write(value)
        self.fails("OFFLINE_BOUNDARY_INVALID")

    def test_summary_counts_mismatch(self):
        value = self.read("result.json")
        value["mcp_calls"] = 99
        self.write(value, "result.json")
        self.fails("RESULT_INVALID")

    def test_whole_bundle_forgery_requires_external_anchor(self):
        # Self-consistent hashes alone cannot authenticate an author or source.
        value = self.read()
        forged = b"A self-consistent but semantically unverified replacement report."
        (self.root / "report.md").write_bytes(forged)
        wrapper = b"Forged wrapper\n" + forged + b"\n"
        (self.root / "delivery-report.md").write_bytes(wrapper)
        value["artifact_sha256"] = hashlib.sha256(forged).hexdigest()
        value["delivery_report_sha256"] = hashlib.sha256(wrapper).hexdigest()
        self.write(value)
        self.assertTrue(verify_bundle(self.root)["bundle_consistent"])
        with self.assertRaisesRegex(VerificationError, "^ANCHOR_MISMATCH$"):
            verify_bundle(self.root, ANCHOR)

    def test_rehashed_report_does_not_match_embedded_copy(self):
        value = self.read()
        (self.root / "report.md").write_bytes(b"replacement")
        value["artifact_sha256"] = hashlib.sha256(b"replacement").hexdigest()
        self.write(value)
        self.fails("REPORT_EMBED_MISMATCH")

    def test_same_evidence_conflicting_source_hash(self):
        value = self.read()
        first = value["tool_events"][0]
        other = next(event for event in value["tool_events"][1:] if event["evidence_id"] == first["evidence_id"])
        other["p1_source_sha256"] = "0" * 64
        self.write(value)
        self.fails("EVENT_INVALID")

    def test_directory_instead_of_receipt(self):
        target = self.root / self.receipt_path()
        target.unlink()
        target.mkdir()
        self.fails("PATH_UNSAFE")

    def test_cli_isolated_read_only_exit_codes(self):
        command = [sys.executable, "-I", "-B", str(HERE / "verify_bundle.py"), str(self.root)]
        okay = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(okay.returncode, 0, okay.stderr)
        self.assertTrue(json.loads(okay.stdout)["bundle_consistent"])
        (self.root / "report.md").write_bytes(b"bad")
        failed = subprocess.run(command, capture_output=True, timeout=10)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertEqual(json.loads(failed.stdout)["error_code"], "REPORT_HASH_MISMATCH")


if __name__ == "__main__":
    unittest.main()
