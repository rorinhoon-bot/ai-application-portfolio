import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from structured_notes.adapters import create_model_client
from structured_notes.adapters.mimo import MAX_COMPLETION_TOKENS, MiMoClient
from structured_notes.config import Settings
from structured_notes.model_client import (
    ModelHttpError,
    ModelNetworkError,
    ModelTimeoutError,
)
from structured_notes.models import ModelRequest


def mimo_settings() -> Settings:
    return Settings(
        _env_file=None,
        model_provider="mimo",
        model_api_key="test-only-key",
        model_base_url="https://api.xiaomimimo.com/v1",
        model_name="mimo-v2.5",
        model_timeout_seconds=30,
    )


def model_request() -> ModelRequest:
    return ModelRequest(
        system_prompt="只返回 JSON。",
        user_payload={
            "topic": "Transformer",
            "material": "untrusted material",
            "learner_level": "beginner",
        },
        response_schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                }
            },
            "required": ["title"],
        },
    )


def response_with_content(content: str, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={
            "choices": [
                {
                    "message": {
                        "content": content,
                    }
                }
            ]
        },
    )


def test_registered_mimo_factory_creates_mimo_client() -> None:
    client = create_model_client(mimo_settings())

    assert isinstance(client, MiMoClient)


def test_mimo_client_builds_openai_compatible_json_request() -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured.update(kwargs)
        return response_with_content('{"title":"Transformer"}')

    client = MiMoClient(mimo_settings(), post=fake_post)

    response = client.generate(model_request())

    assert response.content == '{"title":"Transformer"}'
    assert captured["url"] == (
        "https://api.xiaomimimo.com/v1/chat/completions"
    )
    assert captured["timeout"] == 30
    assert captured["headers"] == {
        "api-key": "test-only-key",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = captured["json"]
    assert body["model"] == "mimo-v2.5"
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_completion_tokens"] == MAX_COMPLETION_TOKENS
    assert body["stream"] is False
    assert body["thinking"] == {"type": "disabled"}
    assert "untrusted material" not in body["messages"][0]["content"]
    assert "JSON Schema" in body["messages"][0]["content"]
    assert json.loads(body["messages"][1]["content"]) == {
        "topic": "Transformer",
        "material": "untrusted material",
        "learner_level": "beginner",
    }
    assert "test-only-key" not in json.dumps(body, ensure_ascii=False)


@pytest.mark.parametrize("status_code", [400, 401, 429, 500])
def test_mimo_client_maps_non_success_status(status_code: int) -> None:
    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        return response_with_content("ignored", status_code=status_code)

    client = MiMoClient(mimo_settings(), post=fake_post)

    with pytest.raises(ModelHttpError) as exc_info:
        client.generate(model_request())

    assert exc_info.value.status_code == status_code
    assert "test-only-key" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("error_factory", "expected_error"),
    [
        (
            lambda request: httpx.ReadTimeout("timeout", request=request),
            ModelTimeoutError,
        ),
        (
            lambda request: httpx.ConnectError("network", request=request),
            ModelNetworkError,
        ),
    ],
)
def test_mimo_client_maps_httpx_transport_errors(
    error_factory: Callable[[httpx.Request], Exception],
    expected_error: type[Exception],
) -> None:
    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        request = httpx.Request("POST", url)
        raise error_factory(request)

    client = MiMoClient(mimo_settings(), post=fake_post)

    with pytest.raises(expected_error):
        client.generate(model_request())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": None}}]},
        ),
    ],
)
def test_mimo_client_converts_malformed_envelope_to_empty_content(
    response: httpx.Response,
) -> None:
    client = MiMoClient(
        mimo_settings(),
        post=lambda url, **kwargs: response,
    )

    assert client.generate(model_request()).content == ""
