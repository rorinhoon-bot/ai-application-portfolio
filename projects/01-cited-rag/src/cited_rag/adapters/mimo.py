"""MiMo OpenAI-compatible chat-completions adapter."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from time import monotonic, sleep
from typing import Any, NoReturn

import httpx

from cited_rag.config import Settings
from cited_rag.errors import (
    ModelHttpError,
    ModelNetworkError,
    ModelTimeoutError,
)
from cited_rag.model_client import (
    AnswerModelAttempt,
    AnswerModelRequest,
    AnswerModelResponse,
    RetryReason,
)

MAX_COMPLETION_TOKENS = 800
MAX_ATTEMPTS = 2
DEFAULT_RETRY_DELAY_SECONDS = 0.25
MAX_RETRY_DELAY_SECONDS = 2.0
RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
_RETRY_AFTER_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
HttpPost = Callable[..., httpx.Response]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]


class MiMoClient:
    """Bounded retries without secret or response-body leakage."""

    def __init__(
        self,
        settings: Settings,
        *,
        post: HttpPost = httpx.post,
        clock: Clock = monotonic,
        sleeper: Sleeper = sleep,
    ) -> None:
        self._api_key = settings.model_api_key.get_secret_value()
        self._base_url = str(settings.model_base_url).rstrip("/")
        self._model_name = settings.model_name
        self._timeout_seconds = settings.model_timeout_seconds
        self._post = post
        self._clock = clock
        self._sleeper = sleeper

    def generate(self, request: AnswerModelRequest) -> AnswerModelResponse:
        body = self._build_request_body(request)
        url = f"{self._base_url}/chat/completions"
        headers = {
            "api-key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        deadline = (
            self._clock()
            + self._timeout_seconds
            + MAX_RETRY_DELAY_SECONDS
        )
        attempts: list[AnswerModelAttempt] = []
        last_error: ModelHttpError | ModelNetworkError | ModelTimeoutError | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            remaining_seconds = deadline - self._clock()
            if remaining_seconds <= 0:
                if last_error is None:
                    last_error = ModelTimeoutError(
                        "model request timed out",
                        phase="budget",
                    )
                _raise_with_attempts(last_error, attempts)
            try:
                response = self._post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=min(
                        self._timeout_seconds,
                        remaining_seconds,
                    ),
                )
            except httpx.RequestError as transport_error:
                domain_error, retry_reason = _map_transport_error(
                    transport_error
                )
                retry_delay = self._retry_delay(
                    attempt=attempt,
                    retry_reason=retry_reason,
                    retry_after_seconds=None,
                    deadline=deadline,
                )
                attempts.append(
                    _failed_attempt(
                        attempt=attempt,
                        retry_reason=(
                            retry_reason
                            if retry_delay is not None
                            else None
                        ),
                        retry_delay=retry_delay,
                        billing_uncertain=_transport_billing_uncertain(
                            domain_error
                        ),
                    )
                )
                if retry_delay is None:
                    _raise_with_attempts(domain_error, attempts)
                last_error = domain_error
                self._sleeper(retry_delay)
                continue

            if not 200 <= response.status_code < 300:
                domain_error = ModelHttpError(response.status_code)
                retry_reason = _http_retry_reason(response.status_code)
                retry_delay = self._retry_delay(
                    attempt=attempt,
                    retry_reason=retry_reason,
                    retry_after_seconds=_retry_after_seconds(response),
                    deadline=deadline,
                )
                attempts.append(
                    _failed_attempt(
                        attempt=attempt,
                        retry_reason=(
                            retry_reason
                            if retry_delay is not None
                            else None
                        ),
                        retry_delay=retry_delay,
                        billing_uncertain=retry_delay is not None,
                    )
                )
                if retry_delay is None:
                    _raise_with_attempts(domain_error, attempts)
                last_error = domain_error
                self._sleeper(retry_delay)
                continue

            attempts.append(
                AnswerModelAttempt(
                    attempt=attempt,
                    outcome="success",
                )
            )
            return self._extract_response(response).model_copy(
                update={"attempts": tuple(attempts)}
            )

        raise AssertionError("bounded model retry loop did not terminate")

    def _retry_delay(
        self,
        *,
        attempt: int,
        retry_reason: RetryReason | None,
        retry_after_seconds: float | None,
        deadline: float,
    ) -> float | None:
        if retry_reason is None or attempt >= MAX_ATTEMPTS:
            return None
        delay = (
            retry_after_seconds
            if retry_after_seconds is not None
            else DEFAULT_RETRY_DELAY_SECONDS
        )
        remaining_seconds = deadline - self._clock()
        if remaining_seconds <= delay:
            return None
        return delay

    def _build_request_body(
        self,
        request: AnswerModelRequest,
    ) -> dict[str, Any]:
        schema_text = json.dumps(
            request.response_schema,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        user_payload = json.dumps(
            request.user_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        system_content = (
            f"{request.system_prompt.rstrip()}\n\n"
            "输出必须符合以下 JSON Schema：\n"
            f"{schema_text}"
        )
        return {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_payload},
            ],
            "response_format": {"type": "json_object"},
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "temperature": 0,
            "stream": False,
            "thinking": {"type": "disabled"},
        }

    @staticmethod
    def _extract_response(response: httpx.Response) -> AnswerModelResponse:
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage", {})
        except (ValueError, KeyError, IndexError, TypeError):
            return AnswerModelResponse(content="")

        if not isinstance(content, str) or not isinstance(usage, dict):
            return AnswerModelResponse(content="")
        return AnswerModelResponse(
            content=content,
            prompt_tokens=_optional_non_negative_int(
                usage.get("prompt_tokens")
            ),
            completion_tokens=_optional_non_negative_int(
                usage.get("completion_tokens")
            ),
            total_tokens=_optional_non_negative_int(
                usage.get("total_tokens")
            ),
        )


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _http_retry_reason(status_code: int) -> RetryReason | None:
    if status_code not in RETRYABLE_HTTP_STATUSES:
        return None
    if status_code == 429:
        return "rate_limit"
    return "server_error"


def _map_transport_error(
    error: httpx.RequestError,
) -> tuple[
    ModelNetworkError | ModelTimeoutError,
    RetryReason | None,
]:
    if isinstance(error, httpx.ConnectTimeout):
        return (
            ModelTimeoutError("model request timed out", phase="connect"),
            "connect_timeout",
        )
    if isinstance(error, httpx.PoolTimeout):
        return (
            ModelTimeoutError("model request timed out", phase="pool"),
            "pool_timeout",
        )
    if isinstance(error, httpx.ReadTimeout):
        return ModelTimeoutError(
            "model request timed out",
            phase="read",
        ), None
    if isinstance(error, httpx.WriteTimeout):
        return ModelTimeoutError(
            "model request timed out",
            phase="write",
        ), None
    if isinstance(error, httpx.TimeoutException):
        return ModelTimeoutError(
            "model request timed out",
            phase="unknown",
        ), None
    if isinstance(error, httpx.ConnectError):
        return (
            ModelNetworkError(
                "model request failed before response",
                phase="connect",
            ),
            "connect_error",
        )
    if isinstance(error, httpx.ReadError):
        phase = "read"
    elif isinstance(error, httpx.WriteError):
        phase = "write"
    else:
        phase = "unknown"
    return ModelNetworkError(
        "model request failed before response",
        phase=phase,
    ), None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > 16 or not _RETRY_AFTER_PATTERN.fullmatch(
        normalized
    ):
        return None
    parsed = float(normalized)
    return min(parsed, MAX_RETRY_DELAY_SECONDS)


def _failed_attempt(
    *,
    attempt: int,
    retry_reason: RetryReason | None,
    retry_delay: float | None,
    billing_uncertain: bool,
) -> AnswerModelAttempt:
    return AnswerModelAttempt(
        attempt=attempt,
        outcome="error",
        retry_reason=retry_reason,
        retry_delay_ms=(
            round(retry_delay * 1000)
            if retry_delay is not None
            else None
        ),
        billing_uncertain=billing_uncertain,
    )


def _transport_billing_uncertain(
    error: ModelNetworkError | ModelTimeoutError,
) -> bool:
    return error.phase not in {"connect", "pool"}


def _raise_with_attempts(
    error: ModelHttpError | ModelNetworkError | ModelTimeoutError,
    attempts: list[AnswerModelAttempt],
) -> NoReturn:
    error.model_attempts = tuple(attempts)
    raise error
