from typing import Annotated

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        str_strip_whitespace=True,
    )

    model_provider: Annotated[str, Field(min_length=1)]
    model_api_key: Annotated[SecretStr, Field(min_length=1)]
    model_base_url: AnyHttpUrl
    model_name: Annotated[str, Field(min_length=1)]
    model_timeout_seconds: Annotated[float, Field(gt=0)] = 30.0

    @field_validator("model_base_url")
    @classmethod
    def require_https(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("MODEL_BASE_URL must use HTTPS")
        return value
