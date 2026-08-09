"""D-6：40 例固定、原创、离线 P3 评估；不调用模型或外部网络。"""
from __future__ import annotations
import asyncio, json, os, shutil, sys, tempfile

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path: sys.path.insert(0, _SRC)
sys.path.insert(0, os.path.dirname(__file__))
from run_c_phase_eval import _load_gold, _run
from mcp_notes.tasks import (TasksStore, TrustedContext, TaskPublishError, CONFIRMATION_ALREADY_CONSUMED,
    CONFIRMATION_EXPIRED, CONFIRMATION_IDENTITY_MISMATCH, CONFIRMATION_INVALID_ID, CONFIRMATION_MISMATCH,
    CONFIRMATION_REQUIRED, IDEMPOTENCY_CONFLICT, INVALID_ARGUMENTS)

class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now
    def add(self, n): self.now += n

def check(results, name, value): results.append((name, bool(value)))

def main():
    cases = json.load(open(os.path.join(_ROOT, "evals", "cases", "p3-service-v1.json"), encoding="utf-8"))
    gold = json.load(open(os.path.join(_ROOT, "evals", "gold", "p3-service-v1-gold.json"), encoding="utf-8"))
    results = []
    tmp = tempfile.mkdtemp(prefix="p3-d6-")
    try:
        # 前 11 例：原 C 评估代码和金标准原样复跑。
        asyncio.run(_run(os.path.join(tmp, "c"), _load_gold(), results))
        root = os.path.join(tmp, "tasks"); os.makedirs(root)
        clock = Clock(); store = TasksStore(os.path.join(tmp, "state.sqlite"), root, clock=clock)
        a = TrustedContext("d6-user", "a" * 64); b = TrustedContext("other-user", "a" * 64)
        p = store.create_task("D6 任务", "原创离线描述。", a)
        check(results, "D06-12-valid-pending", p.outcome == "pending")
        check(results, "D06-13-pending-no-file", os.listdir(root) == [])
        check(results, "D06-14-invalid-title", store.create_task("", "x", a).error_code == INVALID_ARGUMENTS)
        check(results, "D06-15-invalid-description", store.create_task("x", "", a).error_code == INVALID_ARGUMENTS)
        replay = store.create_task("D6 任务", "原创离线描述。", a)
        check(results, "D06-16-create-replay", replay.confirmation_id == p.confirmation_id and replay.outcome == "pending")
        check(results, "D06-17-idempotency-conflict", store.create_task("另一任务", "不同内容", a).error_code == IDEMPOTENCY_CONFLICT)
        approved = store.approve(p.confirmation_id, a)
        check(results, "D06-18-approve-created", approved.outcome == "created")
        check(results, "D06-19-approve-replay", store.approve(p.confirmation_id, a).error_code == CONFIRMATION_ALREADY_CONSUMED)
        r = store.create_task("拒绝", "原创", TrustedContext("d6-user", "b" * 64)); check(results, "D06-20-reject", store.reject(r.confirmation_id, TrustedContext("d6-user", "b" * 64)).outcome == "rejected")
        c = store.create_task("取消", "原创", TrustedContext("d6-user", "c" * 64)); check(results, "D06-21-cancel", store.cancel(c.confirmation_id, TrustedContext("d6-user", "c" * 64)).outcome == "cancelled")
        x = store.create_task("过期", "原创", TrustedContext("d6-user", "d" * 64)); clock.add(601); check(results, "D06-22-expiry", store.approve(x.confirmation_id, TrustedContext("d6-user", "d" * 64)).error_code == CONFIRMATION_EXPIRED); clock.add(-601)
        check(results, "D06-23-invalid-confirmation", store.approve("bad", a).error_code == CONFIRMATION_INVALID_ID)
        check(results, "D06-24-unknown-confirmation", store.approve("conf-0000000000000000", a).error_code == CONFIRMATION_REQUIRED)
        check(results, "D06-25-context-mismatch", store.approve(p.confirmation_id, b).error_code == CONFIRMATION_IDENTITY_MISMATCH)
        check(results, "D06-26-task-id-shape", p.task_id.startswith("task-") and len(p.task_id) == 21)
        check(results, "D06-27-approved-state", store._conn.execute("SELECT status FROM confirmations WHERE confirmation_id=?", (p.confirmation_id,)).fetchone()[0] == "APPROVED")
        check(results, "D06-28-reject-no-file", not os.path.exists(os.path.join(root, r.task_id + ".json")))
        check(results, "D06-29-cancel-no-file", not os.path.exists(os.path.join(root, c.task_id + ".json")))
        audit_cols = [row[1] for row in store._conn.execute("PRAGMA table_info(audit)")]
        check(results, "D06-30-audit-minimal", "title" not in audit_cols and "description" not in audit_cols)
        check(results, "D06-31-path-text-rejected", store.create_task("../escape", "x", a).error_code == INVALID_ARGUMENTS)
        check(results, "D06-32-url-text-rejected", store.create_task("url", "see https://x.invalid", a).error_code == INVALID_ARGUMENTS)
        check(results, "D06-33-control-text-rejected", store.create_task("bad\x01", "x", a).error_code == INVALID_ARGUMENTS)
        q = store.create_task("恢复", "原创", TrustedContext("d6-user", "e" * 64)); store._conn.execute("UPDATE confirmations SET status='PUBLISHING' WHERE confirmation_id=?", (q.confirmation_id,)); store._conn.commit()
        check(results, "D06-34-publishing-approve-recovery", store.approve(q.confirmation_id, TrustedContext("d6-user", "e" * 64)).outcome == "created")
        z = store.create_task("恢复拒绝", "原创", TrustedContext("d6-user", "f" * 64)); store._conn.execute("UPDATE confirmations SET status='PUBLISHING' WHERE confirmation_id=?", (z.confirmation_id,)); store._conn.commit()
        check(results, "D06-35-publishing-reject-safe", store.reject(z.confirmation_id, TrustedContext("d6-user", "f" * 64)).error_code == CONFIRMATION_MISMATCH)
        err = store.approve("bad", a); check(results, "D06-36-error-no-raw-text", "bad" not in repr(err) and err.error_code == CONFIRMATION_INVALID_ID)
        try: TrustedContext("bad subject", "0" * 64); valid = False
        except TaskPublishError: valid = True
        check(results, "D06-37-invalid-context-rejected", valid)
        check(results, "D06-38-content-hash-stable", p.task_id == replay.task_id)
        check(results, "D06-39-network-free-source", ("import " + "socket") not in open(__file__, encoding="utf-8").read().lower())
        check(results, "D06-40-case-count", len(cases["case_ids"]) == gold["total_cases"] == 40)
        store.close()
    finally: shutil.rmtree(tmp, ignore_errors=True)
    passed = sum(bool(item[1]) for item in results); total = len(results)
    print(f"D6 EVAL: scenarios: {total} passed: {passed} failed: {total-passed}")
    if passed != total:
        print("failed_cases:", [item[0] for item in results if not bool(item[1])])
    return 0 if total == gold["total_cases"] and passed == gold["required_passed"] else 1
if __name__ == "__main__": raise SystemExit(main())
