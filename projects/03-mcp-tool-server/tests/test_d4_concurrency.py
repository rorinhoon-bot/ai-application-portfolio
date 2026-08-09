"""D-4：确认消费的跨进程串行化与 PUBLISHING 恢复（纯 stdlib，离线）。"""

import multiprocessing
import os
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
_TESTS = os.path.dirname(__file__)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from mcp_notes import tasks
from mcp_notes.tasks import (
    CONFIRMATION_ALREADY_CONSUMED,
    CONFIRMATION_MISMATCH,
    TASK_WRITE_FAILED,
    TaskPublishError,
    TasksStore,
    TrustedContext,
)
from _network_block import NetworkBlockedTestCase


def _approve_worker(db_path, task_root, confirmation_id, subject, correlation_id, gate, out):
    """spawn 可导入的子进程目标；不用 sleep 赌竞争时序。"""
    store = TasksStore(db_path, task_root, clock=lambda: 1000.0)
    try:
        gate.wait()
        result = store.approve(confirmation_id, TrustedContext(subject, correlation_id))
        out.put((result.outcome, result.error_code))
    finally:
        store.close()


class _Clock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class D4ConcurrencyTests(NetworkBlockedTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(prefix="p3-d4-")
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "state.sqlite")
        self.task_root = os.path.join(self.tmp.name, "tasks")
        os.mkdir(self.task_root)
        self.clock = _Clock(1000.0)
        self.store = TasksStore(self.db_path, self.task_root, clock=self.clock)
        self.addCleanup(self.store.close)
        self.context = TrustedContext("d4-user", "d" * 64)

    def _pending(self):
        result = self.store.create_task("D4 标题", "D4 原创离线描述。", self.context)
        self.assertEqual(result.outcome, "pending")
        return result

    def _status(self, confirmation_id):
        return self.store._conn.execute(
            "SELECT status FROM confirmations WHERE confirmation_id=?", (confirmation_id,)
        ).fetchone()[0]

    def test_t1_two_process_approve_has_one_logical_winner(self):
        pending = self._pending()
        self.store.close()
        ctx = multiprocessing.get_context("spawn")
        gate = ctx.Barrier(2)
        out = ctx.Queue()
        args = (self.db_path, self.task_root, pending.confirmation_id, "d4-user", "d" * 64, gate, out)
        first = ctx.Process(target=_approve_worker, args=args)
        second = ctx.Process(target=_approve_worker, args=args)
        first.start(); second.start()
        first.join(20); second.join(20)
        self.assertEqual(first.exitcode, 0)
        self.assertEqual(second.exitcode, 0)
        results = [out.get(timeout=2), out.get(timeout=2)]
        self.assertEqual(sum(1 for outcome, _ in results if outcome == "created"), 1, results)
        self.assertEqual(
            sum(1 for outcome, code in results if outcome == "unchanged" and code == CONFIRMATION_ALREADY_CONSUMED),
            1,
        )
        check = TasksStore(self.db_path, self.task_root, clock=self.clock)
        self.addCleanup(check.close)
        status = check._conn.execute(
            "SELECT status FROM confirmations WHERE confirmation_id=?", (pending.confirmation_id,)
        ).fetchone()[0]
        self.assertEqual(status, "APPROVED")
        self.assertEqual(len(os.listdir(self.task_root)), 1)

    def test_t2_approve_then_reject_cannot_write_negative_terminal(self):
        pending = self._pending()
        self.assertEqual(self.store.approve(pending.confirmation_id, self.context).outcome, "created")
        result = self.store.reject(pending.confirmation_id, self.context)
        self.assertEqual(result.error_code, CONFIRMATION_MISMATCH)
        self.assertEqual(self._status(pending.confirmation_id), "APPROVED")
        self.assertEqual(len(os.listdir(self.task_root)), 1)

    def test_t3_reject_then_approve_never_publishes(self):
        pending = self._pending()
        self.assertEqual(self.store.reject(pending.confirmation_id, self.context).outcome, "rejected")
        result = self.store.approve(pending.confirmation_id, self.context)
        self.assertEqual(result.error_code, CONFIRMATION_MISMATCH)
        self.assertEqual(self._status(pending.confirmation_id), "REJECTED")
        self.assertEqual(os.listdir(self.task_root), [])

    def test_t4_commit_failure_rereads_on_a_new_connection(self):
        pending = self._pending()
        original = tasks._commit
        calls = []

        def fail_only_phase_two(conn):
            calls.append(conn)
            if len(calls) == 2:
                raise tasks.sqlite3.OperationalError("injected")
            return original(conn)

        with mock.patch.object(tasks, "_commit", side_effect=fail_only_phase_two):
            result = self.store.approve(pending.confirmation_id, self.context)
        self.assertIn(result.outcome, {"created", "unchanged"})
        self.assertEqual(self._status(pending.confirmation_id), "APPROVED")
        self.assertEqual(len(os.listdir(self.task_root)), 1)

    def test_t5_duplicate_approve_does_not_republish(self):
        pending = self._pending()
        with mock.patch.object(self.store, "_publish_task_file", wraps=self.store._publish_task_file) as publish:
            self.assertEqual(self.store.approve(pending.confirmation_id, self.context).outcome, "created")
            replay = self.store.approve(pending.confirmation_id, self.context)
        self.assertEqual(replay.error_code, CONFIRMATION_ALREADY_CONSUMED)
        self.assertEqual(publish.call_count, 1)

    def test_t6_expiry_is_guarded_inside_write_reservation(self):
        pending = self._pending()
        self.clock.advance(601)
        result = self.store.cancel(pending.confirmation_id, self.context)
        self.assertEqual(result.error_code, "confirmation-expired")
        self.assertEqual(self._status(pending.confirmation_id), "EXPIRED")
        self.assertEqual(os.listdir(self.task_root), [])

    def test_t7_subject_binding_isolation(self):
        pending = self._pending()
        other = TrustedContext("other-user", "d" * 64)
        result = self.store.approve(pending.confirmation_id, other)
        self.assertEqual(result.error_code, "confirmation-identity-mismatch")
        self.assertEqual(self._status(pending.confirmation_id), "PENDING")

    def test_t8_audit_failure_does_not_reverse_committed_approval(self):
        pending = self._pending()
        with mock.patch.object(tasks, "_make_connection", side_effect=tasks.sqlite3.OperationalError("audit")):
            result = self.store.approve(pending.confirmation_id, self.context)
        self.assertEqual(result.outcome, "created")
        self.assertEqual(self._status(pending.confirmation_id), "APPROVED")

    def test_t9_publishing_recovery_prevents_negative_terminal(self):
        pending = self._pending()
        self.store._conn.execute(
            "UPDATE confirmations SET status='PUBLISHING' WHERE confirmation_id=?",
            (pending.confirmation_id,),
        )
        self.store._conn.commit()
        with mock.patch.object(self.store, "_publish_task_file", return_value="created"):
            result = self.store.reject(pending.confirmation_id, self.context)
        self.assertEqual(result.error_code, CONFIRMATION_MISMATCH)
        self.assertEqual(self._status(pending.confirmation_id), "APPROVED")


if __name__ == "__main__":
    unittest.main()
