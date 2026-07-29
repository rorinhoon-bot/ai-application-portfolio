"""Environment-backed runtime configuration."""

from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Secrets and provider settings loaded from the P1 .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
    )

    model_provider: Literal["mimo"]
    model_api_key: Annotated[SecretStr, Field(min_length=1)]
    model_base_url: AnyHttpUrl
    model_name: Literal["mimo-v2.5"]
    model_timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 30.0

    @field_validator("model_base_url")
    @classmethod
    def require_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("MODEL_BASE_URL must use HTTPS")
        return value
