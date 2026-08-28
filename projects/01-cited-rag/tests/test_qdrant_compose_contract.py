from pathlib import Path

import yaml

COMPOSE_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "compose.qdrant.yaml"
)
PINNED_IMAGE = (
    "qdrant/qdrant:v1.19.0-unprivileged@"
    "sha256:a0e04fe623cb064502cd869cefc1dc7ce"
    "359d8edd481063b5bd351c0a0a2c91e"
)


def compose_text() -> str:
    return COMPOSE_PATH.read_text(encoding="utf-8")


def qdrant_service() -> dict[str, object]:
    compose = yaml.safe_load(compose_text())
    value = compose["services"]["qdrant"]
    assert isinstance(value, dict)
    return value


def test_compose_pins_exact_unprivileged_image_digest() -> None:
    value = compose_text()

    assert f"image: {PINNED_IMAGE}" in value
    assert ":latest" not in value


def test_compose_publishes_only_loopback_rest_port() -> None:
    value = compose_text()

    assert '"127.0.0.1:6333:6333"' in value
    assert '"6334:6334"' not in value
    assert '"6335:6335"' not in value
    assert '"0.0.0.0:' not in value


def test_compose_uses_named_writable_volumes() -> None:
    qdrant = qdrant_service()

    assert qdrant["volumes"] == [
        "qdrant_storage:/qdrant/storage",
        "qdrant_snapshots:/qdrant/snapshots",
    ]
    assert qdrant["read_only"] is True


def test_compose_requires_separate_external_credentials() -> None:
    value = compose_text()

    assert "${QDRANT_ADMIN_API_KEY:?" in value
    assert "${QDRANT_READ_ONLY_API_KEY:?" in value
    assert "generate-a-random" not in value


def test_compose_disables_unsafe_optional_surfaces() -> None:
    value = compose_text()

    assert 'QDRANT__SERVICE__ENABLE_CORS: "false"' in value
    assert (
        'QDRANT__SERVICE__ENABLE_SNAPSHOT_URL_RECOVERY: "false"'
        in value
    )
    assert 'QDRANT__TELEMETRY_DISABLED: "true"' in value
    assert 'QDRANT__CLUSTER__ENABLED: "false"' in value


def test_compose_uses_dedicated_non_internal_loopback_bridge() -> None:
    value = compose_text()

    assert "qdrant_bridge:" in value
    assert "driver: bridge" in value
    assert "internal: false" in value
    assert (
        'com.docker.network.bridge.host_binding_ipv4: "127.0.0.1"'
        in value
    )
    assert "internal: true" not in value


def test_compose_applies_process_and_log_limits() -> None:
    value = compose_text()

    assert "user: \"1000:1000\"" in value
    assert "- ALL" in value
    assert "- no-new-privileges:true" in value
    assert "pids_limit: 512" in value
    assert "cpus: 2.0" in value
    assert "mem_limit: 1g" in value
    assert "max-size: 10m" in value
    assert 'max-file: "3"' in value


def test_compose_healthcheck_does_not_require_curl_or_wget() -> None:
    value = compose_text()

    assert "/dev/tcp/127.0.0.1/6333" in value
    assert "curl" not in value
    assert "wget" not in value
