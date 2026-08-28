from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = PROJECT_ROOT / "deploy" / "compose.qdrant.yaml"
COLLECTOR_CONFIG_PATH = PROJECT_ROOT / "deploy" / "otel-collector.yaml"
COLLECTOR_IMAGE = (
    "ghcr.io/open-telemetry/opentelemetry-collector-releases/"
    "opentelemetry-collector-contrib:0.159.0@"
    "sha256:1f2c54a30e713fac6b3ae77a1ec84010c2007e29ced8ec"
    "666214fc2f6739c1cc"
)


def load_yaml(path: Path):
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def collector_service():
    value = load_yaml(COMPOSE_PATH)["services"]["otel-collector"]
    assert isinstance(value, dict)
    return value


def test_collector_uses_fixed_image_and_loopback_metrics_only() -> None:
    collector = collector_service()

    assert collector["image"] == COLLECTOR_IMAGE
    assert collector["profiles"] == ["observability"]
    assert collector["ports"] == ["127.0.0.1:9464:9464"]
    assert "4317" not in str(collector)
    assert "4318:" not in str(collector.get("ports"))


def test_collector_has_no_writable_volume_or_privileged_capability() -> None:
    collector = collector_service()

    assert collector["user"] == "10001:10001"
    assert collector["read_only"] is True
    assert collector["cap_drop"] == ["ALL"]
    assert collector["security_opt"] == ["no-new-privileges:true"]
    assert collector["pids_limit"] == 128
    assert collector["cpus"] == 1.0
    assert collector["mem_limit"] == "256m"
    assert collector["volumes"] == [
        {
            "type": "bind",
            "source": "./otel-collector.yaml",
            "target": "/etc/otelcol-contrib/config.yaml",
            "read_only": True,
            "bind": {"create_host_path": False},
        }
    ]


def test_collector_pipeline_uses_only_approved_components() -> None:
    config = load_yaml(COLLECTOR_CONFIG_PATH)

    assert set(config) == {"receivers", "processors", "exporters", "service"}
    assert set(config["receivers"]) == {"otlp"}
    assert set(config["processors"]) == {"memory_limiter", "batch"}
    assert set(config["exporters"]) == {"debug", "prometheus"}
    assert (
        config["receivers"]["otlp"]["protocols"]["http"]["endpoint"]
        == "0.0.0.0:4318"
    )
    assert config["exporters"]["prometheus"]["endpoint"] == "0.0.0.0:9464"
    assert set(config["service"]["pipelines"]) == {"traces", "metrics"}


def test_api_telemetry_is_explicit_and_not_a_readiness_dependency() -> None:
    services = load_yaml(COMPOSE_PATH)["services"]
    api = services["api"]

    assert api["environment"]["OTEL_ENABLED"] == "${P1_OTEL_ENABLED:-false}"
    assert (
        api["environment"]["OTEL_EXPORTER_OTLP_ENDPOINT"]
        == "http://otel-collector:4318"
    )
    assert api["depends_on"] == {
        "qdrant": {"condition": "service_healthy"}
    }
