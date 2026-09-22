"""Behavioral tests: isolated application data, loopback HTTP and real offline MCP."""
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain import AppError, DEFAULT_QUESTION, decode, safe_path
from engine import OfflineEngine
from service import Service, StateLock
from server import Server
from store import Store


def request(**overrides):
    return {"request_id": uuid.uuid4().hex, "title": "离线测试任务", "question": DEFAULT_QUESTION, **overrides}


def settled(service, task, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = service.detail(task)
        if not item["busy"]:
            return item
        time.sleep(0.04)
    raise AssertionError("JOB_NOT_SETTLED")


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.failure = None

    def call(self, operation, root, payload):
        self.calls.append((operation, payload))
        if self.failure:
            raise AppError(self.failure)
        status = "NEEDS_HUMAN" if operation == "create" else "REPORT_NEEDS_HUMAN"
        return {"state": {"status": status, "request_hash": "a" * 64, "report_hash": "b" * 64, "evidence": []}}


class UnitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="course-test-")
        self.root = Path(self.temporary.name) / "state"
        self.engine = FakeEngine()
        self.service = Service(self.root, self.engine)

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def new_task(self):
        payload = request()
        task = self.service.create(payload)
        return payload, settled(self.service, task["id"])

    def action(self, task, **overrides):
        return {"request_id": uuid.uuid4().hex, "action": "approve", "expected_hash": "a" * 64,
                "note": "助手测试：确认固定范围", **overrides}

    def test_create_persists_and_requires_approval(self):
        _, task = self.new_task()
        self.assertEqual(task["status"], "NEEDS_HUMAN")
        self.assertEqual(len(self.engine.calls), 1)
        self.assertEqual(task["events"][0]["details"]["actor"], "local-browser")

    def test_create_idempotent_and_conflicting_payload_rejected(self):
        payload, task = self.new_task()
        self.assertEqual(self.service.create(payload)["id"], task["id"])
        self.assertEqual(len(self.engine.calls), 1)
        with self.assertRaisesRegex(AppError, "IDEMPOTENCY_CONFLICT"):
            self.service.create({**payload, "title": "不同研究任务"})

    def test_approval_idempotence_and_stale_hash(self):
        _, task = self.new_task()
        with self.assertRaisesRegex(AppError, "STALE_APPROVAL"):
            self.service.operate(task["id"], self.action(task, expected_hash="f" * 64))
        payload = self.action(task)
        self.service.operate(task["id"], payload)
        updated = settled(self.service, task["id"])
        self.assertEqual(updated["status"], "REPORT_NEEDS_HUMAN")
        self.service.operate(task["id"], payload)
        self.assertEqual(len(self.engine.calls), 2)
        with self.assertRaisesRegex(AppError, "STALE_APPROVAL"):
            self.service.operate(task["id"], self.action(task))

    def test_failure_retains_previous_gate_and_can_recover(self):
        _, task = self.new_task()
        self.engine.failure = "ENGINE_TIMEOUT"
        self.service.operate(task["id"], self.action(task))
        failed = settled(self.service, task["id"])
        self.assertEqual(failed["status"], "NEEDS_HUMAN")
        self.assertEqual(failed["last_error"], "ENGINE_TIMEOUT")
        self.engine.failure = None
        self.service.operate(task["id"], self.action(task, action="recover", expected_hash=""))
        self.assertIsNone(settled(self.service, task["id"])["last_error"])

    def test_explicit_archive_and_unarchive(self):
        _, task = self.new_task()
        self.assertTrue(self.service.archive(task["id"], {"archived": True})["archived"])
        self.assertFalse(self.service.archive(task["id"], {"archived": False})["archived"])
        with self.assertRaises(AppError):
            self.service.archive(task["id"], {"archived": "false"})

    def test_download_cannot_bypass_approval(self):
        _, task = self.new_task()
        with self.assertRaisesRegex(AppError, "NOT_COMPLETED"):
            self.service.download(task["id"])

    def test_strict_inputs_and_path_ids(self):
        for value in [request(extra="bad"), request(title=1), request(question="短"), request(request_id="../escape")]:
            with self.subTest(value=value):
                with self.assertRaises(AppError):
                    self.service.create(value)
        with self.assertRaises(AppError):
            self.service.detail("../../workspace.sqlite3")

    def test_queue_cap_and_busy_conflict(self):
        store = self.service.store
        first = None
        for _ in range(8):
            item, _ = store.reserve(uuid.uuid4().hex, "create", {"title": "排队测试", "question": DEFAULT_QUESTION})
            first = first or item
        with self.assertRaisesRegex(AppError, "LIMIT_REACHED"):
            store.reserve(uuid.uuid4().hex, "create", {"title": "容量测试", "question": DEFAULT_QUESTION})
        store.finish(item, self.service.store.get(item)["job"]["request_id"], error="ENGINE_FAILED")
        with self.assertRaisesRegex(AppError, "TASK_BUSY"):
            store.reserve(uuid.uuid4().hex, "recover", {"expected_hash": "", "note": "恢复测试"}, task=first)

    def test_restart_marks_interrupted_jobs_without_autorun(self):
        store = self.service.store
        task, _ = store.reserve(uuid.uuid4().hex, "create", {"title": "中断测试", "question": DEFAULT_QUESTION})
        self.service.close()
        self.service = Service(self.root, self.engine)
        item = self.service.detail(task)
        self.assertFalse(item["busy"])
        self.assertEqual(item["job"]["status"], "interrupted")
        self.assertEqual(self.engine.calls, [])

    def test_directory_exclusive_lock(self):
        with self.assertRaisesRegex(AppError, "STATE_BUSY"):
            Service(self.root, self.engine)

    def test_foreign_state_directory_rejected(self):
        foreign = Path(self.temporary.name) / "foreign"
        foreign.mkdir()
        (foreign / "unrelated.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(AppError, "STATE_UNSAFE"):
            StateLock(foreign)
        self.assertEqual((foreign / "unrelated.txt").read_text(), "keep")

    def test_duplicate_json_keys_and_nonfinite_rejected(self):
        for raw in (b'{"title":1,"title":2}', b'{"value":NaN}', b'{"value":1e999}', b'\xff', b'[]broken'):
            with self.assertRaises(AppError):
                decode(raw)

    def test_real_worker_timeout_returns_stable_error(self):
        with self.assertRaisesRegex(AppError, "ENGINE_TIMEOUT"):
            OfflineEngine(timeout=0.001).call("catalog", self.root / "timeout-probe", {})

    def test_invalid_worker_operation_returns_no_raw_exception(self):
        with self.assertRaisesRegex(AppError, "ENGINE_FAILED"):
            OfflineEngine().call("unexpected", self.root / "invalid-probe", {})


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="course-http-")
        self.service = Service(Path(self.temporary.name) / "state", FakeEngine())
        self.server = Server(0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.service.close()
        self.temporary.cleanup()

    def call(self, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        base = {} if body is None else {"Origin": f"http://127.0.0.1:{self.port}",
            "X-CSRF-Token": self.server.csrf, "Content-Type": "application/json"}
        base.update(headers or {})
        connection.request("GET" if body is None else "POST", path, body=body, headers=base)
        response = connection.getresponse()
        data = response.read()
        result = response.status, dict(response.getheaders()), data
        connection.close()
        return result

    def test_home_and_assets_security_headers(self):
        for path in ("/", "/styles.css", "/app.js"):
            status, headers, body = self.call(path)
            self.assertEqual(status, 200)
            self.assertGreater(len(body), 100)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertEqual(headers["Cache-Control"], "no-store")

    def test_bootstrap_and_valid_create(self):
        self.assertEqual(json.loads(self.call("/api/bootstrap")[2])["csrf_token"], self.server.csrf)
        status, _, body = self.call("/api/tasks", json.dumps(request()))
        self.assertEqual(status, 202)
        task = json.loads(body)
        self.assertEqual(self.call("/api/tasks/" + task["id"])[0], 200)

    def test_csrf_origin_and_host_rejected(self):
        for headers in ({"X-CSRF-Token": "bad"}, {"Origin": "https://attacker.invalid"},
                        {"Host": "attacker.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.call("/api/tasks", json.dumps(request()), headers)[0], 403)
        self.assertEqual(self.service.store.list_tasks(), [])

    def test_oversize_duplicate_and_unknown_fields(self):
        for body in ('{"title":1,"title":2}', json.dumps(request(extra=1)), ' ' * 8193):
            self.assertEqual(self.call("/api/tasks", body)[0], 400)

    def test_arbitrary_paths_not_exposed(self):
        for path in ("/.env", "/../domain.py", "/%2e%2e/domain.py", "/api/tasks/../../workspace.sqlite3"):
            self.assertEqual(self.call(path)[0], 404)

    def test_untrusted_text_preserved_as_json_data(self):
        text = '<img src=x onerror=alert(1)>'
        _, _, body = self.call("/api/tasks", json.dumps(request(title=text)))
        task = json.loads(body)
        self.assertEqual(task["title"], text)
        self.assertEqual(self.call("/api/tasks/" + task["id"])[1]["Content-Type"], "application/json; charset=utf-8")


class OfflineEndToEndTests(unittest.TestCase):
    def test_real_p1_p2_p3_approval_recovery_export_and_rejection(self):
        with tempfile.TemporaryDirectory(prefix="course-e2e-") as temporary:
            service = Service(Path(temporary) / "state")
            try:
                catalog = service.knowledge()
                self.assertEqual(len(catalog["records"]), 6)
                payload = request()
                task = settled(service, service.create(payload)["id"])
                self.assertIsNone(task["last_error"])
                self.assertEqual(task["status"], "NEEDS_HUMAN")
                self.assertEqual(task["state"]["model_call_count"], 0)
                first = {"request_id": uuid.uuid4().hex, "action": "approve", "expected_hash": task["state"]["request_hash"], "note": "助手离线测试：批准研究范围"}
                service.operate(task["id"], first)
                reviewed = settled(service, task["id"])
                self.assertIsNone(reviewed["last_error"])
                self.assertEqual(reviewed["status"], "REPORT_NEEDS_HUMAN")
                self.assertEqual(reviewed["evidence_count"], 6)
                self.assertEqual(len(reviewed["state"]["tool_events"]), 8)
                second = {**first, "request_id": uuid.uuid4().hex, "expected_hash": reviewed["state"]["report_hash"], "note": "助手离线测试：批准制品交付，不作内容质量认证"}
                service.operate(task["id"], second)
                done = settled(service, task["id"])
                self.assertEqual(done["status"], "COMPLETED", done["last_error"])
                archive = service.download(task["id"])
                with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                    result = json.loads(zipped.read("result.json"))
                    self.assertEqual(result["real_model_calls"], 0)
                    self.assertFalse(result["content_quality_passed"])
                    self.assertIn("delivery-report.md", zipped.namelist())
                service.operate(task["id"], second)
                self.assertEqual(service.download(task["id"]), archive)
                service.close()
                service = Service(Path(temporary) / "state")
                service.operate(task["id"], {**second, "action": "recover", "request_id": uuid.uuid4().hex})
                replay = settled(service, task["id"])
                self.assertEqual(replay["state"]["model_call_count"], done["state"]["model_call_count"])
                self.assertEqual(service.download(task["id"]), archive)
                rejected = settled(service, service.create(request())["id"])
                service.operate(rejected["id"], {**first, "request_id": uuid.uuid4().hex, "action": "reject", "expected_hash": rejected["state"]["request_hash"]})
                rejected = settled(service, rejected["id"])
                self.assertIsNone(rejected["last_error"])
                self.assertNotIn(rejected["status"], ("COMPLETED", "REPORT_NEEDS_HUMAN"))
                self.assertEqual(rejected["decision_outcome"], "rejected")
                self.assertEqual(rejected["state"]["model_call_count"], 0)
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
