import json
import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = PROJECT_ROOT / "requirements-api.txt"
DOCKERFILE_PATH = PROJECT_ROOT / "deploy" / "Dockerfile.api"
DOCKERIGNORE_PATH = PROJECT_ROOT / ".dockerignore"
COMPOSE_PATH = PROJECT_ROOT / "deploy" / "compose.qdrant.yaml"
REPORT_PATH = PROJECT_ROOT / "data" / "api-container-report.json"
PYTHON_IMAGE = (
    "python:3.14.7-slim-bookworm@"
    "sha256:23c59390fc717bf09f9336908199a0ae"
    "75d9c4264bf296123f94ad772fea3b52"
)
DOCKERFILE_FRONTEND = (
    "docker/dockerfile:1.7@"
    "sha256:a57df69d0ea827fb7266491f2813635d"
    "e6f17269be881f696fbfdf2d83dda33e"
)
LOCK_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^ ]+) "
    r"--hash=sha256:(?P<hash>[0-9a-f]{64})  # (?P<wheel>[^ ]+\.whl)$"
)


def lock_records() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for line in LOCK_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        match = LOCK_PATTERN.fullmatch(line)
        assert match is not None, line
        records.append(match.groupdict())
    return records


def compose() -> dict[str, object]:
    value = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def api_service() -> dict[str, object]:
    services = compose()["services"]
    assert isinstance(services, dict)
    value = services["api"]
    assert isinstance(value, dict)
    return value


def test_api_lock_contains_51_unique_hashed_linux_wheels() -> None:
    records = lock_records()
    names = [record["name"].lower().replace("_", "-") for record in records]

    assert len(records) == 51
    assert len(names) == len(set(names))
    assert all("win" not in record["wheel"].lower() for record in records)
    assert all("macos" not in record["wheel"].lower() for record in records)


def test_api_lock_excludes_ui_windows_and_development_packages() -> None:
    names = {
        record["name"].lower().replace("_", "-")
        for record in lock_records()
    }

    assert {
        "streamlit",
        "pandas",
        "pyarrow",
        "pydeck",
        "gitpython",
        "pywin32",
        "pytest",
        "setuptools",
    }.isdisjoint(names)
    assert {
        "fastapi",
        "fastembed",
        "httpx",
        "pydantic",
        "pydantic-settings",
        "qdrant-client",
        "uvicorn",
        "opentelemetry-api",
        "opentelemetry-exporter-otlp-proto-http",
        "opentelemetry-sdk",
        "h2",
        "hpack",
        "hyperframe",
    }.issubset(names)


def test_dockerfile_pins_base_and_requires_binary_hashes() -> None:
    value = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert value.startswith(f"# syntax={DOCKERFILE_FRONTEND}\n")
    assert f"ARG PYTHON_IMAGE={PYTHON_IMAGE}" in value
    assert value.count("FROM ${PYTHON_IMAGE}") == 2
    assert "--require-hashes" in value
    assert "--only-binary=:all:" in value
    assert "--no-index" in value
    assert "apt-get" not in value


def test_dockerfile_runs_non_root_single_worker_offline() -> None:
    value = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "HF_HUB_OFFLINE=1" in value
    assert "USER 10001:10001" in value
    assert '"--workers", "1"' in value
    assert "streamlit" not in value.lower()
    assert "COPY . " not in value
    assert "ADD " not in value


def test_dockerignore_is_a_positive_build_context_allowlist() -> None:
    lines = set(DOCKERIGNORE_PATH.read_text(encoding="utf-8").splitlines())

    assert "**" in lines
    assert "!requirements-api.txt" in lines
    assert "!src/cited_rag/**" in lines
    assert "!data/model-assets.json" in lines
    assert "!deploy/Dockerfile.api" in lines
    assert not any(".env" in line for line in lines)


def test_api_compose_uses_profile_fixed_image_and_loopback_port() -> None:
    api = api_service()

    assert api["profiles"] == ["api"]
    assert api["image"] == "cited-rag-api:v2-d1"
    assert api["build"] == {
        "context": "..",
        "dockerfile": "deploy/Dockerfile.api",
    }
    assert api["ports"] == ["127.0.0.1:8000:8000"]
    assert api["networks"] == ["qdrant_bridge"]


def test_api_compose_uses_only_read_credentials_and_container_dns() -> None:
    api = api_service()

    assert api["env_file"] == [
        "${P1_MODEL_ENV_FILE:?P1_MODEL_ENV_FILE is required}",
        "../.env.qdrant-read",
    ]
    assert api["environment"] == {
        "HF_HUB_OFFLINE": "1",
        "OTEL_ENABLED": "${P1_OTEL_ENABLED:-false}",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4318",
        "QDRANT_PROFILE": "container",
        "QDRANT_URL": "http://qdrant:6333",
    }
    assert "admin" not in str(api).lower()


def test_api_compose_mounts_only_runtime_assets_read_only() -> None:
    api = api_service()
    volumes = api["volumes"]

    assert isinstance(volumes, list)
    assert volumes == [
        {
            "type": "bind",
            "source": "../data/models/fastembed",
            "target": "/app/data/models/fastembed",
            "read_only": True,
            "bind": {"create_host_path": False},
        },
        {
            "type": "bind",
            "source": "../data/server-indexes",
            "target": "/app/data/server-indexes",
            "read_only": True,
            "bind": {"create_host_path": False},
        },
    ]


def test_api_compose_applies_read_only_process_and_resource_limits() -> None:
    api = api_service()

    assert api["user"] == "10001:10001"
    assert api["read_only"] is True
    assert api["tmpfs"] == ["/tmp:rw,noexec,nosuid,nodev,size=134217728"]
    assert api["cap_drop"] == ["ALL"]
    assert api["security_opt"] == ["no-new-privileges:true"]
    assert api["pids_limit"] == 256
    assert api["cpus"] == 2.0
    assert api["mem_limit"] == "1g"
    assert api["depends_on"] == {
        "qdrant": {"condition": "service_healthy"}
    }


def test_api_healthcheck_uses_python_readyz_without_external_tool() -> None:
    api = api_service()
    healthcheck = api["healthcheck"]

    assert isinstance(healthcheck, dict)
    test = healthcheck["test"]
    assert "python" in test
    assert any("/readyz" in item for item in test)
    assert "curl" not in str(test)
    assert "wget" not in str(test)


def test_api_container_report_preserves_approved_runtime_evidence() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert report["schema_version"] == "1"
    assert report["slice"] == "V2-B2"
    assert report["status"] == "passed"
    assert report["build"]["dependency_count"] == 44
    assert report["build"]["h_drive_consumed_bytes"] <= report["build"][
        "approved_h_drive_cap_bytes"
    ]
    assert report["runtime"]["admin_key_present"] is False
    assert report["active_index"]["point_count"] == 1359
    assert (
        report["active_index"]["active_pointer_sha256_before"]
        == report["active_index"]["active_pointer_sha256_after"]
    )
    assert (
        report["active_index"]["manifest_sha256_before"]
        == report["active_index"]["manifest_sha256_after"]
    )
    assert report["checks"]["mimo_called"] is False
    assert report["checks"]["legal_answer_request_sent"] is False
