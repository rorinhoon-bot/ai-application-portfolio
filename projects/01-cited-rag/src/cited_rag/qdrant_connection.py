"""Strict local and loopback Qdrant client factories."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from qdrant_client import QdrantClient

ClientFactory = Callable[[Path], QdrantClient]
QDRANT_LOOPBACK_URL = "http://127.0.0.1:6333/"
QDRANT_CONTAINER_URL = "http://qdrant:6333/"
MINIMUM_API_KEY_LENGTH = 32


class QdrantReadSettings(BaseSettings):
    """Read-path settings loaded by the API or CLI process."""

    model_config = SettingsConfigDict(
        env_file=".env.qdrant-read",
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
    )

    qdrant_profile: Literal["local", "server", "container"] = "local"
    qdrant_url: AnyHttpUrl | None = None
    qdrant_read_only_api_key: SecretStr | None = None
    qdrant_timeout_seconds: Annotated[int, Field(ge=1, le=60)] = 10

    @model_validator(mode="after")
    def validate_profile(self) -> QdrantReadSettings:
        if self.qdrant_profile == "local":
            if (
                self.qdrant_url is not None
                or self.qdrant_read_only_api_key is not None
            ):
                raise ValueError(
                    "local Qdrant profile must not contain server settings"
                )
            return self
        if self.qdrant_profile == "server":
            _require_exact_url(
                self.qdrant_url,
                expected=QDRANT_LOOPBACK_URL,
                message="QDRANT_URL must be exactly http://127.0.0.1:6333",
            )
        else:
            _require_exact_url(
                self.qdrant_url,
                expected=QDRANT_CONTAINER_URL,
                message="QDRANT_URL must be exactly http://qdrant:6333",
            )
        _require_strong_secret(
            self.qdrant_read_only_api_key,
            name="QDRANT_READ_ONLY_API_KEY",
        )
        return self


class QdrantAdminSettings(BaseSettings):
    """Admin settings loaded only by controlled migration commands."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
    )

    qdrant_url: AnyHttpUrl
    qdrant_admin_api_key: SecretStr
    qdrant_timeout_seconds: Annotated[int, Field(ge=1, le=60)] = 10

    @model_validator(mode="after")
    def validate_admin_connection(self) -> QdrantAdminSettings:
        _require_loopback_url(self.qdrant_url)
        _require_strong_secret(
            self.qdrant_admin_api_key,
            name="QDRANT_ADMIN_API_KEY",
        )
        return self


class QdrantContainerSecrets(BaseSettings):
    """Validate the two credentials passed to the Qdrant container."""

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
    )

    qdrant_admin_api_key: SecretStr
    qdrant_read_only_api_key: SecretStr

    @model_validator(mode="after")
    def validate_distinct_secrets(self) -> QdrantContainerSecrets:
        _require_strong_secret(
            self.qdrant_admin_api_key,
            name="QDRANT_ADMIN_API_KEY",
        )
        _require_strong_secret(
            self.qdrant_read_only_api_key,
            name="QDRANT_READ_ONLY_API_KEY",
        )
        if (
            self.qdrant_admin_api_key.get_secret_value()
            == self.qdrant_read_only_api_key.get_secret_value()
        ):
            raise ValueError("Qdrant admin and read-only keys must differ")
        return self


def make_read_client_factory(
    settings: QdrantReadSettings,
) -> ClientFactory:
    """Create a factory that cannot silently switch credential roles."""

    if settings.qdrant_profile == "local":
        return lambda path: QdrantClient(path=str(path))
    assert settings.qdrant_url is not None
    assert settings.qdrant_read_only_api_key is not None
    return _make_server_client_factory(
        url=settings.qdrant_url,
        api_key=settings.qdrant_read_only_api_key,
        timeout=settings.qdrant_timeout_seconds,
    )


def make_admin_client_factory(
    settings: QdrantAdminSettings,
) -> ClientFactory:
    """Create a Server factory using only the explicit admin credential."""

    return _make_server_client_factory(
        url=settings.qdrant_url,
        api_key=settings.qdrant_admin_api_key,
        timeout=settings.qdrant_timeout_seconds,
    )


def _make_server_client_factory(
    *,
    url: AnyHttpUrl,
    api_key: SecretStr,
    timeout: int,
) -> ClientFactory:
    normalized_url = str(url).removesuffix("/")
    secret = api_key.get_secret_value()

    def create_client(_unused_local_path: Path) -> QdrantClient:
        return QdrantClient(
            url=normalized_url,
            api_key=secret,
            timeout=timeout,
            prefer_grpc=False,
            check_compatibility=True,
        )

    return create_client


def _require_loopback_url(value: AnyHttpUrl | None) -> None:
    _require_exact_url(
        value,
        expected=QDRANT_LOOPBACK_URL,
        message="QDRANT_URL must be exactly http://127.0.0.1:6333",
    )


def _require_exact_url(
    value: AnyHttpUrl | None,
    *,
    expected: str,
    message: str,
) -> None:
    if value is None or str(value) != expected:
        raise ValueError(message)


def _require_strong_secret(
    value: SecretStr | None,
    *,
    name: str,
) -> None:
    if (
        value is None
        or len(value.get_secret_value()) < MINIMUM_API_KEY_LENGTH
    ):
        raise ValueError(
            f"{name} must contain at least {MINIMUM_API_KEY_LENGTH} characters"
        )
