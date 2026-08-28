import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from cited_rag.adapters.mimo import (
    DEFAULT_RETRY_DELAY_SECONDS,
    MAX_ATTEMPTS,
    MAX_COMPLETION_TOKENS,
    MAX_RETRY_DELAY_SECONDS,
    MiMoClient,
)
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
    assert len(response.attempts) == 1
    assert response.attempts[0].attempt == 1
    assert response.attempts[0].outcome == "success"


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
        clock=lambda: 0.0,
        sleeper=lambda _delay: None,
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
    calls = 0

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    result = MiMoClient(
        mimo_settings(),
        post=fake_post,
    ).generate(model_request())

    assert result.content == ""
    assert result.total_tokens is None
    assert calls == 1


@pytest.mark.parametrize("status_code", [408, 429, 500, 502, 503, 504])
def test_retryable_http_status_retries_once_with_identical_body(
    status_code: int,
) -> None:
    responses = iter(
        [
            response_with_content("hidden", status_code=status_code),
            response_with_content('{"answer":"回答"}'),
        ]
    )
    bodies: list[str] = []
    delays: list[float] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        bodies.append(
            json.dumps(
                kwargs["json"],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return next(responses)

    result = MiMoClient(
        mimo_settings(),
        post=fake_post,
        clock=lambda: 0.0,
        sleeper=delays.append,
    ).generate(model_request())

    assert len(bodies) == MAX_ATTEMPTS
    assert bodies[0] == bodies[1]
    assert delays == [DEFAULT_RETRY_DELAY_SECONDS]
    assert [item.outcome for item in result.attempts] == [
        "error",
        "success",
    ]
    assert result.attempts[0].retry_reason == (
        "rate_limit" if status_code == 429 else "server_error"
    )
    assert result.attempts[0].billing_uncertain is True


@pytest.mark.parametrize(
    "status_code",
    [400, 401, 403, 404, 409, 413, 422, 501],
)
def test_non_retryable_http_status_fails_after_one_attempt(
    status_code: int,
) -> None:
    calls = 0
    delays: list[float] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response_with_content("secret", status_code=status_code)

    with pytest.raises(ModelHttpError) as error:
        MiMoClient(
            mimo_settings(),
            post=fake_post,
            clock=lambda: 0.0,
            sleeper=delays.append,
        ).generate(model_request())

    assert calls == 1
    assert delays == []
    assert len(error.value.model_attempts) == 1
    assert error.value.model_attempts[0].retry_reason is None


@pytest.mark.parametrize(
    ("error_factory", "reason"),
    [
        (
            lambda request: httpx.ConnectError(
                "connect",
                request=request,
            ),
            "connect_error",
        ),
        (
            lambda request: httpx.ConnectTimeout(
                "connect timeout",
                request=request,
            ),
            "connect_timeout",
        ),
        (
            lambda request: httpx.PoolTimeout(
                "pool timeout",
                request=request,
            ),
            "pool_timeout",
        ),
    ],
)
def test_connection_stage_error_retries_once(
    error_factory: Callable[[httpx.Request], Exception],
    reason: str,
) -> None:
    calls = 0
    delays: list[float] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error_factory(httpx.Request("POST", url))
        return response_with_content('{"answer":"回答"}')

    result = MiMoClient(
        mimo_settings(),
        post=fake_post,
        clock=lambda: 0.0,
        sleeper=delays.append,
    ).generate(model_request())

    assert calls == 2
    assert delays == [DEFAULT_RETRY_DELAY_SECONDS]
    assert result.attempts[0].retry_reason == reason
    assert result.attempts[0].billing_uncertain is False


@pytest.mark.parametrize(
    ("error_factory", "expected", "phase"),
    [
        (
            lambda request: httpx.ReadTimeout(
                "read timeout",
                request=request,
            ),
            ModelTimeoutError,
            "read",
        ),
        (
            lambda request: httpx.WriteTimeout(
                "write timeout",
                request=request,
            ),
            ModelTimeoutError,
            "write",
        ),
        (
            lambda request: httpx.ReadError(
                "read error",
                request=request,
            ),
            ModelNetworkError,
            "read",
        ),
        (
            lambda request: httpx.WriteError(
                "write error",
                request=request,
            ),
            ModelNetworkError,
            "write",
        ),
    ],
)
def test_ambiguous_transport_error_does_not_retry(
    error_factory: Callable[[httpx.Request], Exception],
    expected: type[Exception],
    phase: str,
) -> None:
    calls = 0

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise error_factory(httpx.Request("POST", url))

    with pytest.raises(expected) as error:
        MiMoClient(
            mimo_settings(),
            post=fake_post,
            clock=lambda: 0.0,
            sleeper=lambda _delay: pytest.fail("must not sleep"),
        ).generate(model_request())

    assert calls == 1
    assert error.value.phase == phase
    assert len(error.value.model_attempts) == 1
    assert error.value.model_attempts[0].billing_uncertain is True


@pytest.mark.parametrize(
    ("header", "expected_delay"),
    [
        ("1.5", 1.5),
        ("3", MAX_RETRY_DELAY_SECONDS),
        ("Wed, 21 Oct 2015 07:28:00 GMT", DEFAULT_RETRY_DELAY_SECONDS),
        ("-1", DEFAULT_RETRY_DELAY_SECONDS),
        ("invalid", DEFAULT_RETRY_DELAY_SECONDS),
        ("9" * 17, DEFAULT_RETRY_DELAY_SECONDS),
    ],
)
def test_retry_after_is_parsed_safely_and_bounded(
    header: str,
    expected_delay: float,
) -> None:
    calls = 0
    delays: list[float] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": header},
                text="secret provider body",
            )
        return response_with_content('{"answer":"回答"}')

    result = MiMoClient(
        mimo_settings(),
        post=fake_post,
        clock=lambda: 0.0,
        sleeper=delays.append,
    ).generate(model_request())

    assert calls == 2
    assert delays == [expected_delay]
    assert result.attempts[0].retry_delay_ms == round(
        expected_delay * 1000
    )


def test_retry_stops_when_total_budget_cannot_cover_delay() -> None:
    clock_values = iter([0.0, 0.0, 31.9])
    calls = 0

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response_with_content("secret", status_code=503)

    with pytest.raises(ModelHttpError) as error:
        MiMoClient(
            mimo_settings(),
            post=fake_post,
            clock=lambda: next(clock_values),
            sleeper=lambda _delay: pytest.fail("must not sleep"),
        ).generate(model_request())

    assert calls == 1
    assert len(error.value.model_attempts) == 1
    assert error.value.model_attempts[0].retry_reason is None


def test_interruption_during_backoff_prevents_second_attempt() -> None:
    calls = 0

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response_with_content("secret", status_code=429)

    def interrupt(_delay: float) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        MiMoClient(
            mimo_settings(),
            post=fake_post,
            clock=lambda: 0.0,
            sleeper=interrupt,
        ).generate(model_request())

    assert calls == 1
