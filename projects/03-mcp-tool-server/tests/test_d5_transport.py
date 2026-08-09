"""D-5：默认 stdio 与显式本地回环 streamable-HTTP 的离线集成测试。"""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
_TESTS = os.path.dirname(__file__)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_notes.identity import write_identity_file
from mcp_notes.server import ServerConfig
from mcp_notes.tasks import INVALID_ARGUMENTS, TaskPublishError
from _network_block import NetworkBlockedTestCase


class D5TransportTests(NetworkBlockedTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp(prefix="p3-d5-")
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.notes = os.path.join(self.tmp, "notes")
        self.tasks = os.path.join(self.tmp, "tasks")
        self.identity_dir = os.path.join(self.tmp, "identity")
        os.makedirs(self.notes)
        os.makedirs(self.tasks)
        os.makedirs(self.identity_dir)
        fixtures = os.path.join(_ROOT, "evals", "fixtures", "notes-v1")
        for name in os.listdir(fixtures):
            if name.endswith(".md"):
                shutil.copyfile(os.path.join(fixtures, name), os.path.join(self.notes, name))
        self.identity_file = os.path.join(self.identity_dir, "identity.json")
        write_identity_file(self.identity_file, "p3-local-service")

    def _env(self, port=None):
        env = dict(os.environ)
        env["PYTHONPATH"] = _SRC
        env["MCP_NOTES_DB_PATH"] = os.path.join(self.tmp, "state.sqlite")
        env["MCP_NOTES_TASK_ROOT"] = self.tasks
        env["MCP_NOTES_NOTES_ROOT"] = self.notes
        env["MCP_NOTES_IDENTITY_FILE"] = self.identity_file
        if port is not None:
            env["MCP_NOTES_TRANSPORT"] = "streamable-http"
            env["MCP_NOTES_HOST"] = "127.0.0.1"
            env["MCP_NOTES_PORT"] = str(port)
            env["NETWORK_ACCESS_BLOCKED_IN_TESTS"] = "1"
        return env

    def test_d5_default_is_stdio(self):
        config = ServerConfig.from_env(self._env())
        self.assertEqual(config.transport, "stdio")

    def test_d5_rejects_public_listener_and_bad_port(self):
        public = self._env()
        public.update({"MCP_NOTES_TRANSPORT": "streamable-http", "MCP_NOTES_HOST": "0.0.0.0"})
        with self.assertRaises(TaskPublishError) as cm:
            ServerConfig.from_env(public)
        self.assertEqual(cm.exception.code, INVALID_ARGUMENTS)
        bad_port = self._env()
        bad_port.update({"MCP_NOTES_TRANSPORT": "streamable-http", "MCP_NOTES_PORT": "70000"})
        with self.assertRaises(TaskPublishError) as cm:
            ServerConfig.from_env(bad_port)
        self.assertEqual(cm.exception.code, INVALID_ARGUMENTS)

    def test_d5_rejects_legacy_sse_and_unknown_transport(self):
        for value in ("sse", "http", ""):
            env = self._env()
            env["MCP_NOTES_TRANSPORT"] = value
            with self.assertRaises(TaskPublishError) as cm:
                ServerConfig.from_env(env)
            self.assertEqual(cm.exception.code, INVALID_ARGUMENTS)

    def test_d5_streamable_http_loopback_real_client(self):
        # 先由 OS 分配端口；之后仅连接 127.0.0.1，绝不访问外网。
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        proc = subprocess.Popen(
            [sys.executable, "-m", "mcp_notes.server"],
            cwd=_ROOT,
            env=self._env(port),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(self._stop, proc)

        async def scenario():
            url = f"http://127.0.0.1:{port}/mcp"
            last = None
            for _ in range(80):
                try:
                    async with Client(streamable_http_client(url)) as client:
                        tools = await client.list_tools()
                        self.assertEqual(sorted(t.name for t in tools.tools), ["create_task", "search_notes"])
                        self.assertNotIn("approve", [t.name for t in tools.tools])
                        result = await client.call_tool(
                            "create_task", {"title": "D5 本地回环", "description": "仅本地 streamable HTTP"}
                        )
                        data = json.loads(result.content[0].text)
                        self.assertEqual(data["status"], "pending")
                        self.assertEqual(os.listdir(self.tasks), [])
                        return
                except Exception as exc:  # server 正在启动；重试只针对受控回环端点
                    last = exc
                    await asyncio.sleep(0.05)
            self.fail(f"local loopback server did not become ready: {type(last).__name__}")

        asyncio.run(scenario())

    @staticmethod
    def _stop(proc):
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
        finally:
            # Popen owns these pipes. Closing them avoids ResourceWarning and
            # prevents local interpreter paths from appearing in test output.
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()


if __name__ == "__main__":
    unittest.main()
