import pytest
from pydantic import ValidationError

from cited_rag.config import Settings


def settings(**overrides: object) -> Settings:
    values = {
        "model_provider": "mimo",
        "model_api_key": "test-only-key",
        "model_base_url": "https://api.xiaomimimo.com/v1",
        "model_name": "mimo-v2.5",
        "model_timeout_seconds": 30,
        **overrides,
    }
    return Settings(_env_file=None, **values)


def test_settings_keep_api_key_secret() -> None:
    configured = settings()

    assert configured.model_api_key.get_secret_value() == "test-only-key"
    assert "test-only-key" not in repr(configured)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_provider", "other"),
        ("model_api_key", ""),
        ("model_base_url", "http://api.xiaomimimo.com/v1"),
        ("model_name", "other-model"),
        ("model_timeout_seconds", 0),
        ("model_timeout_seconds", 61),
    ],
)
def test_settings_reject_unsafe_or_unpinned_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        settings(**{field: value})
