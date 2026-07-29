"""MiMo OpenAI-compatible chat-completions adapter."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from cited_rag.config import Settings
from cited_rag.errors import (
    ModelHttpError,
    ModelNetworkError,
    ModelTimeoutError,
)
from cited_rag.model_client import AnswerModelRequest, AnswerModelResponse

MAX_COMPLETION_TOKENS = 800
HttpPost = Callable[..., httpx.Response]


class MiMoClient:
    """One request, no retry, no secret or response-body leakage."""

    def __init__(
        self,
        settings: Settings,
        *,
        post: HttpPost = httpx.post,
    ) -> None:
        self._api_key = settings.model_api_key.get_secret_value()
        self._base_url = str(settings.model_base_url).rstrip("/")
        self._model_name = settings.model_name
        self._timeout_seconds = settings.model_timeout_seconds
        self._post = post

    def generate(self, request: AnswerModelRequest) -> AnswerModelResponse:
        try:
            response = self._post(
                f"{self._base_url}/chat/completions",
                headers={
                    "api-key": self._api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=self._build_request_body(request),
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise ModelTimeoutError("model request timed out") from error
        except httpx.RequestError as error:
            raise ModelNetworkError("model request failed before response") from error

        if not 200 <= response.status_code < 300:
            raise ModelHttpError(response.status_code)

        return self._extract_response(response)

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
