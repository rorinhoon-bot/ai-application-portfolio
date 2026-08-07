"""P3 C 阶段 stdio 集成测试（stdlib unittest，继承默认网络阻断底座）。

覆盖（真实本地 stdio MCP Server/Client，虚构夹具，离线）：
- list_tools 仅暴露 search_notes 与 create_task；approve/reject/cancel 绝不暴露
  （受控确认在 Tool 外由本地可信 Host 完成）。
- search_notes 成功（关键词命中）与失败（非法关键词 → invalid-arguments）。
- create_task 成功返回 PENDING（task_id + confirmation_id，不写文件）与失败
  （空标题 → invalid-arguments）。
- Resource notes://service-info 返回静态只读服务描述，工具清单不含受控确认动作。
- Host 控制器（Tool 外）批准 / 拒绝 / 取消 / 身份错绑 / 未知确认，由本地可信边界
  驱动既有 tasks.py 核心；身份绑定强制、错绑被拒、不写文件于负向终态。

所有用例继承 NetworkBlockedTestCase：测试期间默认阻断网络（socket 层 monkeypatch），
stdio 子进程经管道通信、不经过网络；不写 URL / 请求头 / 真实笔记。
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
_FIXTURES = os.path.join(_ROOT, "evals", "fixtures", "notes-v1")

from mcp.client import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

from mcp_notes.host import TrustedHostController  # noqa: E402
from mcp_notes.server import _derive_correlation_id  # noqa: E402
from mcp_notes.tasks import (  # noqa: E402
    CONFIRMATION_IDENTITY_MISMATCH,
    CONFIRMATION_REQUIRED,
    TaskPublishError,
    TasksStore,
    TrustedContext,
    _valid_correlation_id,
)

_TESTS = os.path.dirname(__file__)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
from _network_block import NetworkBlockedTestCase  # noqa: E402


class StdioMCPIntegrationTests(NetworkBlockedTestCase):
    """真实 stdio 子进程 MCP Server/Client 集成测试。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="p3-it-")
        self._notes = os.path.join(self._tmp, "notes")
        self._tasks = os.path.join(self._tmp, "tasks")
        self._db = os.path.join(self._tmp, "control.db")
        os.makedirs(self._notes, exist_ok=True)
        os.makedirs(self._tasks, exist_ok=True)
        if os.path.isdir(_FIXTURES):
            for name in os.listdir(_FIXTURES):
                if name.endswith(".md"):
                    shutil.copyfile(
                        os.path.join(_FIXTURES, name),
                        os.path.join(self._notes, name),
                    )
        env = dict(os.environ)
        env["PYTHONPATH"] = _SRC
        env["MCP_NOTES_DB_PATH"] = self._db
        env["MCP_NOTES_TASK_ROOT"] = self._tasks
        env["MCP_NOTES_NOTES_ROOT"] = self._notes
        env["MCP_NOTES_SUBJECT"] = "p3-local-service"
        # P0-5：为 Server 子进程启用外部网络阻断（仅测试环境开关）；父进程已由
        # NetworkBlockedTestCase 阻断。stdio Tool / Resource 仍须正常工作。
        env["NETWORK_ACCESS_BLOCKED_IN_TESTS"] = "1"
        self._env = env

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)
        super().tearDown()

    def _params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_notes.server"],
            env=self._env,
            cwd=_ROOT,
        )

    # ------------------------------------------------------------------ #
    def test_list_tools_excludes_confirmation_actions(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                tools = await c.list_tools()
                names = sorted(t.name for t in tools.tools)
                self.assertEqual(names, ["create_task", "search_notes"])
                # 受控确认动作绝不暴露为 Tool
                self.assertNotIn("approve", names)
                self.assertNotIn("reject", names)
                self.assertNotIn("cancel", names)

        asyncio.run(scenario())

    def test_search_notes_success(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                r = await c.call_tool("search_notes", {"keyword": "检索"})
                data = json.loads(r.content[0].text)
                self.assertEqual(data["status"], "ok")
                self.assertGreaterEqual(data["total_matched"], 1)
                self.assertIn("hits", data)
                for hit in data["hits"]:
                    # 结果脱敏：仅稳定字段，无绝对路径 / 正文
                    self.assertIn("note_id", hit)
                    self.assertIn("title", hit)
                    self.assertIn("excerpt", hit)
                    self.assertNotIn("relative_path", hit)

        asyncio.run(scenario())

    def test_search_notes_invalid_keyword(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                r = await c.call_tool("search_notes", {"keyword": ".."})
                data = json.loads(r.content[0].text)
                self.assertEqual(data["status"], "error")
                self.assertEqual(data["error_code"], "invalid-arguments")

        asyncio.run(scenario())

    def test_create_task_pending(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                r = await c.call_tool(
                    "create_task",
                    {"title": "复习任务", "description": "每天复习一小时"},
                )
                data = json.loads(r.content[0].text)
                self.assertEqual(data["status"], "pending")
                self.assertTrue(data["task_id"].startswith("task-"))
                self.assertTrue(data["confirmation_id"].startswith("conf-"))
                # PENDING 阶段不写任务文件
                self.assertFalse(
                    os.path.exists(os.path.join(self._tasks, data["task_id"] + ".json"))
                )

        asyncio.run(scenario())

    def test_create_task_invalid_title(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                r = await c.call_tool("create_task", {"title": "", "description": "x"})
                data = json.loads(r.content[0].text)
                self.assertEqual(data["status"], "error")
                self.assertEqual(data["error_code"], "invalid-arguments")

        asyncio.run(scenario())

    def test_resource_service_info(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                info = await c.read_resource("notes://service-info")
                # ReadResourceResult 使用 .contents（而非 .content）
                text = info.contents[0].text
                data = json.loads(text)
                self.assertEqual(data["transport"], "stdio")
                self.assertEqual(data["tools"], ["search_notes", "create_task"])
                self.assertIn("approve/reject/cancel", data["tools_note"])
                self.assertIn("TrustedContext", data["identity"])

        asyncio.run(scenario())

    # ------------------------------------------------------------------ #
    # P0-2：Tool 参数必须返回稳定 invalid-arguments，绝不回显 Pydantic 原始异常 /
    # 类型细节 / URL；不得静默忽略未知字段
    # ------------------------------------------------------------------ #
    def _assert_clean_invalid(self, payload: dict) -> None:
        self.assertEqual(payload.get("status"), "error")
        self.assertEqual(payload.get("error_code"), "invalid-arguments")
        # 不得泄露 Pydantic 类型细节 / 文档 URL / 堆栈
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("pydantic", text.lower())
        self.assertNotIn("https://errors.pydantic", text)
        self.assertNotIn("ValidationError", text)
        self.assertNotIn("Traceback", text)

    def test_search_notes_non_string_rejected(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                r = await c.call_tool("search_notes", {"keyword": 123})
                self._assert_clean_invalid(json.loads(r.content[0].text))

        asyncio.run(scenario())

    def test_create_task_non_string_rejected(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                r = await c.call_tool("create_task", {"title": 456, "description": "x"})
                self._assert_clean_invalid(json.loads(r.content[0].text))

        asyncio.run(scenario())

    def test_create_task_unknown_field_rejected(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                # 未知字段 extra 不得静默忽略，必须拒绝
                r = await c.call_tool(
                    "create_task",
                    {"title": "复习任务", "description": "每天复习一小时", "extra": "evil"},
                )
                self._assert_clean_invalid(json.loads(r.content[0].text))

        asyncio.run(scenario())

    def test_create_task_missing_field_rejected(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                # 缺失 description（必填）
                r = await c.call_tool("create_task", {"title": "复习任务"})
                self._assert_clean_invalid(json.loads(r.content[0].text))

        asyncio.run(scenario())

    # ------------------------------------------------------------------ #
    # P0-3：create_task 重试必须保持幂等（相同规范化请求 → 相同 task_id /
    # confirmation_id，不产生第二条意图；不同内容 → 独立意图）
    # ------------------------------------------------------------------ #
    def test_create_task_idempotent_replay_same_id(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                a = await c.call_tool(
                    "create_task",
                    {"title": "复习任务", "description": "每天复习一小时"},
                )
                b = await c.call_tool(
                    "create_task",
                    {"title": "复习任务", "description": "每天复习一小时"},
                )
                da = json.loads(a.content[0].text)
                db = json.loads(b.content[0].text)
                self.assertEqual(da["status"], "pending")
                self.assertEqual(db["status"], "pending")
                # 相同规范化请求 → 相同 task_id / confirmation_id
                self.assertEqual(da["task_id"], db["task_id"])
                self.assertEqual(da["confirmation_id"], db["confirmation_id"])

        asyncio.run(scenario())

    def test_create_task_different_content_independent(self):
        async def scenario():
            async with Client(stdio_client(self._params())) as c:
                a = await c.call_tool(
                    "create_task",
                    {"title": "复习任务A", "description": "每天复习一小时"},
                )
                b = await c.call_tool(
                    "create_task",
                    {"title": "复习任务B", "description": "每周复习两小时"},
                )
                da = json.loads(a.content[0].text)
                db = json.loads(b.content[0].text)
                self.assertEqual(da["status"], "pending")
                self.assertEqual(db["status"], "pending")
                # 不同内容 → 独立意图（不同 task_id / confirmation_id）
                self.assertNotEqual(da["task_id"], db["task_id"])
                self.assertNotEqual(da["confirmation_id"], db["confirmation_id"])

        asyncio.run(scenario())

    # ------------------------------------------------------------------ #
    # P0-5：Server 子进程（由 NETWORK_ACCESS_BLOCKED_IN_TESTS 触发）必须阻断外部
    # 网络；loopback / unix 套接字仍可用；stdio Tool / Resource 正常工作见上方用例
    # ------------------------------------------------------------------ #
    def _run_block_probe(self, snippet: str) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONPATH"] = _SRC
        env["NETWORK_ACCESS_BLOCKED_IN_TESTS"] = "1"
        return subprocess.run(
            [sys.executable, "-c", snippet],
            env=env,
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_subprocess_blocks_external_network(self):
        # 与 Server 子进程完全相同的开关：env 置位 → 安装阻断 → 外部 connect 被拒
        snippet = (
            "import os;"
            "os.environ['NETWORK_ACCESS_BLOCKED_IN_TESTS']='1';"
            "from mcp_notes._network_block import maybe_install_network_block;"
            "maybe_install_network_block();"
            "import socket;"
            "socket.create_connection(('93.184.216.34', 80))"
        )
        proc = self._run_block_probe(snippet)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("NETWORK_ACCESS_BLOCKED_IN_TESTS", proc.stderr)

    def test_subprocess_allows_loopback(self):
        # 回环连接不得被阻断（socket.connect 对 127.0.0.1 应得到连接拒绝 OSError，
        # 而非 NETWORK 阻断 RuntimeError；注意 socket.create_connection 整体被阻断，
        # 故此处直接用 socket.connect 验证 loopback 白名单）。
        snippet = (
            "import os\n"
            "os.environ['NETWORK_ACCESS_BLOCKED_IN_TESTS']='1'\n"
            "from mcp_notes._network_block import maybe_install_network_block\n"
            "maybe_install_network_block()\n"
            "import socket\n"
            "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "try:\n"
            "    s.connect(('127.0.0.1', 9))\n"
            "    print('UNEXPECTED_CONNECT')\n"
            "except OSError as e:\n"
            "    print('OK_LOOPBACK_OSERROR', type(e).__name__)\n"
            "except RuntimeError as e:\n"
            "    print('BLOCKED', e)\n"
            "finally:\n"
            "    s.close()\n"
        )
        proc = self._run_block_probe(snippet)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("OK_LOOPBACK_OSERROR", proc.stdout)
        self.assertNotIn("BLOCKED", proc.stdout)


    def test_derived_correlation_id_format(self):
        # D-1：correlation_id 必须是服务端按 NFKC 派生的 64 位小写十六进制（无前缀）
        cid = _derive_correlation_id("Title", "Description")
        self.assertTrue(_valid_correlation_id(cid))
        self.assertEqual(len(cid), 64)
        # 相同规范化内容重放 → 相同 correlation_id（P0-3 幂等）
        self.assertEqual(cid, _derive_correlation_id("Title", "Description"))
        # 不同内容 → 不同 correlation_id → 独立意图
        self.assertNotEqual(cid, _derive_correlation_id("Title", "Other"))


class HostControllerTests(NetworkBlockedTestCase):
    """本地可信 Host 控制器（Tool 外批准 / 拒绝 / 取消）集成测试。"""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="p3-host-")
        self._tasks = os.path.join(self._tmp, "tasks")
        self._db = os.path.join(self._tmp, "control.db")
        os.makedirs(self._tasks, exist_ok=True)
        self._subject = "p3-local-service"
        self._store = TasksStore(self._db, self._tasks)
        self._host = TrustedHostController(self._db, self._tasks, self._subject)

    def tearDown(self):
        try:
            self._host.close()
        finally:
            try:
                self._store.close()
            finally:
                shutil.rmtree(self._tmp, ignore_errors=True)
                super().tearDown()

    def _create(self, title="复习任务", desc="每天复习一小时"):
        ctx = TrustedContext(self._subject, "c" * 64)
        res = self._store.create_task(title, desc, ctx)
        self.assertEqual(res.outcome, "pending")
        return res

    def test_approve_publishes_file(self):
        res = self._create()
        ap = self._host.approve(res.confirmation_id)
        self.assertEqual(ap.outcome, "created")
        self.assertTrue(
            os.path.exists(os.path.join(self._tasks, res.task_id + ".json"))
        )

    def test_reject_terminal(self):
        res = self._create()
        rj = self._host.reject(res.confirmation_id)
        self.assertEqual(rj.outcome, "rejected")
        # 负向终态不发布任务文件
        self.assertFalse(
            os.path.exists(os.path.join(self._tasks, res.task_id + ".json"))
        )

    def test_cancel_terminal(self):
        res = self._create()
        cx = self._host.cancel(res.confirmation_id)
        self.assertEqual(cx.outcome, "cancelled")
        self.assertFalse(
            os.path.exists(os.path.join(self._tasks, res.task_id + ".json"))
        )

    def test_identity_mismatch_rejected(self):
        # 记录由 service-B 创建；service-A 的 Host 批准应被身份绑定拒绝
        # （P0-4：身份绑定的 subject 来自 Host 受控配置，绝不取用记录中的 subject）
        store_b = TasksStore(self._db, self._tasks)
        res = store_b.create_task(
            "错绑标题", "错绑描述", TrustedContext("service-B", "c" * 64)
        )
        store_b.close()
        self.assertEqual(res.outcome, "pending")
        host_a = TrustedHostController(self._db, self._tasks, "service-A")
        ap = host_a.approve(res.confirmation_id)
        self.assertEqual(ap.error_code, CONFIRMATION_IDENTITY_MISMATCH)
        self.assertFalse(
            os.path.exists(os.path.join(self._tasks, res.task_id + ".json"))
        )
        host_a.close()

    def test_identity_mismatch_reject_and_cancel(self):
        # service-A 的 Host 对 service-B 记录 reject / cancel 同样 identity-mismatch
        store_b = TasksStore(self._db, self._tasks)
        res = store_b.create_task(
            "错绑标题2", "错绑描述2", TrustedContext("service-B", "d" * 64)
        )
        store_b.close()
        self.assertEqual(res.outcome, "pending")
        host_a = TrustedHostController(self._db, self._tasks, "service-A")
        rj = host_a.reject(res.confirmation_id)
        self.assertEqual(rj.error_code, CONFIRMATION_IDENTITY_MISMATCH)
        cx = host_a.cancel(res.confirmation_id)
        self.assertEqual(cx.error_code, CONFIRMATION_IDENTITY_MISMATCH)
        self.assertFalse(
            os.path.exists(os.path.join(self._tasks, res.task_id + ".json"))
        )
        host_a.close()

    def test_unknown_confirmation_required(self):
        ap = self._host.approve("conf-0000000000000000")
        self.assertEqual(ap.outcome, "error")
        self.assertEqual(ap.error_code, CONFIRMATION_REQUIRED)

    def test_host_invalid_subject_fails_closed(self):
        # D-1：Host 配置 subject 非法（含空格）→ 构造即失败关闭
        with self.assertRaises(TaskPublishError):
            TrustedHostController(self._db, self._tasks, "bad subject")

    def test_host_rejects_corrupted_persisted_correlation_id(self):
        # P0-1 ④：Host 取回的 correlation_id 若损坏/旧格式，必须失败关闭，
        # 不写任务文件、不泄露原始值。
        res = self._create()  # 合法 correlation_id（"c" * 64）
        # 直接篡改持久化记录中的 correlation_id 为旧格式 "c-1"
        cur = self._store._conn.cursor()
        cur.execute(
            "UPDATE confirmations SET correlation_id=? WHERE confirmation_id=?",
            ("c-1", res.confirmation_id),
        )
        self._store._conn.commit()
        ap = self._host.approve(res.confirmation_id)
        # 失败关闭：返回错误，绝不写任务文件
        self.assertEqual(ap.outcome, "error")
        self.assertFalse(
            os.path.exists(os.path.join(self._tasks, res.task_id + ".json"))
        )


if __name__ == "__main__":
    unittest.main()
