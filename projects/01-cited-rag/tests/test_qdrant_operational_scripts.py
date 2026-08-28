from collections.abc import Callable
import json
from pathlib import Path

import pytest

from scripts import build_server_index as build
from scripts import validate_qdrant_permissions as permissions
from scripts import validate_qdrant_persistence as persistence
from scripts import validate_qdrant_recovery as recovery
from scripts.validate_qdrant_recovery import _safe_snapshot_name


def validation_result() -> dict[str, object]:
    return {
        "status": "unchanged",
        "server_version": "1.19.0",
        "index_id": "614f6c23-7c35-5832-8086-c29651d60866",
        "build_id": "418359df-7c62-4345-9bfe-57459c251dd3",
        "collection_name": "cited-rag-active",
        "chunk_count": 1359,
        "embedded_count": 0,
        "validation": {
            "point_count": 1359,
            "payload_count": 1359,
            "unique_point_count": 1359,
            "self_query_top_score": 1.0,
            "version_filter_checked": True,
        },
    }


def test_persistence_sequence_never_removes_named_volumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose_calls: list[tuple[str, ...]] = []
    docker_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(persistence, "REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(persistence, "_docker_executable", lambda: "docker")
    monkeypatch.setattr(
        persistence,
        "_validate_index",
        validation_result,
    )
    monkeypatch.setattr(
        persistence,
        "_run_compose",
        lambda _docker, *arguments: compose_calls.append(arguments),
    )
    monkeypatch.setattr(
        persistence,
        "_run_docker",
        lambda _docker, *arguments: docker_calls.append(arguments),
    )
    monkeypatch.setattr(persistence, "_wait_until_ready", lambda: None)

    assert persistence.main() == 0

    assert compose_calls == [
        ("restart", "qdrant"),
        ("down",),
        ("up", "-d", "qdrant"),
    ]
    assert all("-v" not in arguments for arguments in compose_calls)
    assert docker_calls == [
        ("volume", "inspect", volume_name)
        for volume_name in persistence.VOLUME_NAMES
    ]
    report = json.loads(persistence.REPORT_PATH.read_text(encoding="utf-8"))
    assert report["compose_down_used_volume_removal"] is False
    assert report["named_volumes_preserved"] == list(
        persistence.VOLUME_NAMES
    )


def test_persistence_sequence_retries_up_after_failed_recreation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose_calls: list[tuple[str, ...]] = []
    up_attempts = 0

    def run_compose(_docker: str, *arguments: str) -> None:
        nonlocal up_attempts
        compose_calls.append(arguments)
        if arguments == ("up", "-d", "qdrant"):
            up_attempts += 1
            if up_attempts == 1:
                raise RuntimeError("simulated first up failure")

    monkeypatch.setattr(persistence, "REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setattr(persistence, "_docker_executable", lambda: "docker")
    monkeypatch.setattr(
        persistence,
        "_validate_index",
        validation_result,
    )
    monkeypatch.setattr(persistence, "_run_compose", run_compose)
    monkeypatch.setattr(persistence, "_run_docker", lambda *_args: None)
    monkeypatch.setattr(persistence, "_wait_until_ready", lambda: None)

    with pytest.raises(RuntimeError, match="simulated first up failure"):
        persistence.main()

    assert up_attempts == 2
    assert compose_calls[-1] == ("up", "-d", "qdrant")
    assert not persistence.REPORT_PATH.exists()


@pytest.mark.parametrize(
    "unsafe_name",
    ("", "../x.snapshot", "..\\x.snapshot", "/x.snapshot", "x/y", "x\\y"),
)
def test_snapshot_name_rejects_path_traversal(unsafe_name: str) -> None:
    with pytest.raises(RuntimeError, match="unsafe snapshot name"):
        _safe_snapshot_name(unsafe_name)


def test_snapshot_name_accepts_qdrant_basename() -> None:
    name = "cited-rag-2026-08-23.snapshot"

    assert _safe_snapshot_name(name) == name


@pytest.mark.parametrize(
    "validator",
    (
        build._validate_report_target,
        permissions._validate_report_target,
        persistence._validate_report_target,
        recovery._validate_report_target,
    ),
)
def test_operational_report_target_must_be_a_regular_file(
    validator: Callable[[Path], bool],
    tmp_path: Path,
) -> None:
    report = tmp_path / "report.json"
    report.mkdir()

    with pytest.raises(RuntimeError, match="regular file"):
        validator(report)

    report.rmdir()
    report.write_text("{}\n", encoding="utf-8")
    assert validator(report) is True
