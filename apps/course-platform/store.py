"""Application-owned metadata and durable operation reservations."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
import threading
import uuid

from domain import AppError, digest, require, safe_path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root):
        self.root = safe_path(root, directory=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = safe_path(self.root / "workspace.sqlite3")
        self.mutex = threading.RLock()
        with self.transaction() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, question TEXT NOT NULL,
                    status TEXT NOT NULL, state_json TEXT NOT NULL DEFAULT '{}',
                    archived INTEGER NOT NULL DEFAULT 0, busy INTEGER NOT NULL DEFAULT 1,
                    last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    request_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    action TEXT NOT NULL, payload_hash TEXT NOT NULL, status TEXT NOT NULL,
                    error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL REFERENCES tasks(id),
                    request_id TEXT, kind TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS task_executions (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(id), snapshot_json TEXT NOT NULL);
            """)

    @contextmanager
    def transaction(self):
        with self.mutex:
            safe_path(self.path)
            connection = sqlite3.connect(self.path, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    def _event(self, connection, task, request, kind, details):
        connection.execute("INSERT INTO events(task_id,request_id,kind,details_json,created_at) VALUES(?,?,?,?,?)",
                           (task, request, kind, json.dumps(details, ensure_ascii=False), now()))

    def _task(self, row, detail=True):
        require(row is not None, "NOT_FOUND")
        result = dict(row)
        result["archived"] = bool(result["archived"])
        result["busy"] = bool(result["busy"])
        state = json.loads(result.pop("state_json"))
        if detail:
            result["state"] = state
        result["evidence_count"] = len(state.get("evidence") or [])
        result["decision_outcome"] = "rejected" if any(error in (state.get("errors") or []) for error in
            ("HUMAN_REQUEST_REJECTED", "REPORT_REJECTED")) else None
        return result

    def list_tasks(self):
        with self.transaction() as connection:
            items = [self._task(r, False) for r in connection.execute("SELECT * FROM tasks ORDER BY created_at DESC,id DESC")]
            for item in items:
                binding = connection.execute('SELECT snapshot_json FROM task_executions WHERE task_id=?',(item['id'],)).fetchone()
                if binding:
                    snapshot = json.loads(binding[0])
                    item['execution'] = {k:snapshot[k] for k in ('project_id','contract_hash','execution_hash')}
            return items

    def get(self, task):
        with self.transaction() as connection:
            result = self._task(connection.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone())
            result["events"] = [{**dict(r), "details": json.loads(r["details_json"])} for r in
                                connection.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (task,))]
            for event in result["events"]:
                event.pop("details_json")
            job = connection.execute("SELECT * FROM jobs WHERE task_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (task,)).fetchone()
            result["job"] = dict(job) if job else None
            binding = connection.execute('SELECT snapshot_json FROM task_executions WHERE task_id=?', (task,)).fetchone()
            if binding:
                snapshot = json.loads(binding[0])
                result['execution'] = {k: snapshot[k] for k in ('project_id', 'contract_hash', 'execution_hash')}
            return result

    def execution(self, task):
        with self.transaction() as connection:
            row = connection.execute('SELECT snapshot_json FROM task_executions WHERE task_id=?', (task,)).fetchone()
            return json.loads(row[0]) if row else None

    def reserve(self, request_id, action, payload, *, task=None, actor='local-browser'):
        signature = digest({"action": action, "task": task, "payload": payload})
        with self.transaction() as connection:
            previous = connection.execute("SELECT * FROM jobs WHERE request_id=?", (request_id,)).fetchone()
            if previous:
                require(previous["payload_hash"] == signature, "IDEMPOTENCY_CONFLICT")
                return previous["task_id"], False
            require(connection.execute("SELECT count(*) FROM jobs").fetchone()[0] < 1000, "LIMIT_REACHED")
            require(connection.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] < 8, "LIMIT_REACHED")
            if task is None:
                require(connection.execute("SELECT count(*) FROM tasks").fetchone()[0] < 200, "LIMIT_REACHED")
                task = "task-" + uuid.uuid4().hex
                connection.execute("INSERT INTO tasks(id,title,question,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                                   (task, payload["title"], payload["question"], "INITIALIZING", now(), now()))
                if 'execution' in payload:
                    connection.execute('INSERT INTO task_executions VALUES(?,?)',
                                       (task, json.dumps(payload['execution'], ensure_ascii=False)))
            else:
                row = connection.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
                require(row is not None, "NOT_FOUND")
                require(not row["busy"], "TASK_BUSY")
                state = json.loads(row["state_json"])
                if action != "recover":
                    gate = state.get("status")
                    if action == 'revise':
                        require(gate == 'REPORT_NEEDS_HUMAN' and state.get('human_revision_count', 0) < 2, 'REVISION_INVALID')
                    require(gate in ("NEEDS_HUMAN", "REPORT_NEEDS_HUMAN"), "STALE_APPROVAL")
                    expected = state.get("request_hash" if gate == "NEEDS_HUMAN" else "report_hash")
                    require(payload["expected_hash"] == expected, "STALE_APPROVAL")
                connection.execute("UPDATE tasks SET busy=1,last_error=NULL,updated_at=? WHERE id=?", (now(), task))
            connection.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
                               (request_id, task, action, signature, "queued", None, now(), now()))
            self._event(connection, task, request_id, "operation_requested",
                        {"action": action, "actor": actor, "note": payload.get("note", ""),
                         "expected_hash": payload.get("expected_hash"), "content_quality_approval": False})
            return task, True

    def running(self, request):
        with self.transaction() as connection:
            connection.execute("UPDATE jobs SET status='running',updated_at=? WHERE request_id=?", (now(), request))

    def finish(self, task, request, state=None, error=None):
        with self.transaction() as connection:
            if state is not None:
                connection.execute("UPDATE tasks SET state_json=?,status=?,busy=0,last_error=NULL,updated_at=? WHERE id=?",
                                   (json.dumps(state, ensure_ascii=False), state["status"], now(), task))
            else:
                connection.execute("UPDATE tasks SET busy=0,last_error=?,updated_at=? WHERE id=?", (error, now(), task))
            connection.execute("UPDATE jobs SET status=?,error=?,updated_at=? WHERE request_id=?",
                               ("failed" if error else "completed", error, now(), request))
            self._event(connection, task, request, "operation_failed" if error else "state_updated",
                        {"code": error} if error else {"status": state["status"], "run_id": state.get("run_id")})

    def interrupt_pending(self):
        with self.transaction() as connection:
            for job in connection.execute("SELECT * FROM jobs WHERE status IN ('queued','running')").fetchall():
                connection.execute("UPDATE jobs SET status='interrupted',error='ENGINE_FAILED',updated_at=? WHERE request_id=?", (now(), job["request_id"]))
                connection.execute("UPDATE tasks SET busy=0,last_error='ENGINE_FAILED',updated_at=? WHERE id=?", (now(), job["task_id"]))
                self._event(connection, job["task_id"], job["request_id"], "service_interrupted", {"recovery_requires_operator": True})

    def archive(self, task, archived, actor='local-browser'):
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
            require(row is not None, "NOT_FOUND")
            require(not row["busy"], "TASK_BUSY")
            connection.execute("UPDATE tasks SET archived=?,updated_at=? WHERE id=?", (int(archived), now(), task))
            self._event(connection, task, None, "archive_changed", {"archived": archived, "actor": actor})
