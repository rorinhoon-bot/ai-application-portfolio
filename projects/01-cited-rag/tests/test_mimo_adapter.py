import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from cited_rag.adapters.mimo import MAX_COMPLETION_TOKENS, MiMoClient
from cited_rag.config import Settings
from cited_rag.errors import (
    ModelHttpError,
    ModelNetworkError,
    ModelTimeoutError,
)
from cited_rag.model_client import AnswerModelRequest


def mimo_settings() -> Settings:
    return Settings(
        _env_file=None,
        model_provider="mimo",
        model_api_key="test-only-key",
        model_base_url="https://api.xiaomimimo.com/v1",
        model_name="mimo-v2.5",
        model_timeout_seconds=30,
    )


def model_request() -> AnswerModelRequest:
    return AnswerModelRequest(
        system_prompt="只返回 JSON。",
        user_payload={"question": "问题", "evidence": "untrusted material"},
        response_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
    )


def response_with_content(
    content: str,
    *,
    status_code: int = 200,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        },
    )


def test_mimo_client_builds_bounded_request_and_reads_usage() -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured.update(kwargs)
        return response_with_content('{"answer":"回答"}')

    response = MiMoClient(mimo_settings(), post=fake_post).generate(
        model_request()
    )

    assert response.content == '{"answer":"回答"}'
    assert (
        response.prompt_tokens,
        response.completion_tokens,
        response.total_tokens,
    ) == (100, 20, 120)
    assert captured["url"] == (
        "https://api.xiaomimimo.com/v1/chat/completions"
    )
    assert captured["timeout"] == 30
    assert captured["headers"]["api-key"] == "test-only-key"
    body = captured["json"]
    assert body["model"] == "mimo-v2.5"
    assert body["max_completion_tokens"] == MAX_COMPLETION_TOKENS
    assert body["temperature"] == 0
    assert body["stream"] is False
    assert body["thinking"] == {"type": "disabled"}
    assert "untrusted material" not in body["messages"][0]["content"]
    assert json.loads(body["messages"][1]["content"]) == {
        "question": "问题",
        "evidence": "untrusted material",
    }
    assert "test-only-key" not in json.dumps(body, ensure_ascii=False)


@pytest.mark.parametrize("status_code", [400, 401, 429, 500])
def test_mimo_client_maps_http_status_without_response_body(
    status_code: int,
) -> None:
    client = MiMoClient(
        mimo_settings(),
        post=lambda url, **kwargs: response_with_content(
            "secret provider body",
            status_code=status_code,
        ),
    )

    with pytest.raises(ModelHttpError) as error:
        client.generate(model_request())

    assert error.value.status_code == status_code
    assert "secret provider body" not in str(error.value)
    assert "test-only-key" not in str(error.value)


@pytest.mark.parametrize(
    ("error_factory", "expected"),
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
def test_mimo_client_maps_transport_errors(
    error_factory: Callable[[httpx.Request], Exception],
    expected: type[Exception],
) -> None:
    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        raise error_factory(httpx.Request("POST", url))

    with pytest.raises(expected):
        MiMoClient(mimo_settings(), post=fake_post).generate(model_request())


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
def test_mimo_client_turns_malformed_envelope_into_empty_content(
    response: httpx.Response,
) -> None:
    result = MiMoClient(
        mimo_settings(),
        post=lambda url, **kwargs: response,
    ).generate(model_request())

    assert result.content == ""
    assert result.total_tokens is None
