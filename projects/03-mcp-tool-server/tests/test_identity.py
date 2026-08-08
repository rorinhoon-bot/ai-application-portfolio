"""P3 D-3 身份模块单元测试（stdlib unittest，离线、Windows 宿主可直接跑）。

覆盖 D-3-design.md §7.2 测试矩阵：
- A 值来源单一性（P0-1）：env 永不产生值，仅可选相等性断言
- B 安全读取（P0-2）：fd/HANDLE 链、拒绝链接跟随、fstat 类型断言、限长、能力缺失
- C schema（P1-1）：严格校验
- D 注入与绑定（M1 进程模型）：生产构造器拒裸 str、防呆、单进程内嵌、多身份、分离进程
- E 稳定码唯一输出：server.main() 与受控启动器入口

全部纯标准库；任何需真实 OS 账户 / 原生凭证 / 真实 symlink 的用例标 skip 占位
（blocked-until-approved），不创建、不运行。
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from mcp_notes.identity import (  # noqa: E402
    IDENTITY_SCHEMA_VERSION,
    MAX_IDENTITY_BYTES,
    RuntimeIdentity,
    load_runtime_identity,
    write_identity_file,
)
from mcp_notes.safe_task_write import SafeWriteError, TASK_ROOT_UNSAFE  # noqa: E402
from mcp_notes.tasks import (  # noqa: E402
    INVALID_ARGUMENTS,
    TaskPublishError,
)

import mcp_notes.identity as _identity_mod  # noqa: E402


_VALID = {"version": 1, "subject": "p3-local-service", "subject_kind": "deployment-provisioned"}


def _write_doc(path, doc):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, sort_keys=True)


class IdentityModuleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="p3-id-")

    def tearDown(self):
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _ident_path(self, name="identity.json"):
        d = os.path.join(self._tmp, "identity")
        return os.path.join(d, name)

    # ------------------------------------------------------------------ #
    # A. 值来源单一性（P0-1）
    # ------------------------------------------------------------------ #
    def test_a1_missing_file_no_env_fails(self):
        # 身份文件缺失 + 无 env → 失败关闭
        path = os.path.join(self._tmp, "missing", "identity.json")
        with self.assertRaises(TaskPublishError):
            load_runtime_identity({}, identity_file_path=path)

    def test_a2_missing_file_with_valid_env_fails(self):
        # 身份文件缺失 + 有合法 env → 仍失败关闭（env 不是后备）
        path = os.path.join(self._tmp, "missing", "identity.json")
        with self.assertRaises(TaskPublishError):
            load_runtime_identity(
                {"MCP_NOTES_SUBJECT": "p3-local-service"}, identity_file_path=path
            )

    def test_a3_file_valid_no_env_loads(self):
        # 文件合法 + env 未给出 → 加载成功
        path = self._ident_path()
        write_identity_file(path, "p3-local-service")
        ident = load_runtime_identity({}, identity_file_path=path)
        self.assertIsInstance(ident, RuntimeIdentity)
        self.assertEqual(ident.subject, "p3-local-service")

    def test_a4_file_valid_env_equal_same_subject(self):
        # 文件合法 + env 给出且相等 → 加载成功，结果与 A3 逐字节相同
        path = self._ident_path()
        write_identity_file(path, "p3-local-service")
        ident_a = load_runtime_identity({}, identity_file_path=path)
        ident_b = load_runtime_identity(
            {"MCP_NOTES_SUBJECT": "p3-local-service"}, identity_file_path=path
        )
        self.assertEqual(ident_a.subject, ident_b.subject)

    def test_a5_file_valid_env_unequal_fails(self):
        # 文件合法 + env 给出但不等 → 失败关闭
        path = self._ident_path()
        write_identity_file(path, "p3-local-service")
        with self.assertRaises(TaskPublishError):
            load_runtime_identity(
                {"MCP_NOTES_SUBJECT": "other-subject"}, identity_file_path=path
            )

    def test_a6_equivalence_invariant(self):
        # 等价不变量：删除 env 后重新加载，结果不变
        path = self._ident_path()
        write_identity_file(path, "p3-local-service")
        with_env = load_runtime_identity(
            {"MCP_NOTES_SUBJECT": "p3-local-service"}, identity_file_path=path
        )
        without_env = load_runtime_identity({}, identity_file_path=path)
        self.assertEqual(with_env.subject, without_env.subject)

    # ------------------------------------------------------------------ #
    # B. 安全读取（P0-2）
    # ------------------------------------------------------------------ #
    def test_b7_bad_name_component_fails(self):
        # <name> 不符白名单（.. / 非 .json 后缀 / 含 \x00）→ 失败关闭
        for bad in ("..", "identity.txt", "a" * 64 + ".json", "na\x00me.json"):
            path = os.path.join(self._tmp, "identity", bad)
            with self.subTest(name=bad):
                with self.assertRaises(TaskPublishError):
                    load_runtime_identity({}, identity_file_path=path)

    def test_b8_capability_missing_fails(self):
        # 平台能力缺失 → 失败关闭，绝无字符串路径读取回退
        if sys.platform == "win32":
            target = "mcp_notes.identity.open_task_root"
        else:
            target = "mcp_notes.identity._posix._posix_supported"
        with mock.patch(target, side_effect=SafeWriteError(TASK_ROOT_UNSAFE) if sys.platform == "win32" else lambda: False):
            path = self._ident_path()
            write_identity_file(path, "p3-local-service")
            with self.assertRaises(TaskPublishError):
                load_runtime_identity({}, identity_file_path=path)

    def test_b9_root_open_fails_maps_to_invalid(self):
        # 身份根链打开失败（D-2 原语抛 SafeWriteError）→ 映射 invalid-arguments
        if sys.platform == "win32":
            target = "mcp_notes.identity.open_task_root"
        else:
            target = "mcp_notes.identity._posix._open_root"
        with mock.patch(target, side_effect=SafeWriteError(TASK_ROOT_UNSAFE)):
            path = self._ident_path()
            write_identity_file(path, "p3-local-service")
            with self.assertRaises(TaskPublishError):
                load_runtime_identity({}, identity_file_path=path)

    def test_b10_non_regular_file_fails(self):
        # 身份文件非普通文件（fstat 返回非 S_ISREG）→ 失败关闭
        path = self._ident_path()
        write_identity_file(path, "p3-local-service")
        with mock.patch.object(stat, "S_ISREG", return_value=False):
            with self.assertRaises(TaskPublishError):
                load_runtime_identity({}, identity_file_path=path)

    def test_b11_toctou_fstat_on_fd_not_path(self):
        # 类型断言基于 fstat(fd)（已打开 fd，非路径）；记录 fd 参数
        path = self._ident_path()
        write_identity_file(path, "p3-local-service")
        seen = []
        real_fstat = os.fstat

        def fake_fstat(fd, *a, **k):
            seen.append(fd)
            return real_fstat(fd)

        with mock.patch.object(os, "fstat", side_effect=fake_fstat):
            ident = load_runtime_identity({}, identity_file_path=path)
        self.assertEqual(ident.subject, "p3-local-service")
        # 类型断言针对已打开的 int fd（不是路径字符串）
        self.assertTrue(seen, "os.fstat 必须被调用")
        self.assertTrue(all(isinstance(x, int) for x in seen))

    def test_b12_read_io_fails(self):
        # 读取 IO 失败 → 失败关闭，稳定码，无原始 OSError 泄露
        path = self._ident_path()
        write_identity_file(path, "p3-local-service")
        with mock.patch.object(os, "read", side_effect=OSError("read failed")):
            with self.assertRaises(TaskPublishError):
                load_runtime_identity({}, identity_file_path=path)

    def test_b13_size_boundary(self):
        # 真实边界：恰好 4096 字节（合法 JSON + 空白填充）通过；4097 字节 → 失败关闭
        valid_text = json.dumps(_VALID, ensure_ascii=False, sort_keys=True)
        valid_len = len(valid_text.encode("utf-8"))

        # 4096 字节：合法 JSON + 尾随空格填充到恰好 4096（JSON 允许尾随空白）
        path_4096 = os.path.join(self._tmp, "ident-4096.json")
        assert valid_len < MAX_IDENTITY_BYTES, "合法 JSON 必须小于 4096 字节才能填充"
        text_4096 = valid_text + " " * (MAX_IDENTITY_BYTES - valid_len)
        with open(path_4096, "w", encoding="utf-8") as f:
            f.write(text_4096)
        self.assertEqual(len(text_4096.encode("utf-8")), MAX_IDENTITY_BYTES)
        ident = load_runtime_identity({}, identity_file_path=path_4096)
        self.assertEqual(ident.subject, "p3-local-service")

        # 4097 字节：超过上限 → 失败关闭
        path_4097 = os.path.join(self._tmp, "ident-4097.json")
        text_4097 = valid_text + " " * (MAX_IDENTITY_BYTES + 1 - valid_len)
        with open(path_4097, "w", encoding="utf-8") as f:
            f.write(text_4097)
        self.assertEqual(len(text_4097.encode("utf-8")), MAX_IDENTITY_BYTES + 1)
        with self.assertRaises(TaskPublishError):
            load_runtime_identity({}, identity_file_path=path_4097)

    def test_b_handle_leak_on_open_osfhandle_failure(self):
        # Windows（win32）：msvcrt.open_osfhandle(fh) 失败时必须显式关闭已打开的 fh，
        # HANDLE 不得泄漏；边界仍映射为稳定 invalid-arguments
        if sys.platform != "win32":
            self.skipTest("Windows HANDLE 路径仅在 win32 验证")
        import msvcrt
        import mcp_notes.safe_task_write as _stw

        path = self._ident_path()
        write_identity_file(path, "p3-local-service")
        FAKE_PARENT = 0xAAAA
        FAKE_FH = 0xBBBB
        close_mock = mock.MagicMock()
        # _nt_open / _close 为 identity 内 win32 分支局部导入，需 patch 原模块
        with mock.patch.object(_identity_mod, "open_task_root", return_value=[FAKE_PARENT]), \
             mock.patch.object(_stw, "_nt_open", return_value=FAKE_FH), \
             mock.patch.object(_stw, "_close", close_mock), \
             mock.patch.object(msvcrt, "open_osfhandle", side_effect=OSError("no fd")):
            with self.assertRaises(TaskPublishError):
                load_runtime_identity({}, identity_file_path=path)
        # 泄漏的 fh 必须被恰好关闭一次（open_task_root 返回的父句柄也会被关闭，但不含 FAKE_FH）
        closed = [c.args[0] for c in close_mock.call_args_list]
        self.assertEqual(closed.count(FAKE_FH), 1)

    @unittest.skip(
        "blocked-until-approved: 真实 symlink/junction 身份根与身份文件夹具"
        "（D-3 §9-5，与 D2-L1..L4 同规格）；不创建、不运行"
    )
    def test_b14_real_symlink_junction(self):
        raise NotImplementedError("真实链接夹具待用户单独批准")

    # ------------------------------------------------------------------ #
    # C. schema（P1-1）
    # ------------------------------------------------------------------ #
    def test_c15_top_level_not_object_fails(self):
        path = self._ident_path()
        _write_doc(path, ["not", "an", "object"])
        with self.assertRaises(TaskPublishError):
            load_runtime_identity({}, identity_file_path=path)

    def test_c16_version_invalid_fails(self):
        for ver in (None, "1", True, 2):
            with self.subTest(version=ver):
                path = self._ident_path()
                doc = {"version": ver, "subject": "s", "subject_kind": "deployment-provisioned"}
                _write_doc(path, doc)
                with self.assertRaises(TaskPublishError):
                    load_runtime_identity({}, identity_file_path=path)

    def test_c17_subject_invalid_fails(self):
        # D-3：非法 subject 字符串覆盖迁移到「身份文件内 subject 非法 → 加载失败关闭」
        cases = {
            "missing": {"version": 1, "subject_kind": "deployment-provisioned"},
            "not_str": {"version": 1, "subject": 123, "subject_kind": "deployment-provisioned"},
            "empty": {"version": 1, "subject": "", "subject_kind": "deployment-provisioned"},
            "space": {"version": 1, "subject": "bad subject", "subject_kind": "deployment-provisioned"},
            "cjk": {"version": 1, "subject": "本地服务", "subject_kind": "deployment-provisioned"},
            "too_long": {"version": 1, "subject": "a" * 129, "subject_kind": "deployment-provisioned"},
            "ok_128": None,  # 占位：128 字符合法的正向用例见 test_c17b
        }
        for label, doc in cases.items():
            if doc is None:
                continue
            with self.subTest(label=label):
                path = self._ident_path()
                _write_doc(path, doc)
                with self.assertRaises(TaskPublishError):
                    load_runtime_identity({}, identity_file_path=path)

    def test_c17b_subject_128_chars_ok(self):
        # 128 字符白名单边界合法 → 通过
        subject = "a" * 128
        path = self._ident_path()
        write_identity_file(path, subject)
        ident = load_runtime_identity({}, identity_file_path=path)
        self.assertEqual(ident.subject, subject)

    def test_c18_subject_kind_invalid_fails(self):
        for kind in (None, 1, "other", "deployment"):
            with self.subTest(kind=kind):
                path = self._ident_path()
                doc = {"version": 1, "subject": "s", "subject_kind": kind}
                _write_doc(path, doc)
                with self.assertRaises(TaskPublishError):
                    load_runtime_identity({}, identity_file_path=path)

    def test_c19_unknown_key_rejected(self):
        path = self._ident_path()
        doc = dict(_VALID)
        doc["extra"] = "ignored"
        _write_doc(path, doc)
        with self.assertRaises(TaskPublishError):
            load_runtime_identity({}, identity_file_path=path)

    def test_c20_non_utf8_or_bom_or_bad_json_fails(self):
        import shutil

        # 非 UTF-8 字节
        p1 = self._ident_path()
        os.makedirs(os.path.dirname(p1), exist_ok=True)
        with open(p1, "wb") as f:
            f.write(b"\xff\xfe" + b'{"version":1}')
        with self.assertRaises(TaskPublishError):
            load_runtime_identity({}, identity_file_path=p1)
        # 带 BOM 的 UTF-8
        p2 = self._ident_path("bom.json")
        with open(p2, "wb") as f:
            f.write(b"\xef\xbb\xbf" + json.dumps(_VALID).encode("utf-8"))
        with self.assertRaises(TaskPublishError):
            load_runtime_identity({}, identity_file_path=p2)
        # JSON 语法错误
        p3 = self._ident_path("bad.json")
        with open(p3, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        with self.assertRaises(TaskPublishError):
            load_runtime_identity({}, identity_file_path=p3)
        shutil.rmtree(os.path.dirname(p1), ignore_errors=True)

    # ------------------------------------------------------------------ #
    # D. 注入与绑定（M1 进程模型）
    # ------------------------------------------------------------------ #
    def test_d21_host_rejects_bare_str(self):
        # 生产构造器拒绝裸 str（非 RuntimeIdentity）→ invalid-arguments
        from mcp_notes.host import TrustedHostController

        with self.assertRaises(TaskPublishError):
            TrustedHostController("x.db", "tasks", "bare-subject")

    def test_d22_public_construction_fails(self):
        # 防呆（非安全边界）：公共 API 直接传 str 构造 RuntimeIdentity 失败
        with self.assertRaises(TypeError):
            RuntimeIdentity(subject="p3-local-service")

    def test_d23_single_process_embedded_injection(self):
        # 单进程内嵌（M1 特例）：一次 bootstrap 注入 Server 与 Host → approve 全链路通过
        from mcp_notes.host import TrustedHostController
        from mcp_notes.server import ServerConfig, build_server
        from mcp_notes.tasks import TasksStore, TrustedContext

        path = self._ident_path()
        write_identity_file(path, "p3-local-service")
        ident = load_runtime_identity({}, identity_file_path=path)

        db_path = os.path.join(self._tmp, "control.db")
        task_root = os.path.join(self._tmp, "tasks")
        notes_root = os.path.join(_ROOT, "evals", "fixtures", "notes-v1")
        os.makedirs(task_root, exist_ok=True)

        config = ServerConfig(
            db_path=db_path, task_root=task_root, notes_root=notes_root, identity=ident
        )
        build_server(config)  # 构造不报错即证明 identity 注入生效
        store = TasksStore(db_path, task_root)
        try:
            res = store.create_task("嵌入任务", "描述", TrustedContext(ident.subject, "a" * 64))
            host = TrustedHostController(db_path, task_root, ident)
            try:
                ap = host.approve(res.confirmation_id)
                self.assertEqual(ap.outcome, "created")
            finally:
                host.close()
            self.assertTrue(
                os.path.exists(os.path.join(task_root, res.task_id + ".json"))
            )
        finally:
            store.close()

    def test_d24_multi_identity_mismatch(self):
        # 多身份（M1 常规路径）：两次独立真实加载、两个受控身份根；身份 B 的 Host
        # 消费身份 A 创建的 confirmation → confirmation-identity-mismatch、不写文件
        from mcp_notes.host import TrustedHostController
        from mcp_notes.tasks import (
            CONFIRMATION_IDENTITY_MISMATCH,
            TasksStore,
            TrustedContext,
        )

        a_path = os.path.join(self._tmp, "identity-a", "identity.json")
        b_path = os.path.join(self._tmp, "identity-b", "identity.json")
        write_identity_file(a_path, "service-A")
        write_identity_file(b_path, "service-B")

        # 两次独立真实加载（模拟两个进程各自加载；不绕过加载器）
        ident_a = load_runtime_identity({}, identity_file_path=a_path)
        ident_b = load_runtime_identity({}, identity_file_path=b_path)
        self.assertNotEqual(ident_a.subject, ident_b.subject)

        db_path = os.path.join(self._tmp, "control.db")
        task_root = os.path.join(self._tmp, "tasks")
        os.makedirs(task_root, exist_ok=True)
        store = TasksStore(db_path, task_root)
        try:
            res = store.create_task("错绑", "描述", TrustedContext(ident_a.subject, "c" * 64))
            host_b = TrustedHostController(db_path, task_root, ident_b)
            try:
                ap = host_b.approve(res.confirmation_id)
                self.assertEqual(ap.error_code, CONFIRMATION_IDENTITY_MISMATCH)
            finally:
                host_b.close()
            self.assertFalse(
                os.path.exists(os.path.join(task_root, res.task_id + ".json"))
            )
        finally:
            store.close()

    def test_d25_separate_process_same_file_consistent(self):
        # 分离进程（M1）：两次真实加载指向同一受控身份文件 → 同 subject（部署级保证）
        path = self._ident_path()
        write_identity_file(path, "p3-local-service")
        ident1 = load_runtime_identity({}, identity_file_path=path)
        ident2 = load_runtime_identity({}, identity_file_path=path)
        self.assertEqual(ident1.subject, ident2.subject)

    def test_d26_correlation_id_regression(self):
        # correlation_id 不可由客户端提供/覆盖；仍为 64-hex
        from mcp_notes.server import _derive_correlation_id
        from mcp_notes.tasks import _valid_correlation_id

        cid = _derive_correlation_id("Title", "Desc")
        self.assertTrue(_valid_correlation_id(cid))
        self.assertEqual(len(cid), 64)
        self.assertEqual(cid, _derive_correlation_id("Title", "Desc"))

    # ------------------------------------------------------------------ #
    # E. 稳定码唯一输出（P1-3 前提；可验收入口）
    # ------------------------------------------------------------------ #
    def _run_subprocess(self, env_extra, entry_module):
        env = dict(os.environ)
        env.pop("MCP_NOTES_SUBJECT", None)
        env.pop("MCP_NOTES_IDENTITY_FILE", None)
        env["PYTHONPATH"] = _SRC + os.pathsep + env.get("PYTHONPATH", "")
        env["P3_SRC"] = _SRC
        env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-m", entry_module],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def _assert_clean_fail(self, proc):
        self.assertNotEqual(0, proc.returncode)
        self.assertEqual("", proc.stdout)
        self.assertIn("invalid-arguments", proc.stderr)
        for forbidden in ("Traceback", 'File "', _ROOT, "TaskPublishError"):
            self.assertNotIn(forbidden, proc.stderr)

    def test_e27_server_main_bootstrap_failure(self):
        # server.main() 入口：身份文件缺失 → 失败关闭、稳定码、无泄露
        missing = os.path.join(self._tmp, "nope", "identity.json")
        proc = self._run_subprocess(
            {"MCP_NOTES_IDENTITY_FILE": missing}, "mcp_notes.server"
        )
        self._assert_clean_fail(proc)

    def test_e28_controlled_launcher_bootstrap_failure(self):
        # 受控启动器入口（Host 侧）：三类确定性破坏身份文件 → 同等失败关闭、无泄露
        launcher = os.path.join(os.path.dirname(__file__), "_identity_bootstrap_launcher.py")

        # (a) 缺失文件
        missing = os.path.join(self._tmp, "nope", "identity.json")
        # (b) 非法 schema（version: 2）
        bad_schema = os.path.join(self._tmp, "bad-schema", "identity.json")
        os.makedirs(os.path.dirname(bad_schema), exist_ok=True)
        _write_doc(bad_schema, {"version": 2, "subject": "s", "subject_kind": "deployment-provisioned"})
        # (c) 非普通文件（指向目录）
        directory = os.path.join(self._tmp, "dir-as-file")
        os.makedirs(directory, exist_ok=True)

        for label, target in (("missing", missing), ("bad_schema", bad_schema), ("directory", directory)):
            with self.subTest(case=label):
                env = dict(os.environ)
                env.pop("MCP_NOTES_SUBJECT", None)
                env.pop("MCP_NOTES_IDENTITY_FILE", None)
                env["PYTHONPATH"] = _SRC + os.pathsep + env.get("PYTHONPATH", "")
                env["P3_SRC"] = _SRC
                env["MCP_NOTES_IDENTITY_FILE"] = target
                proc = subprocess.run(
                    [sys.executable, launcher],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self._assert_clean_fail(proc)


if __name__ == "__main__":
    unittest.main()
