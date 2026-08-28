"""Validate Qdrant data across restart and Compose down/up."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
import sys
import time

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = PROJECT_ROOT / "deploy" / "compose.qdrant.yaml"
SERVER_ENV = PROJECT_ROOT / ".env.qdrant-server"
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_server_index.py"
REPORT_PATH = PROJECT_ROOT / "data" / "qdrant-persistence-report.json"
READY_URL = "http://127.0.0.1:6333/readyz"
VOLUME_NAMES = (
    "cited-rag-qdrant_qdrant_storage",
    "cited-rag-qdrant_qdrant_snapshots",
)


def main(*, preserve_existing_report: bool = False) -> int:
    report_already_exists = _validate_report_target(REPORT_PATH)
    if report_already_exists and not preserve_existing_report:
        raise FileExistsError("Qdrant persistence report already exists")
    docker = _docker_executable()
    before = _validate_index()
    phases: list[dict[str, object]] = [
        _phase_record("before_restart", before)
    ]

    compose_is_up = True
    try:
        _run_compose(docker, "restart", "qdrant")
        _wait_until_ready()
        phases.append(
            _phase_record("after_restart", _validate_index())
        )

        _run_compose(docker, "down")
        compose_is_up = False
        for volume_name in VOLUME_NAMES:
            _run_docker(docker, "volume", "inspect", volume_name)

        _run_compose(docker, "up", "-d", "qdrant")
        compose_is_up = True
        _wait_until_ready()
        phases.append(
            _phase_record("after_down_up", _validate_index())
        )
    finally:
        if not compose_is_up:
            _run_compose(docker, "up", "-d", "qdrant")
            _wait_until_ready()

    identity_fields = ("index_id", "build_id", "collection_name")
    expected_identity = {
        field: before[field] for field in identity_fields
    }
    for phase in phases:
        if any(
            phase[field] != expected_identity[field]
            for field in identity_fields
        ):
            raise RuntimeError("Qdrant index identity changed across restart")
        if phase["embedded_count"] != 0:
            raise RuntimeError("persistence check unexpectedly rebuilt vectors")
        validation = phase["validation"]
        if not isinstance(validation, dict) or validation.get("point_count") != 1359:
            raise RuntimeError("Qdrant point validation changed across restart")

    report = {
        "schema_version": "1",
        "status": "passed",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "compose_down_used_volume_removal": False,
        "named_volumes_preserved": list(VOLUME_NAMES),
        "phases": phases,
    }
    if not report_already_exists:
        with REPORT_PATH.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
            file.write("\n")
    print(
        json.dumps(
            {
                "status": "passed",
                "identity": expected_identity,
                "phases": [phase["phase"] for phase in phases],
                "point_count": 1359,
                "vectors_rebuilt": 0,
                "named_volumes_preserved": list(VOLUME_NAMES),
                (
                    "report_preserved"
                    if report_already_exists
                    else "report"
                ): str(REPORT_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _phase_record(
    phase: str,
    validation: dict[str, object],
) -> dict[str, object]:
    return {
        "phase": phase,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "server_version": validation["server_version"],
        "index_id": validation["index_id"],
        "build_id": validation["build_id"],
        "collection_name": validation["collection_name"],
        "chunk_count": validation["chunk_count"],
        "embedded_count": validation["embedded_count"],
        "validation": validation["validation"],
    }


def _validate_index() -> dict[str, object]:
    environment = os.environ.copy()
    environment["HF_HUB_OFFLINE"] = "1"
    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT)],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("offline Server index validation failed")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("Server index validation output is invalid") from error
    if value.get("status") not in {"ready", "unchanged"}:
        raise RuntimeError("Server index is not ready")
    return value


def _wait_until_ready(*, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    with httpx.Client(timeout=2.0, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(READY_URL)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1)
    raise TimeoutError("Qdrant /readyz did not return HTTP 200")


def _docker_executable() -> str:
    discovered = shutil.which("docker")
    if discovered is not None:
        return discovered
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = (
            Path(local_app_data)
            / "Programs"
            / "DockerDesktop"
            / "resources"
            / "bin"
            / "docker.exe"
        )
        if candidate.is_file():
            return str(candidate)
    raise FileNotFoundError("Docker CLI was not found")


def _run_compose(docker: str, *arguments: str) -> None:
    _run_docker(
        docker,
        "compose",
        "--env-file",
        str(SERVER_ENV),
        "-f",
        str(COMPOSE_FILE),
        *arguments,
    )


def _run_docker(docker: str, *arguments: str) -> None:
    result = subprocess.run(
        [docker, *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Docker command failed with exit code {result.returncode}"
        )


def _validate_report_target(path: Path) -> bool:
    if path.is_symlink():
        raise RuntimeError("persistence report must not be a symbolic link")
    if path.exists() and not path.is_file():
        raise RuntimeError("persistence report must be a regular file")
    return path.exists()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate Qdrant data across restart and down/up."
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="preserve an existing tracked historical persistence report",
    )
    arguments = parser.parse_args()
    raise SystemExit(
        main(preserve_existing_report=arguments.restore)
    )
