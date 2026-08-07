"""P3 Slice B2a：create_task 受控写入离线核心测试（标准库 unittest，无依赖）。

覆盖（固定离线夹具 + 金标准 tasks-core-v1.json）：
- 未确认 / 批准 / 拒绝 / 取消 / 过期 / 身份错绑 / 内容变化（幂等冲突）
- 重复请求（安全重放）/ 重复批准（已消费幂等）/ 冲突文件（no-replace）/ 原子写入失败
- 非法参数 / 网络阻断 / 敏感信息扫描

所有用例默认继承 NetworkBlockedTestCase，测试期间阻断网络。固定场景来自
evals/gold/tasks-core-v1.json（原创虚构数据，不含密钥 / Cookie / 鉴权头 / 绝对路径）。
"""

import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import nullcontext
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
_TESTS = os.path.dirname(__file__)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from mcp_notes.tasks import (  # noqa: E402
    TasksStore,
    TrustedContext,
    TaskResult,
    TaskPublishError,
    CONFIRMATION_REQUIRED,
    CONFIRMATION_IDENTITY_MISMATCH,
    CONFIRMATION_MISMATCH,
    CONFIRMATION_EXPIRED,
    CONFIRMATION_ALREADY_CONSUMED,
    CONFIRMATION_INVALID_ID,
    IDEMPOTENCY_CONFLICT,
    TASK_CONFLICT,
    TASK_WRITE_FAILED,
    TASK_ROOT_UNSAFE,
    INVALID_ARGUMENTS,
    TASK_TITLE_MAX,
    TASK_DESC_MAX,
    validate_task_field,
)
from mcp_notes import safe_task_write  # noqa: E402
from mcp_notes.safe_task_write import TASK_INVALID_ID, NameCollision  # noqa: E402
from mcp_notes.contracts import TASK_TITLE_MIN, TASK_DESC_MIN  # noqa: E402
from _network_block import NetworkBlockedTestCase  # noqa: E402

_GOLD_PATH = os.path.join(_ROOT, "evals", "gold", "tasks-core-v1.json")

# 禁止泄露模式：扫描源码与生成文件，命中即失败（不回显疑似秘密内容）
# sk- 模式使用负向后顾，避免把 "task-" 中的 "sk" 误判为 API Key
_SECRET_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(r"(?i)api[_-]?key\s*[:=]"),
    re.compile(r"(?i)password\s*[:=]"),
    re.compile(r"(?i)authorization\s*:\s*\S+"),
    re.compile(r"(?i)set-cookie\s*:"),
    re.compile(r"(?i)aws_access_key_id"),
    re.compile(r"[A-Za-z]:\\(?:Users|home)"),
    re.compile(r"/home/[a-z0-9]+/"),
]


def _make_store():
    tmp = tempfile.mkdtemp(prefix="p3-b2a-")
    db_path = os.path.join(tmp, "state.sqlite")
    task_root = os.path.join(tmp, "tasks")
    # 测试夹具：预创建受控任务根（仅为普通临时目录）；生产代码不创建任务根。
    os.makedirs(task_root, exist_ok=True)
    return TasksStore(db_path, task_root), task_root


def _count_task_files(task_root):
    if not os.path.isdir(task_root):
        return 0
    return sum(1 for n in os.listdir(task_root) if n.endswith(".json") and not n.startswith("."))


def _has_temp_leftovers(task_root):
    if not os.path.isdir(task_root):
        return False
    return any(n.startswith(".") and ".tmp." in n for n in os.listdir(task_root))


def _scan_for_secrets(text, label):
    for pat in _SECRET_PATTERNS:
        if pat.search(text):
            raise AssertionError(f"敏感模式命中 {label}: {pat.pattern!r}")


class _Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class TestGoldScenarios(NetworkBlockedTestCase):
    """执行固定金标准 tasks-core-v1.json 中的全部场景。"""

    def setUp(self):
        super().setUp()
        with open(_GOLD_PATH, "r", encoding="utf-8") as fh:
            self.gold = json.load(fh)

    def _task_id_for(self, store, confirmation_id):
        cur = store._conn.cursor()
        row = cur.execute(
            "SELECT task_id FROM confirmations WHERE confirmation_id=?",
            (confirmation_id,),
        ).fetchone()
        return row[0]

    def _assert_step(self, scn, step, res, task_root, store):
        exp = step["expect"]
        self.assertEqual(res.outcome, exp["outcome"], msg=f"{scn['case_id']}: outcome")
        if "error_code" in exp:
            self.assertEqual(
                res.error_code, exp["error_code"], msg=f"{scn['case_id']}: error_code"
            )
        files = _count_task_files(task_root)
        self.assertEqual(files, exp["file_count"], msg=f"{scn['case_id']}: file_count")
        if exp.get("error_code") == TASK_WRITE_FAILED:
            self.assertFalse(
                _has_temp_leftovers(task_root), msg=f"{scn['case_id']}: 不应残留临时文件"
            )
        if "stale_hash" in exp:
            # 冲突场景：既有文件不得被覆盖
            with open(
                os.path.join(task_root, res.task_id + ".json"), "r", encoding="utf-8"
            ) as fh:
                existing = json.load(fh)
            self.assertEqual(
                existing.get("content_hash"), exp["stale_hash"],
                msg=f"{scn['case_id']}: 既有文件未被覆盖",
            )
        # 泄露扫描：生成的所有任务文件不得含敏感模式
        if os.path.isdir(task_root):
            for n in os.listdir(task_root):
                if n.endswith(".json"):
                    with open(os.path.join(task_root, n), "r", encoding="utf-8") as fh:
                        _scan_for_secrets(fh.read(), f"{scn['case_id']}/{n}")

    def _run_scenario(self, scn):
        # 必须用受控时钟构造 store，使 gold 场景中的 clock_start / advance 生效
        clock = _Clock(scn.get("clock_start", 1_000_000))
        tmp = tempfile.mkdtemp(prefix="p3-b2a-")
        db_path = os.path.join(tmp, "state.sqlite")
        task_root = os.path.join(tmp, "tasks")
        # 测试夹具：预创建受控任务根；生产代码不创建任务根。
        os.makedirs(task_root, exist_ok=True)
        store = TasksStore(db_path, task_root, clock=clock)
        pending_ids = {}
        fault = scn.get("inject_fault")
        if fault == "native_create":
            # NtCreateFile 本身失败（创建阶段即报错）
            ctx = mock.patch(
                "mcp_notes.safe_task_write._nt_create_file_fn", side_effect=OSError("fault")
            )
        elif fault == "write_failure":
            # NtCreateFile 成功后的写入阶段失败（WriteFile 返回失败）；清理走真实
            # NtDeleteFile（清理成功路径），最终无残留。
            ctx = mock.patch.object(
                safe_task_write.kernel32, "WriteFile",
                lambda h, buf, n, written, ov: 0,
            )
        else:
            ctx = nullcontext()
        try:
            with ctx:
                for i, step in enumerate(scn["steps"]):
                    if "advance" in step:
                        clock.advance(step["advance"])
                    subj = step["subject"]
                    cid = step["correlation_id"]
                    tc = TrustedContext(subj, cid)
                    op = step["op"]
                    if op == "create":
                        res = store.create_task(step["title"], step["description"], tc)
                        if res.confirmation_id:
                            pending_ids[i] = res.confirmation_id
                    elif op in ("approve", "reject", "cancel"):
                        conf = pending_ids.get(
                            step.get("confirmation_ref"), step.get("confirmation_id")
                        )
                        if op == "approve":
                            res = store.approve(conf, tc)
                        elif op == "reject":
                            res = store.reject(conf, tc)
                        else:
                            res = store.cancel(conf, tc)
                    elif op == "seed_conflict":
                        conf = pending_ids[step["confirmation_ref"]]
                        task_id = self._task_id_for(store, conf)
                        payload = {
                            "task_id": task_id,
                            "title": step.get("title", "stale"),
                            "description": "stale",
                            "content_hash": step.get("content_hash", "stale-hash"),
                            "created_at": clock(),
                            "status": "created",
                        }
                        os.makedirs(task_root, exist_ok=True)
                        with open(
                            os.path.join(task_root, task_id + ".json"),
                            "w",
                            encoding="utf-8",
                        ) as fh:
                            json.dump(payload, fh, ensure_ascii=False)
                        continue
                    else:
                        raise AssertionError(f"unknown op {op}")
                    self._assert_step(scn, step, res, task_root, store)
        finally:
            store.close()

    def test_all_gold_scenarios(self):
        for scn in self.gold["scenarios"]:
            with self.subTest(case_id=scn["case_id"]):
                self._run_scenario(scn)


class TestIllegalParams(NetworkBlockedTestCase):
    def setUp(self):
        super().setUp()
        self.store, self.task_root = _make_store()
        self.addCleanup(self.store.close)
        self.tc = TrustedContext("local-user", "0" * 64)

    def _expect_invalid(self, title, description):
        res = self.store.create_task(title, description, self.tc)
        self.assertEqual(res.outcome, "error")
        self.assertEqual(res.error_code, INVALID_ARGUMENTS)
        self.assertIsNone(res.task_id)
        # 不写任何文件
        self.assertEqual(_count_task_files(self.task_root), 0)

    def test_empty_title(self):
        self._expect_invalid("", "正常描述内容")

    def test_title_too_long(self):
        self._expect_invalid("x" * (TASK_TITLE_MAX + 1), "正常描述内容")

    def test_empty_description(self):
        self._expect_invalid("正常标题", "")

    def test_description_too_long(self):
        self._expect_invalid("正常标题", "x" * (TASK_DESC_MAX + 1))

    def test_control_char_in_title(self):
        self._expect_invalid("标题\x00注入", "正常描述内容")

    def test_path_in_title(self):
        self._expect_invalid("C:\\Users\\x", "正常描述内容")

    def test_url_in_description(self):
        self._expect_invalid("正常标题", "参见 http://example.com")

    def test_shell_token_in_description(self):
        self._expect_invalid("正常标题", "执行 a;b")

    def test_non_string_title(self):
        self._expect_invalid(123, "正常描述内容")

    def test_missing_trusted_context(self):
        res = self.store.create_task("正常标题", "正常描述内容", None)
        self.assertEqual(res.error_code, INVALID_ARGUMENTS)

    def test_empty_subject(self):
        # P1-5：构造即校验，非法 subject 抛受控 TaskPublishError(invalid-arguments)
        with self.assertRaises(TaskPublishError) as cm:
            TrustedContext("", "1" * 64)
        self.assertEqual(cm.exception.code, INVALID_ARGUMENTS)

    def test_empty_correlation_id(self):
        with self.assertRaises(TaskPublishError) as cm:
            TrustedContext("u", "")
        self.assertEqual(cm.exception.code, INVALID_ARGUMENTS)


class TestNoFileWithoutConfirmation(NetworkBlockedTestCase):
    """未批准 / 拒绝 / 取消 / 过期路径均不创建任务文件。"""

    def setUp(self):
        super().setUp()
        self.store, self.task_root = _make_store()
        self.addCleanup(self.store.close)
        self.tc = TrustedContext("local-user", "2" * 64)

    def test_create_does_not_write_file(self):
        res = self.store.create_task("草稿标题", "草稿描述内容。", self.tc)
        self.assertEqual(res.outcome, "pending")
        self.assertEqual(_count_task_files(self.task_root), 0)

    def test_reject_does_not_write_file(self):
        r1 = self.store.create_task("拒绝标题", "拒绝描述内容。", self.tc)
        r2 = self.store.reject(r1.confirmation_id, self.tc)
        self.assertEqual(r2.outcome, "rejected")
        self.assertEqual(_count_task_files(self.task_root), 0)

    def test_cancel_does_not_write_file(self):
        r1 = self.store.create_task("取消标题", "取消描述内容。", self.tc)
        r2 = self.store.cancel(r1.confirmation_id, self.tc)
        self.assertEqual(r2.outcome, "cancelled")
        self.assertEqual(_count_task_files(self.task_root), 0)

    def test_expired_does_not_write_file(self):
        # 用同一可控时钟的存储：创建后推进时钟超过十分钟，再批准
        tmp = tempfile.mkdtemp(prefix="p3-b2a-exp-")
        clock = _Clock(1_000_000)
        store = TasksStore(
            os.path.join(tmp, "s.sqlite"),
            os.path.join(tmp, "t"),
            clock=clock,
        )
        try:
            r1 = store.create_task("过期标题", "过期描述内容。", self.tc)
            self.assertEqual(r1.outcome, "pending")
            clock.advance(700)  # 现在 1_000_700 > 过期时间 1_000_600
            r2 = store.approve(r1.confirmation_id, self.tc)
            self.assertEqual(r2.error_code, CONFIRMATION_EXPIRED)
            self.assertEqual(_count_task_files(os.path.join(tmp, "t")), 0)
        finally:
            store.close()


class TestNetworkBlockExplicit(NetworkBlockedTestCase):
    """受控写核心在测试期间不触发任何网络入口。"""

    def test_socket_blocked_during_operations(self):
        import socket

        from _network_block import _blocked, _blocked_connect

        self.assertIs(socket.socket.connect, _blocked_connect)
        self.assertIs(socket.create_connection, _blocked)
        store, _ = _make_store()
        try:
            tc = TrustedContext("local-user", "3" * 64)
            r1 = store.create_task("网络标题", "网络描述内容。", tc)
            r2 = store.approve(r1.confirmation_id, tc)
            self.assertIn(r2.outcome, ("created", "unchanged"))
        finally:
            store.close()


class TestSourceSecretsScan(NetworkBlockedTestCase):
    """源码与金标准不得含真实密钥 / Cookie / 鉴权头 / 绝对用户路径。"""

    def test_no_secrets_in_source(self):
        src_dir = os.path.join(_ROOT, "src", "mcp_notes")
        scanned = 0
        for name in os.listdir(src_dir):
            if name.endswith(".py"):
                with open(os.path.join(src_dir, name), "r", encoding="utf-8") as fh:
                    _scan_for_secrets(fh.read(), name)
                scanned += 1
        self.assertGreaterEqual(scanned, 5)

    def test_no_secrets_in_gold(self):
        with open(_GOLD_PATH, "r", encoding="utf-8") as fh:
            _scan_for_secrets(fh.read(), "tasks-core-v1.json")


class TestTaskFieldValidation(NetworkBlockedTestCase):
    """validate_task_field 复用 keyword 的 NFKC 优先拒绝策略。"""

    def test_normal(self):
        self.assertEqual(validate_task_field("  标题  ", TASK_TITLE_MIN, TASK_TITLE_MAX), "标题")

    def test_too_short(self):
        self.assertIsNone(validate_task_field("", TASK_TITLE_MIN, TASK_TITLE_MAX))

    def test_too_long(self):
        self.assertIsNone(validate_task_field("x" * (TASK_TITLE_MAX + 1), TASK_TITLE_MIN, TASK_TITLE_MAX))

    def test_fullwidth_path_blocked(self):
        # 全角 Ｃ：＼ 经 NFKC 归一后变成 C:\，必须被路径规则拦截
        self.assertIsNone(validate_task_field("Ｃ：＼Ｕｓｅｒｓ", TASK_TITLE_MIN, TASK_TITLE_MAX))

    def test_url_blocked(self):
        self.assertIsNone(validate_task_field("http://x", TASK_TITLE_MIN, TASK_TITLE_MAX))

    def test_non_string(self):
        self.assertIsNone(validate_task_field(123, TASK_TITLE_MIN, TASK_TITLE_MAX))


class TestCorrelationBinding(NetworkBlockedTestCase):
    """P0-1：approve / reject / cancel 必须 subject 与 correlation_id 同时相等。"""

    def setUp(self):
        super().setUp()
        self.store, self.task_root = _make_store()
        self.addCleanup(self.store.close)

    def test_same_subject_diff_correlation_rejected(self):
        tc1 = TrustedContext("u", "b" * 64)
        r = self.store.create_task("标题", "描述内容。", tc1)
        self.assertEqual(r.outcome, "pending")
        tc2 = TrustedContext("u", "c" * 64)  # 同 subject 不同 correlation_id
        for op in ("approve", "reject", "cancel"):
            res = getattr(self.store, op)(r.confirmation_id, tc2)
            self.assertEqual(
                res.error_code, CONFIRMATION_IDENTITY_MISMATCH, msg=f"{op}: 应身份错绑"
            )
        # 任务文件数始终为 0
        self.assertEqual(_count_task_files(self.task_root), 0)

    def test_matching_correlation_approves(self):
        tc = TrustedContext("u", "b" * 64)
        r = self.store.create_task("标题", "描述内容。", tc)
        res = self.store.approve(r.confirmation_id, tc)
        self.assertEqual(res.outcome, "created")
        self.assertEqual(_count_task_files(self.task_root), 1)


class TestAlreadyConsumedNotExpired(NetworkBlockedTestCase):
    """P0-2：已消费状态（APPROVED）不被过期逻辑改写。"""

    def test_approved_stays_approved_past_expiry(self):
        tmp = tempfile.mkdtemp(prefix="p3-p02-")
        clock = _Clock(1_000_000)
        os.makedirs(os.path.join(tmp, "t"), exist_ok=True)  # 测试夹具预创建任务根
        store = TasksStore(
            os.path.join(tmp, "s.sqlite"), os.path.join(tmp, "t"), clock=clock
        )
        try:
            tc = TrustedContext("u", "5" * 64)
            r = store.create_task("标题", "描述内容。", tc)
            self.assertEqual(store.approve(r.confirmation_id, tc).outcome, "created")
            clock.advance(700)  # 超过十分钟有效期
            r3 = store.approve(r.confirmation_id, tc)
            self.assertEqual(r3.outcome, "unchanged")
            self.assertEqual(r3.error_code, CONFIRMATION_ALREADY_CONSUMED)
            # 数据库仍为 APPROVED，不二次写
            cur = store._conn.cursor()
            row = cur.execute(
                "SELECT status FROM confirmations WHERE confirmation_id=?",
                (r.confirmation_id,),
            ).fetchone()
            self.assertEqual(row[0], "APPROVED")
            self.assertEqual(_count_task_files(os.path.join(tmp, "t")), 1)
        finally:
            store.close()

    def test_reject_after_approved_is_mismatch(self):
        tmp = tempfile.mkdtemp(prefix="p3-p02-")
        clock = _Clock(1_000_000)
        os.makedirs(os.path.join(tmp, "t"), exist_ok=True)  # 测试夹具预创建任务根
        store = TasksStore(
            os.path.join(tmp, "s.sqlite"), os.path.join(tmp, "t"), clock=clock
        )
        try:
            tc = TrustedContext("u", "6" * 64)
            r = store.create_task("标题", "描述内容。", tc)
            self.assertEqual(store.approve(r.confirmation_id, tc).outcome, "created")
            res = store.reject(r.confirmation_id, tc)
            self.assertEqual(res.error_code, CONFIRMATION_MISMATCH)
            self.assertEqual(_count_task_files(os.path.join(tmp, "t")), 1)
        finally:
            store.close()


class TestNoReplacePublish(NetworkBlockedTestCase):
    """P0-3：真正 no-replace；最终发布瞬间目标出现必须 task-conflict。"""

    def setUp(self):
        super().setUp()
        self.store, self.task_root = _make_store()
        self.addCleanup(self.store.close)
        self.tc = TrustedContext("u", "7" * 64)

    def test_race_target_appears_at_publish(self):
        r = self.store.create_task("race 标题", "race 描述内容。", self.tc)
        self.assertEqual(r.outcome, "pending")

        def fake_create(parent, name, disposition):
            # 模拟并发进程在“我们创建之前”写入了目标（不同内容）
            target = os.path.join(self.task_root, name)
            if not os.path.exists(target):
                with open(target, "w", encoding="utf-8") as fh:
                    json.dump({"content_hash": "other-hash", "status": "created"}, fh)
            raise NameCollision()

        with mock.patch(
            "mcp_notes.safe_task_write._nt_create_file", side_effect=fake_create
        ):
            res = self.store.approve(r.confirmation_id, self.tc)
        self.assertEqual(res.error_code, TASK_CONFLICT)
        # 既有目标字节不变
        with open(os.path.join(self.task_root, r.task_id + ".json"), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["content_hash"], "other-hash")
        self.assertFalse(_has_temp_leftovers(self.task_root))
        self.assertEqual(_count_task_files(self.task_root), 1)


class TestTaskRootSafety(NetworkBlockedTestCase):
    """P0-4：任务根 / 祖先目录 B1 同等级安全边界，失败关闭。"""

    def setUp(self):
        super().setUp()
        self.store, self.task_root = _make_store()
        self.addCleanup(self.store.close)
        self.tc = TrustedContext("u", "8" * 64)

    def test_native_unavailable_fails_closed(self):
        # 非 Windows / 原生不可用 → 失败关闭、不写文件
        with mock.patch.object(safe_task_write, "_NATIVE_AVAILABLE", False), \
             mock.patch.object(safe_task_write, "ntdll", None):
            r = self.store.create_task("标题", "描述内容。", self.tc)
            res = self.store.approve(r.confirmation_id, self.tc)
        self.assertEqual(res.error_code, TASK_ROOT_UNSAFE)
        self.assertEqual(_count_task_files(self.task_root), 0)

    def test_reparse_root_fails_closed(self):
        # 任务根（祖先）被 reparse 拦截 → 失败关闭、不写文件
        with mock.patch(
            "mcp_notes.safe_task_write._nt_open",
            side_effect=safe_task_write.NotAllowedReparse(),
        ):
            r = self.store.create_task("标题", "描述内容。", self.tc)
            res = self.store.approve(r.confirmation_id, self.tc)
        self.assertEqual(res.error_code, TASK_ROOT_UNSAFE)
        self.assertEqual(_count_task_files(self.task_root), 0)

    def test_file_create_reparse_fails_closed(self):
        # 文件创建路径被 reparse 拦截（OBJ_DONT_REPARSE）→ 失败关闭
        with mock.patch(
            "mcp_notes.safe_task_write._nt_create_file",
            side_effect=safe_task_write.NotAllowedReparse(),
        ):
            r = self.store.create_task("标题", "描述内容。", self.tc)
            res = self.store.approve(r.confirmation_id, self.tc)
        self.assertEqual(res.error_code, TASK_ROOT_UNSAFE)
        self.assertEqual(_count_task_files(self.task_root), 0)

    def test_task_id_injection_rejected(self):
        # 越权路径 / 非法 task_id 直接被安全层拒绝，不写文件
        with self.assertRaises(safe_task_write.SafeWriteError) as cm:
            safe_task_write.publish_task_file(
                self.task_root, "../escape.json", {"x": 1}
            )
        self.assertEqual(cm.exception.code, TASK_INVALID_ID)
        self.assertEqual(_count_task_files(self.task_root), 0)

    def test_happy_path_writes_via_native(self):
        # 真实 Windows 原生路径：批准确实写出任务文件（验证安全层被实际执行）
        if not safe_task_write._NATIVE_AVAILABLE:
            self.skipTest("native layer unavailable on this platform")
        r = self.store.create_task("标题", "描述内容。", self.tc)
        res = self.store.approve(r.confirmation_id, self.tc)
        self.assertEqual(res.outcome, "created")
        self.assertEqual(_count_task_files(self.task_root), 1)


class TestTrustedContextValidation(NetworkBlockedTestCase):
    """P1-5 / D-1：TrustedContext.subject / correlation_id 严格校验（D-1 为 subject 精确字符白名单）。"""

    def test_invalid_subject_type(self):
        with self.assertRaises(TaskPublishError) as cm:
            TrustedContext(123, "c")
        self.assertEqual(cm.exception.code, INVALID_ARGUMENTS)

    def test_invalid_correlation_type(self):
        with self.assertRaises(TaskPublishError) as cm:
            TrustedContext("u", 456)
        self.assertEqual(cm.exception.code, INVALID_ARGUMENTS)

    def test_empty_both(self):
        with self.assertRaises(TaskPublishError):
            TrustedContext("", "")

    def test_control_char_rejected(self):
        with self.assertRaises(TaskPublishError):
            TrustedContext("u\x00x", "c")

    def test_too_long_rejected(self):
        with self.assertRaises(TaskPublishError):
            TrustedContext("u", "c" * 300)

    def test_valid(self):
        tc = TrustedContext("local-user", "d" * 64)
        self.assertEqual(tc.subject, "local-user")
        self.assertEqual(tc.correlation_id, "d" * 64)

    # ---- D-1 精确身份格式：subject 字符白名单 ----

    def test_subject_with_space_rejected(self):
        with self.assertRaises(TaskPublishError):
            TrustedContext("bad subject", "b" * 64)

    def test_subject_with_cjk_rejected(self):
        with self.assertRaises(TaskPublishError):
            TrustedContext("用户", "b" * 64)

    def test_subject_leading_hyphen_rejected(self):
        with self.assertRaises(TaskPublishError):
            TrustedContext("-bad", "b" * 64)

    def test_subject_too_long_rejected(self):
        with self.assertRaises(TaskPublishError):
            TrustedContext("a" * 129, "b" * 64)

    def test_subject_special_chars_valid(self):
        tc = TrustedContext("a.b_c-d", "e" * 64)
        self.assertEqual(tc.subject, "a.b_c-d")

    # ---- D-1 修正（P0-1）：correlation_id 在核心类型层强制 ^[0-9a-f]{64}$ ----

    def test_illegal_correlation_id_rejected(self):
        # ① 非 64 位小写十六进制的 correlation_id 必须在构造期被拒
        with self.assertRaises(TaskPublishError):
            TrustedContext("good", "c-1")  # 旧格式非 64-hex
        with self.assertRaises(TaskPublishError):
            TrustedContext("good", "C" * 64)  # 大写非法
        with self.assertRaises(TaskPublishError):
            TrustedContext("good", "g" + "0" * 63)  # 含非 hex 字符

    def test_64hex_correlation_id_accepted(self):
        # ② 合法 64 位小写十六进制 correlation_id 被接受
        tc = TrustedContext("good", "f" * 64)
        self.assertEqual(tc.subject, "good")
        self.assertEqual(tc.correlation_id, "f" * 64)

    def test_create_task_blocks_illegal_correlation_id(self):
        # ③ TasksStore.create_task 不能经“直接构造的非法 correlation_id”到达；
        # 核心类型层强制格式，非法 correlation_id 在 TrustedContext 构造期即失败。
        with self.assertRaises(TaskPublishError):
            TrustedContext("good", "not-64-hex")
        # 合法 correlation_id 仍可比正常创建 PENDING（对照组）
        store, task_root = _make_store()
        self.addCleanup(store.close)
        tc = TrustedContext("good", "f" * 64)
        res = store.create_task("标题", "描述内容。", tc)
        self.assertEqual(res.outcome, "pending")
        self.assertEqual(_count_task_files(task_root), 0)


class TestConfirmationIdNoEcho(NetworkBlockedTestCase):
    """P1-6：confirmation_id 严格格式校验，错误结果不得回显任意输入。"""

    def setUp(self):
        super().setUp()
        self.store, self.task_root = _make_store()
        self.addCleanup(self.store.close)
        self.tc = TrustedContext("u", "4" * 64)

    def _assert_no_echo(self, res):
        self.assertEqual(res.error_code, CONFIRMATION_INVALID_ID)
        self.assertIsNone(res.confirmation_id)  # 绝不回显原始输入

    def test_absolute_path_rejected(self):
        res = self.store.approve("C:\\Windows\\x.json", self.tc)
        self._assert_no_echo(res)

    def test_over_long_rejected(self):
        res = self.store.approve("conf-" + "a" * 200, self.tc)
        self._assert_no_echo(res)

    def test_illegal_type_rejected(self):
        res = self.store.approve(12345, self.tc)
        self._assert_no_echo(res)

    def test_unknown_but_valid_format_not_echoed(self):
        # 格式合法但不存在 → confirmation-required，且不回显
        res = self.store.approve("conf-" + "0" * 16, self.tc)
        self.assertEqual(res.error_code, CONFIRMATION_REQUIRED)
        self.assertIsNone(res.confirmation_id)
        self.assertEqual(_count_task_files(self.task_root), 0)


class TestWriteFailureAfterCreate(NetworkBlockedTestCase):
    """P0-1：NtCreateFile 成功后写入 / 刷新失败必须映射为稳定 task-write-failed。

    关键不变量：不抛原始异常、0 字节 / 半成品 / 临时文件由句柄原生清理
    （先关闭文件 HANDLE，再对已验证父目录 HANDLE 相对 NtDeleteFile；
    绝不 os.remove / os.replace / 任何字符串路径回退），确认记录保持 PENDING，
    移除故障后可安全重试并成功创建。
    """

    def setUp(self):
        super().setUp()
        self.store, self.task_root = _make_store()
        self.addCleanup(self.store.close)
        self.tc = TrustedContext("u", "9" * 64)

    def _payload(self, task_id):
        return {
            "task_id": task_id,
            "title": "标题",
            "description": "描述内容。",
            "content_hash": "h-" + task_id,
            "created_at": 1.0,
            "status": "created",
        }

    def test_flush_failure_maps_to_task_write_failed_and_no_residual(self):
        if not safe_task_write._NATIVE_AVAILABLE:
            self.skipTest("native layer unavailable")
        task_id = "task-wflush001"
        payload = self._payload(task_id)
        # 注入：NtCreateFile 成功，但 FlushFileBuffers 返回失败（flush 失败）
        with mock.patch.object(safe_task_write.kernel32, "FlushFileBuffers", lambda h: 0):
            with self.assertRaises(safe_task_write.SafeWriteError) as cm:
                safe_task_write.publish_task_file(self.task_root, task_id, payload)
        # 不抛原始异常：稳定码 task-write-failed
        self.assertEqual(cm.exception.code, TASK_WRITE_FAILED)
        # 无残留最终文件 / 半成品 / 临时文件：任务目录必须完全为空
        self.assertEqual(_count_task_files(self.task_root), 0)
        self.assertFalse(_has_temp_leftovers(self.task_root))
        self.assertEqual(sorted(os.listdir(self.task_root)), [])
        # 移除故障后重试可成功创建
        self.assertEqual(
            safe_task_write.publish_task_file(self.task_root, task_id, payload), "created"
        )
        self.assertEqual(_count_task_files(self.task_root), 1)

    def test_write_failure_maps_to_task_write_failed_and_no_residual(self):
        if not safe_task_write._NATIVE_AVAILABLE:
            self.skipTest("native layer unavailable")
        task_id = "task-wwrite002"
        payload = self._payload(task_id)
        # 注入：NtCreateFile 成功，但 WriteFile 返回 0（写入失败）
        with mock.patch.object(
            safe_task_write.kernel32, "WriteFile",
            lambda h, buf, n, written, ov: 0,
        ):
            with self.assertRaises(safe_task_write.SafeWriteError) as cm:
                safe_task_write.publish_task_file(self.task_root, task_id, payload)
        self.assertEqual(cm.exception.code, TASK_WRITE_FAILED)
        self.assertEqual(_count_task_files(self.task_root), 0)
        self.assertFalse(_has_temp_leftovers(self.task_root))
        self.assertEqual(sorted(os.listdir(self.task_root)), [])
        # 移除故障后重试可成功创建
        self.assertEqual(
            safe_task_write.publish_task_file(self.task_root, task_id, payload), "created"
        )
        self.assertEqual(_count_task_files(self.task_root), 1)

    def test_approve_write_failure_keeps_pending_and_retry_creates(self):
        if not safe_task_write._NATIVE_AVAILABLE:
            self.skipTest("native layer unavailable")
        r = self.store.create_task("标题", "描述内容。", self.tc)
        self.assertEqual(r.outcome, "pending")
        # 注入刷新失败：approve 返回 task-write-failed，确认记录保持 PENDING
        with mock.patch.object(safe_task_write.kernel32, "FlushFileBuffers", lambda h: 0):
            res = self.store.approve(r.confirmation_id, self.tc)
        self.assertEqual(res.error_code, TASK_WRITE_FAILED)
        # 上层返回服务派生 task_id（不回显任何外部输入）
        self.assertEqual(res.task_id, r.task_id)
        self.assertEqual(_count_task_files(self.task_root), 0)
        self.assertFalse(_has_temp_leftovers(self.task_root))
        self.assertEqual(sorted(os.listdir(self.task_root)), [])
        # 确认记录保持 PENDING（未提交 APPROVED）
        cur = self.store._conn.cursor()
        row = cur.execute(
            "SELECT status FROM confirmations WHERE confirmation_id=?",
            (r.confirmation_id,),
        ).fetchone()
        self.assertEqual(row[0], "PENDING")
        # 移除故障后重试可成功创建
        res2 = self.store.approve(r.confirmation_id, self.tc)
        self.assertEqual(res2.outcome, "created")
        self.assertEqual(_count_task_files(self.task_root), 1)


class TestConflictReadonlyAndDeleteFailure(NetworkBlockedTestCase):
    """P0-1 / P0-2 收口回归：冲突只读转换失败与删除失败均映射为稳定码、不泄露原始异常。

    - 冲突只读失败（P0-1）：冲突文件存在 + 原生冒烟完成后，分别注入已验证 HANDLE → fd
      只读转换的 `open_osfhandle` 失败 / `fdopen` 失败 / `read` 失败；`approve` 必须返回
      稳定码、confirmation 仍 PENDING、无原始异常文本，且**退出 mock 后冲突文件可被立即
      删除**（证明 `_read_existing_json` 已精确释放仍归本函数所有的 HANDLE/fd，无遗留锁）。
    - 删除失败（P0-2）：NtCreateFile 成功后写入失败触发清理路径，但 `NtDeleteFile` 返回
      非成功 NTSTATUS；清理失败**不得静默吞掉**，必须返回脱敏稳定 task-write-failed，
      且不回显 NTSTATUS / 路径；此情形下不能错误断言目录必空（残余可能仍在）。
    """

    def setUp(self):
        super().setUp()
        self.store, self.task_root = _make_store()
        self.addCleanup(self.store.close)
        self.tc = TrustedContext("u", "a" * 64)

    def _make_conflict_file(self, task_id, content_hash):
        path = os.path.join(self.task_root, task_id + ".json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({
                "task_id": task_id,
                "title": "标题",
                "description": "描述内容。",
                "content_hash": content_hash,
                "created_at": 1.0,
                "status": "created",
            }, fh)
        return path

    def test_conflict_readonly_conversion_failure_returns_stable_code_pending(self):
        if not safe_task_write._NATIVE_AVAILABLE:
            self.skipTest("native layer unavailable")
        # 原生冒烟：确认原生层可用
        self.assertTrue(safe_task_write.verify_native_support())
        r = self.store.create_task("标题", "描述内容。", self.tc)
        self.assertEqual(r.outcome, "pending")
        # 预写同 task_id 冲突文件（内容哈希不同，确保走 NameCollision 分支）
        path = self._make_conflict_file(r.task_id, "different-content-hash")
        # 注入：已验证 HANDLE → fd 只读转换失败（open_osfhandle 抛 OSError）
        with mock.patch.object(
            safe_task_write.msvcrt, "open_osfhandle", side_effect=OSError("injected-fault")
        ):
            res = self.store.approve(r.confirmation_id, self.tc)
        # 不抛原始异常：返回稳定错误码 task-write-failed
        self.assertEqual(res.error_code, TASK_WRITE_FAILED)
        self.assertEqual(res.task_id, r.task_id)
        # 确认记录保持 PENDING（未提交 APPROVED）
        cur = self.store._conn.cursor()
        row = cur.execute(
            "SELECT status FROM confirmations WHERE confirmation_id=?",
            (r.confirmation_id,),
        ).fetchone()
        self.assertEqual(row[0], "PENDING")
        # 不泄露原始异常文本（无 "injected-fault" / "OSError"）
        self.assertNotIn("injected-fault", repr(res))
        self.assertNotIn("OSError", repr(res))
        # 无锁证据：退出 mock 后冲突文件可被立即删除（_read_existing_json 已释放 fh，无遗留锁）
        os.remove(path)
        self.assertFalse(os.path.exists(path))

    def test_conflict_readonly_fdopen_failure_returns_stable_code_pending(self):
        if not safe_task_write._NATIVE_AVAILABLE:
            self.skipTest("native layer unavailable")
        self.assertTrue(safe_task_write.verify_native_support())
        r = self.store.create_task("标题", "描述内容。", self.tc)
        self.assertEqual(r.outcome, "pending")
        path = self._make_conflict_file(r.task_id, "different-content-hash")
        # 注入：HANDLE → fd 转换成功，但 os.fdopen 抛 OSError；fd 仍归本函数所有，须精确关闭一次
        with mock.patch.object(
            safe_task_write.os, "fdopen", side_effect=OSError("injected-fdopen-fault")
        ):
            res = self.store.approve(r.confirmation_id, self.tc)
        self.assertEqual(res.error_code, TASK_WRITE_FAILED)
        self.assertEqual(res.task_id, r.task_id)
        cur = self.store._conn.cursor()
        row = cur.execute(
            "SELECT status FROM confirmations WHERE confirmation_id=?",
            (r.confirmation_id,),
        ).fetchone()
        self.assertEqual(row[0], "PENDING")
        self.assertNotIn("injected-fdopen-fault", repr(res))
        self.assertNotIn("OSError", repr(res))
        # 无锁证据：退出 mock 后冲突文件可被立即删除（fd 已精确关闭一次，无遗留锁）
        os.remove(path)
        self.assertFalse(os.path.exists(path))

    def test_conflict_readonly_read_failure_returns_stable_code_pending(self):
        if not safe_task_write._NATIVE_AVAILABLE:
            self.skipTest("native layer unavailable")
        self.assertTrue(safe_task_write.verify_native_support())
        r = self.store.create_task("标题", "描述内容。", self.tc)
        self.assertEqual(r.outcome, "pending")
        path = self._make_conflict_file(r.task_id, "different-content-hash")
        # 注入：fdopen 返回真实文件对象（真实 fd 仍须被关闭），但 read() 抛 OSError
        real_fdopen = safe_task_write.os.fdopen

        def _fdopen_raising_read(fd, mode, *args, **kwargs):
            fobj = real_fdopen(fd, mode, *args, **kwargs)
            real_read = fobj.read

            def _read(*a, **k):
                raise OSError("injected-read-fault")

            fobj.read = _read
            return fobj

        with mock.patch.object(
            safe_task_write.os, "fdopen", side_effect=_fdopen_raising_read
        ):
            res = self.store.approve(r.confirmation_id, self.tc)
        self.assertEqual(res.error_code, TASK_WRITE_FAILED)
        self.assertEqual(res.task_id, r.task_id)
        cur = self.store._conn.cursor()
        row = cur.execute(
            "SELECT status FROM confirmations WHERE confirmation_id=?",
            (r.confirmation_id,),
        ).fetchone()
        self.assertEqual(row[0], "PENDING")
        self.assertNotIn("injected-read-fault", repr(res))
        self.assertNotIn("OSError", repr(res))
        # 无锁证据：退出 mock 后冲突文件可被立即删除（真实 fd 已通过 f.close() 释放，无遗留锁）
        os.remove(path)
        self.assertFalse(os.path.exists(path))

    def test_delete_failure_maps_to_stable_code_no_raw_ntstatus(self):
        if not safe_task_write._NATIVE_AVAILABLE:
            self.skipTest("native layer unavailable")
        self.assertTrue(safe_task_write.verify_native_support())
        r = self.store.create_task("标题", "描述内容。", self.tc)
        self.assertEqual(r.outcome, "pending")
        # 注入：NtCreateFile 成功后 WriteFile 失败（触发写入后清理路径）；
        # 同时令 NtDeleteFile 返回非成功 NTSTATUS（清理失败且不抛异常）。
        with mock.patch.object(
            safe_task_write.kernel32, "WriteFile",
            lambda h, buf, n, written, ov: 0,
        ), mock.patch.object(
            safe_task_write.ntdll, "NtDeleteFile", return_value=0xC0000043
        ):
            res = self.store.approve(r.confirmation_id, self.tc)
        # 清理失败不得静默吞掉：返回脱敏稳定码，绝不回显 NTSTATUS / 路径
        self.assertEqual(res.error_code, TASK_WRITE_FAILED)
        self.assertEqual(res.task_id, r.task_id)
        # 确认记录保持 PENDING（失败关闭，未提交 APPROVED）
        cur = self.store._conn.cursor()
        row = cur.execute(
            "SELECT status FROM confirmations WHERE confirmation_id=?",
            (r.confirmation_id,),
        ).fetchone()
        self.assertEqual(row[0], "PENDING")
        # 审计仅保存稳定码：不得回显原始 NTSTATUS / 路径文本
        body = repr(res) + " " + res.error_code
        self.assertNotIn("0xC0000043", body)
        self.assertNotIn("NTSTATUS", body)
        self.assertNotIn("NtDeleteFile", body)
        # 清理失败时不能错误断言目录必空（残余 0 字节文件可能仍在该受控目录）。
        # 仅断言稳定结果，不检查目录是否为空。


if __name__ == "__main__":
    unittest.main()
