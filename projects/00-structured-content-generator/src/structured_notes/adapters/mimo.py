import json
from collections.abc import Callable
from typing import Any

import httpx

from structured_notes.config import Settings
from structured_notes.model_client import (
    ModelHttpError,
    ModelNetworkError,
    ModelTimeoutError,
)
from structured_notes.models import ModelRequest, ModelResponse

MAX_COMPLETION_TOKENS = 4096
HttpPost = Callable[..., httpx.Response]


class MiMoClient:
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

    def generate(self, request: ModelRequest) -> ModelResponse:
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
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError() from exc
        except httpx.RequestError as exc:
            raise ModelNetworkError() from exc

        if not 200 <= response.status_code < 300:
            raise ModelHttpError(response.status_code)

        return ModelResponse(content=self._extract_content(response))

    def _build_request_body(self, request: ModelRequest) -> dict[str, Any]:
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
                {
                    "role": "system",
                    "content": system_content,
                },
                {
                    "role": "user",
                    "content": user_payload,
                },
            ],
            "response_format": {
                "type": "json_object",
            },
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "stream": False,
            "thinking": {
                "type": "disabled",
            },
        }

    @staticmethod
    def _extract_content(response: httpx.Response) -> str:
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            return ""

        return content if isinstance(content, str) else ""
