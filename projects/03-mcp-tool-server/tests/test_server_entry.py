"""P3 C 阶段：生产入口 / 配置路径不创建任务根（P0-1）；默认 notes_root 指向真实夹具（P1-1）。

注意：本文件仅验证“配置解析与 Server 构建不创建任务根”这一不变量；任务根的真实
预存在性由 `safe_task_write` 句柄层在发布时校验（缺失 → task-root-unsafe 失败关闭）。
演示 / 测试中的临时任务根预建仅作为夹具（见 test_mcp_integration.py / demo）。
"""

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

from mcp_notes.identity import write_identity_file  # noqa: E402
from mcp_notes.server import ServerConfig, TaskPublishError, build_server  # noqa: E402

_TESTS = os.path.dirname(__file__)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
from _network_block import NetworkBlockedTestCase  # noqa: E402


class ServerConfigEntryTests(NetworkBlockedTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="p3-entry-")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)
        super().tearDown()

    def _fixtures(self):
        return os.path.join(_ROOT, "evals", "fixtures", "notes-v1")

    def test_production_entry_does_not_create_task_root(self):
        # 任务根指向尚不存在的目录；生产入口 / 配置路径不得自行创建它（D-015）
        task_root = os.path.join(self._tmp, "nonexistent-tasks")
        db_path = os.path.join(self._tmp, "control.db")
        # D-3：受控身份根夹具（受控启动器设置 MCP_NOTES_IDENTITY_FILE）
        identity_dir = os.path.join(self._tmp, "identity")
        os.makedirs(identity_dir, exist_ok=True)
        identity_file = os.path.join(identity_dir, "identity.json")
        write_identity_file(identity_file, "p3-local-service")
        env = {
            "MCP_NOTES_DB_PATH": db_path,
            "MCP_NOTES_TASK_ROOT": task_root,
            "MCP_NOTES_NOTES_ROOT": self._fixtures(),
            "MCP_NOTES_IDENTITY_FILE": identity_file,
        }
        config = ServerConfig.from_env(env)
        self.assertFalse(os.path.exists(config.task_root))
        # build_server 仅基于 notes_root 建立只读索引，绝不创建任务根
        server = build_server(config)
        self.assertFalse(os.path.exists(config.task_root))
        self.assertIsNotNone(server)

    def test_default_notes_root_points_to_fixtures(self):
        # 不传 MCP_NOTES_NOTES_ROOT → 默认指向仓库 evals/fixtures/notes-v1 且真实存在；
        # 身份由受控身份文件加载（无默认主体，缺失 / 非法 → 失败关闭）
        identity_dir = os.path.join(self._tmp, "identity")
        os.makedirs(identity_dir, exist_ok=True)
        identity_file = os.path.join(identity_dir, "identity.json")
        write_identity_file(identity_file, "p3-local-service")
        config = ServerConfig.from_env({"MCP_NOTES_IDENTITY_FILE": identity_file})
        self.assertTrue(
            config.notes_root.endswith(os.path.join("evals", "fixtures", "notes-v1"))
        )
        self.assertTrue(os.path.isdir(config.notes_root))
        md_files = [n for n in os.listdir(config.notes_root) if n.endswith(".md")]
        self.assertGreaterEqual(len(md_files), 1)

    def test_invalid_identity_subject_fails_closed_at_config(self):
        # D-3：身份文件内 subject 非法（含空格）→ 加载失败关闭 → from_env 抛受控错误
        identity_dir = os.path.join(self._tmp, "identity")
        os.makedirs(identity_dir, exist_ok=True)
        identity_file = os.path.join(identity_dir, "identity.json")
        write_identity_file(identity_file, "bad subject")
        with self.assertRaises(TaskPublishError):
            ServerConfig.from_env({"MCP_NOTES_IDENTITY_FILE": identity_file})

    def test_from_env_missing_identity_fails_closed(self):
        # D-3：缺失 MCP_NOTES_IDENTITY_FILE（且缺省路径无文件）→ 失败关闭，不回退默认主体
        with self.assertRaises(TaskPublishError):
            ServerConfig.from_env({})

    def test_direct_construct_invalid_subject_fails_closed(self):
        # D-3 §5.1 / §7.2 D-21：直接构造非 RuntimeIdentity（裸 str）→ 失败关闭，
        # 不得绕过 __post_init__ 校验
        with self.assertRaises(TaskPublishError):
            ServerConfig(
                db_path="x.db", task_root="t", notes_root="n", identity="bad subject"
            )

    def test_entry_missing_subject_fails_closed_without_leak(self):
        # P0-2 入口泄露修复：缺失 MCP_NOTES_SUBJECT 时，`python -m mcp_notes.server`
        # 必须失败关闭且不泄露路径 / server.py / 堆栈；stdout 为空、stderr 仅含
        # 稳定码、非零退出。
        env = dict(os.environ)
        env.pop("MCP_NOTES_SUBJECT", None)  # 强制缺失
        env.pop("MCP_NOTES_IDENTITY_FILE", None)  # D-3：缺身份文件 → 失败关闭
        env["PYTHONPATH"] = _SRC + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-m", "mcp_notes.server"],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertEqual("", proc.stdout)
        self.assertIn("invalid-arguments", proc.stderr)
        # 禁止泄露绝对路径、源码文件名或异常堆栈
        for forbidden in ("server.py", "Traceback", 'File "', _ROOT, "TaskPublishError"):
            self.assertNotIn(forbidden, proc.stderr)
