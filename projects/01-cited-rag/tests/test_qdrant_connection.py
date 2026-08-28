from pathlib import Path

import pytest
from pydantic import ValidationError

import cited_rag.qdrant_connection as connection
from cited_rag.qdrant_connection import (
    QdrantAdminSettings,
    QdrantContainerSecrets,
    QdrantReadSettings,
    make_admin_client_factory,
    make_read_client_factory,
)

READ_KEY = "r" * 48
ADMIN_KEY = "a" * 48


def read_settings(**overrides: object) -> QdrantReadSettings:
    return QdrantReadSettings(_env_file=None, **overrides)


def admin_settings(**overrides: object) -> QdrantAdminSettings:
    values = {
        "qdrant_url": "http://127.0.0.1:6333",
        "qdrant_admin_api_key": ADMIN_KEY,
        **overrides,
    }
    return QdrantAdminSettings(_env_file=None, **values)


def test_local_read_factory_uses_only_the_supplied_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        connection,
        "QdrantClient",
        lambda **kwargs: calls.append(kwargs) or object(),
    )
    local_path = tmp_path / "qdrant"

    make_read_client_factory(read_settings())(local_path)

    assert calls == [{"path": str(local_path)}]


def test_server_read_factory_uses_only_read_only_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        connection,
        "QdrantClient",
        lambda **kwargs: calls.append(kwargs) or object(),
    )
    configured = read_settings(
        qdrant_profile="server",
        qdrant_url="http://127.0.0.1:6333",
        qdrant_read_only_api_key=READ_KEY,
        qdrant_timeout_seconds=12,
    )

    make_read_client_factory(configured)(Path("ignored"))

    assert calls == [
        {
            "url": "http://127.0.0.1:6333",
            "api_key": READ_KEY,
            "timeout": 12,
            "prefer_grpc": False,
            "check_compatibility": True,
        }
    ]
    assert READ_KEY not in repr(configured)


def test_container_read_factory_uses_only_compose_dns_and_read_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        connection,
        "QdrantClient",
        lambda **kwargs: calls.append(kwargs) or object(),
    )
    configured = read_settings(
        qdrant_profile="container",
        qdrant_url="http://qdrant:6333",
        qdrant_read_only_api_key=READ_KEY,
        qdrant_timeout_seconds=9,
    )

    make_read_client_factory(configured)(Path("ignored"))

    assert calls == [
        {
            "url": "http://qdrant:6333",
            "api_key": READ_KEY,
            "timeout": 9,
            "prefer_grpc": False,
            "check_compatibility": True,
        }
    ]


def test_admin_factory_cannot_fall_back_to_read_only_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        connection,
        "QdrantClient",
        lambda **kwargs: calls.append(kwargs) or object(),
    )

    make_admin_client_factory(admin_settings())(Path("ignored"))

    assert calls[0]["api_key"] == ADMIN_KEY
    assert "qdrant_read_only_api_key" not in calls[0]


@pytest.mark.parametrize(
    "values",
    [
        {"qdrant_profile": "server"},
        {
            "qdrant_profile": "server",
            "qdrant_url": "http://127.0.0.1:6333",
        },
        {
            "qdrant_profile": "server",
            "qdrant_url": "http://localhost:6333",
            "qdrant_read_only_api_key": READ_KEY,
        },
        {
            "qdrant_profile": "server",
            "qdrant_url": "https://127.0.0.1:6333",
            "qdrant_read_only_api_key": READ_KEY,
        },
        {
            "qdrant_profile": "server",
            "qdrant_url": "http://127.0.0.1:6334",
            "qdrant_read_only_api_key": READ_KEY,
        },
        {
            "qdrant_profile": "server",
            "qdrant_url": "http://127.0.0.1:6333/collections",
            "qdrant_read_only_api_key": READ_KEY,
        },
        {
            "qdrant_profile": "server",
            "qdrant_url": "http://127.0.0.1:6333",
            "qdrant_read_only_api_key": "short",
        },
        {"qdrant_profile": "container"},
        {
            "qdrant_profile": "container",
            "qdrant_url": "http://qdrant:6333",
        },
        {
            "qdrant_profile": "container",
            "qdrant_url": "http://127.0.0.1:6333",
            "qdrant_read_only_api_key": READ_KEY,
        },
        {
            "qdrant_profile": "container",
            "qdrant_url": "https://qdrant:6333",
            "qdrant_read_only_api_key": READ_KEY,
        },
        {
            "qdrant_profile": "container",
            "qdrant_url": "http://qdrant:6334",
            "qdrant_read_only_api_key": READ_KEY,
        },
        {
            "qdrant_profile": "container",
            "qdrant_url": "http://qdrant:6333/collections",
            "qdrant_read_only_api_key": READ_KEY,
        },
        {
            "qdrant_profile": "server",
            "qdrant_url": "http://qdrant:6333",
            "qdrant_read_only_api_key": READ_KEY,
        },
        {"qdrant_url": "http://127.0.0.1:6333"},
        {"qdrant_read_only_api_key": READ_KEY},
        {"qdrant_timeout_seconds": 0},
        {"qdrant_timeout_seconds": 61},
    ],
)
def test_read_settings_reject_unsafe_combinations(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        read_settings(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("qdrant_url", "http://localhost:6333"),
        ("qdrant_url", "http://127.0.0.1:6333/path"),
        ("qdrant_admin_api_key", "short"),
        ("qdrant_timeout_seconds", 0),
        ("qdrant_timeout_seconds", 61),
    ],
)
def test_admin_settings_reject_unsafe_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        admin_settings(**{field: value})


def test_container_secrets_must_be_strong_and_distinct() -> None:
    configured = QdrantContainerSecrets(
        _env_file=None,
        qdrant_admin_api_key=ADMIN_KEY,
        qdrant_read_only_api_key=READ_KEY,
    )

    assert ADMIN_KEY not in repr(configured)
    assert READ_KEY not in repr(configured)
    with pytest.raises(ValidationError, match="must differ"):
        QdrantContainerSecrets(
            _env_file=None,
            qdrant_admin_api_key=ADMIN_KEY,
            qdrant_read_only_api_key=ADMIN_KEY,
        )
