import pytest
from pydantic import ValidationError

from structured_notes.config import Settings


def valid_settings_data() -> dict[str, object]:
    return {
        "model_provider": "fake-provider",
        "model_api_key": "test-only-key",
        "model_base_url": "https://example.com/v1",
        "model_name": "test-model",
    }


def test_settings_accept_valid_values_and_use_default_timeout() -> None:
    settings = Settings(_env_file=None, **valid_settings_data())

    assert settings.model_provider == "fake-provider"
    assert settings.model_name == "test-model"
    assert settings.model_timeout_seconds == 30.0
    assert str(settings.model_api_key) == "**********"


def test_settings_load_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "environment-provider")
    monkeypatch.setenv("MODEL_API_KEY", "environment-test-key")
    monkeypatch.setenv("MODEL_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("MODEL_NAME", "environment-model")
    monkeypatch.setenv("MODEL_TIMEOUT_SECONDS", "15")

    settings = Settings(_env_file=None)

    assert settings.model_provider == "environment-provider"
    assert settings.model_name == "environment-model"
    assert settings.model_timeout_seconds == 15.0


def test_settings_reject_missing_required_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "MODEL_PROVIDER",
        "MODEL_API_KEY",
        "MODEL_BASE_URL",
        "MODEL_NAME",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_reject_non_positive_timeout() -> None:
    data = valid_settings_data()
    data["model_timeout_seconds"] = 0

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **data)

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("model_timeout_seconds",)
    assert error["type"] == "greater_than"


def test_settings_reject_non_https_base_url() -> None:
    data = valid_settings_data()
    data["model_base_url"] = "http://example.com/v1"

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, **data)

    error = exc_info.value.errors()[0]

    assert error["loc"] == ("model_base_url",)
    assert error["type"] == "value_error"
