"""P3 C 阶段：生产入口 / 配置路径不创建任务根（P0-1）；默认 notes_root 指向真实夹具（P1-1）。

注意：本文件仅验证“配置解析与 Server 构建不创建任务根”这一不变量；任务根的真实
预存在性由 `safe_task_write` 句柄层在发布时校验（缺失 → task-root-unsafe 失败关闭）。
演示 / 测试中的临时任务根预建仅作为夹具（见 test_mcp_integration.py / demo）。
"""

import os
import shutil
import sys
import tempfile
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

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
        env = {
            "MCP_NOTES_DB_PATH": db_path,
            "MCP_NOTES_TASK_ROOT": task_root,
            "MCP_NOTES_NOTES_ROOT": self._fixtures(),
            "MCP_NOTES_SUBJECT": "p3-local-service",
        }
        config = ServerConfig.from_env(env)
        self.assertFalse(os.path.exists(config.task_root))
        # build_server 仅基于 notes_root 建立只读索引，绝不创建任务根
        server = build_server(config)
        self.assertFalse(os.path.exists(config.task_root))
        self.assertIsNotNone(server)

    def test_default_notes_root_points_to_fixtures(self):
        # 不传 MCP_NOTES_NOTES_ROOT → 默认指向仓库 evals/fixtures/notes-v1 且真实存在；
        # subject 为必填，须显式提供（P0-2：无默认主体）
        config = ServerConfig.from_env({"MCP_NOTES_SUBJECT": "p3-local-service"})
        self.assertTrue(
            config.notes_root.endswith(os.path.join("evals", "fixtures", "notes-v1"))
        )
        self.assertTrue(os.path.isdir(config.notes_root))
        md_files = [n for n in os.listdir(config.notes_root) if n.endswith(".md")]
        self.assertGreaterEqual(len(md_files), 1)

    def test_invalid_subject_fails_closed_at_config(self):
        # D-1 配置启动失败关闭：subject 含空格等非法字符 → from_env 抛受控错误
        with self.assertRaises(TaskPublishError):
            ServerConfig.from_env({"MCP_NOTES_SUBJECT": "bad subject"})

    def test_from_env_missing_subject_fails_closed(self):
        # P0-2 ⑤：缺失 MCP_NOTES_SUBJECT 必须失败关闭（不再回退默认主体）
        with self.assertRaises(TaskPublishError):
            ServerConfig.from_env({})

    def test_direct_construct_invalid_subject_fails_closed(self):
        # P0-2 ⑥：直接构造非法 subject 不得绕过 __post_init__ 校验
        with self.assertRaises(TaskPublishError):
            ServerConfig(
                db_path="x.db", task_root="t", notes_root="n", subject="bad subject"
            )
