"""Trusted local adapter paths and strict contracts; no environment-file loader."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
P1 = REPO / "projects/01-cited-rag"
P2 = REPO / "projects/02-agent-research-workflow"
P3 = REPO / "projects/03-mcp-tool-server"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class BoundaryError(ValueError):
    pass


class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Record(Strict):
    record_id: Annotated[str, Field(pattern=r"^(graph-plan|chain-plan)-(tool-calling|human-approval|recovery)$")]
    candidate_id: Literal["graph-plan", "chain-plan"]
    section_id: Literal["tool-calling", "human-approval", "recovery"]
    title: str
    text: Annotated[str, Field(min_length=1, max_length=2400)]
    source_file: Literal["graph-plan.html", "chain-plan.html"]
    source_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    content_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    block_orders: list[int]
    note_id: Annotated[str, Field(pattern=r"^[a-f0-9]{16}$")]


class P1Response(Strict):
    schema_version: Literal["p1-integration-v1"]
    mode: Literal["fixture-keyword"]
    corpus_hash: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    records: list[Record]


class P1Request(Strict):
    operation: Literal["catalog", "search"]
    query: Annotated[str, Field(max_length=300)] = ""
    candidate_ids: list[Literal["graph-plan", "chain-plan"]] = Field(default_factory=list)
    top_k: Annotated[int, Field(ge=1, le=8)] = 6


def clean_env(project):
    env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH") if key in os.environ}
    env.update(PYTHONPATH=str(project / "src"), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8",
               LANGGRAPH_STRICT_MSGPACK="true", NETWORK_ACCESS_BLOCKED_IN_TESTS="1")
    return env


def worker(project, script, payload, *, arguments=(), timeout=25):
    command = [str(project / ".venv/Scripts/python.exe"), str(HERE / script), *map(str, arguments)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, cwd=HERE, env=clean_env(project))
    try:
        stdout, _ = process.communicate(json.dumps(payload, ensure_ascii=False).encode(), timeout=timeout)
    except subprocess.TimeoutExpired:
        # Only terminate this tool-owned process tree; never a discovered or pre-existing service.
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        process.kill()
        process.communicate()
        raise BoundaryError("ADAPTER_TIMEOUT") from None
    if process.returncode or len(stdout) > 262144:
        raise BoundaryError("ADAPTER_FAILED")
    try:
        result = json.loads(stdout)
    except (ValueError, UnicodeError):
        raise BoundaryError("ADAPTER_OUTPUT_INVALID") from None
    if not isinstance(result, dict):
        raise BoundaryError("ADAPTER_OUTPUT_INVALID")
    return result


def safe_directory(path):
    path = Path(path).absolute()
    for component in (path, *path.parents):
        if component.exists() and (component.is_symlink() or
                getattr(component.lstat(), "st_file_attributes", 0) & 0x400):
            raise BoundaryError("RUNTIME_PATH_UNSAFE")
    if not path.is_dir():
        raise BoundaryError("RUNTIME_PATH_UNSAFE")
    return path


def read_json(path):
    path = Path(path)
    safe_directory(path.parent)
    if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
        raise BoundaryError("RUNTIME_PATH_UNSAFE")
    return json.loads(path.read_text(encoding="utf-8"))


def write_once(path, value):
    path = Path(path)
    safe_directory(path.parent)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    publish_bytes(path, text.encode("utf-8"))


def publish_bytes(path, data):
    """Atomic no-replace local artifact, identical replay only; never overwrite old work."""
    path = Path(path)
    safe_directory(path.parent)
    if path.exists():
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise BoundaryError("RUNTIME_PATH_UNSAFE")
        if path.read_bytes() == data:
            return
        raise BoundaryError("ARTIFACT_CONFLICT")
    fd, temporary = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise BoundaryError("ARTIFACT_CONFLICT") from None
    finally:
        os.unlink(temporary)
