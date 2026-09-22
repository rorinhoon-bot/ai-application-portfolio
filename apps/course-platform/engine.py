"""Replaceable engine port and the fixed offline subprocess implementation."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Protocol

from domain import APP, REPO, AppError, decode, require, safe_path


class Engine(Protocol):
    def call(self, operation: str, task_root: Path, payload: dict) -> dict: ...


class OfflineEngine:
    worker_script = 'engine_worker.py'
    def __init__(self, timeout=120):
        self.timeout = timeout
        self.python = REPO / "projects/02-agent-research-workflow/.venv/Scripts/python.exe"

    def call(self, operation, task_root, payload):
        require(self.python.is_file(), "ENGINE_UNAVAILABLE")
        safe_path(task_root, directory=True).mkdir(parents=True, exist_ok=True)
        env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH") if k in os.environ}
        env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", LANGSMITH_TRACING="false",
                   LANGCHAIN_TRACING_V2="false", LANGGRAPH_STRICT_MSGPACK="true")
        # Bounded post-read from a tool-owned file, not unbounded PIPE accumulation.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen([str(self.python), "-B", str(APP / self.worker_script),
                                        "--task-root", str(task_root)], stdin=subprocess.PIPE,
                                       stdout=output, stderr=subprocess.DEVNULL, cwd=APP, env=env)
            try:
                process.communicate(json.dumps({"operation": operation, **payload}, ensure_ascii=False).encode(), timeout=self.timeout)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                process.kill()
                process.wait()
                raise AppError("ENGINE_TIMEOUT") from None
            output.seek(0)
            raw = output.read(2 * 1024 * 1024 + 1)
        require(len(raw) <= 2 * 1024 * 1024, "ENGINE_FAILED")
        try:
            response = decode(raw)
        except AppError:
            raise AppError("ENGINE_FAILED") from None
        require(process.returncode == 0 and type(response) is dict and "error" not in response, "ENGINE_FAILED")
        return response


class FrozenEngine(OfflineEngine):
    worker_script = 'frozen_worker.py'

    def __init__(self, timeout=240):
        super().__init__(timeout)
