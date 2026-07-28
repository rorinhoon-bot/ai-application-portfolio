import json
import time
from collections.abc import Callable
from json import JSONDecodeError
from pathlib import Path

from pydantic import ValidationError

from structured_notes.errors import AppError, ErrorCode, ExitCode
from structured_notes.model_client import (
    ModelClient,
    ModelHttpError,
    ModelNetworkError,
    ModelTimeoutError,
)
from structured_notes.models import GenerationInput, LearningNote, ModelRequest

MAX_REQUEST_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (1.0, 2.0)
PROMPT_FILENAMES = {
    "baseline_v1": "baseline_v1.txt",
    "improved_v1": "improved_v1.txt",
}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT_DIRECTORY = PROJECT_ROOT / "prompts"


def load_prompt(
    version: str,
    *,
    prompt_directory: Path = DEFAULT_PROMPT_DIRECTORY,
) -> str:
    filename = PROMPT_FILENAMES.get(version)
    if filename is None:
        raise AppError(
            ErrorCode.CONFIG_ERROR,
            "未知 Prompt 版本。",
            retryable=False,
            exit_code=ExitCode.INPUT_OR_CONFIG_ERROR,
        )

    try:
        prompt = (prompt_directory / filename).read_text(encoding="utf-8")
    except OSError as exc:
        raise AppError(
            ErrorCode.CONFIG_ERROR,
            "无法读取 Prompt 文件。",
            retryable=False,
            exit_code=ExitCode.INPUT_OR_CONFIG_ERROR,
        ) from exc

    if not prompt.strip():
        raise AppError(
            ErrorCode.CONFIG_ERROR,
            "Prompt 文件不能为空。",
            retryable=False,
            exit_code=ExitCode.INPUT_OR_CONFIG_ERROR,
        )

    return prompt


def generate_note(
    generation_input: GenerationInput,
    client: ModelClient,
    *,
    system_prompt: str,
    sleeper: Callable[[float], None] = time.sleep,
) -> LearningNote:
    request = ModelRequest(
        system_prompt=system_prompt,
        user_payload=generation_input.model_dump(mode="json"),
        response_schema=LearningNote.model_json_schema(),
    )
    response_content = _generate_with_retry(client, request, sleeper=sleeper)

    if not response_content.strip():
        raise AppError(
            ErrorCode.EMPTY_MODEL_RESPONSE,
            "模型返回了空内容。",
            retryable=False,
            exit_code=ExitCode.MODEL_OUTPUT_ERROR,
        )

    try:
        raw_output = json.loads(response_content)
    except JSONDecodeError as exc:
        raise AppError(
            ErrorCode.INVALID_MODEL_JSON,
            "模型返回内容不是合法 JSON。",
            retryable=False,
            exit_code=ExitCode.MODEL_OUTPUT_ERROR,
        ) from exc

    try:
        return LearningNote.model_validate(raw_output)
    except ValidationError as exc:
        raise AppError(
            ErrorCode.OUTPUT_SCHEMA_ERROR,
            "模型返回内容不符合输出 Schema。",
            retryable=False,
            exit_code=ExitCode.MODEL_OUTPUT_ERROR,
        ) from exc


def _generate_with_retry(
    client: ModelClient,
    request: ModelRequest,
    *,
    sleeper: Callable[[float], None],
) -> str:
    for attempt in range(MAX_REQUEST_ATTEMPTS):
        try:
            return client.generate(request).content
        except ModelTimeoutError as exc:
            if attempt < MAX_REQUEST_ATTEMPTS - 1:
                sleeper(RETRY_DELAYS_SECONDS[attempt])
                continue
            raise AppError(
                ErrorCode.MODEL_TIMEOUT,
                "模型请求超时。",
                retryable=True,
                exit_code=ExitCode.MODEL_API_ERROR,
            ) from exc
        except ModelNetworkError as exc:
            if attempt < MAX_REQUEST_ATTEMPTS - 1:
                sleeper(RETRY_DELAYS_SECONDS[attempt])
                continue
            raise AppError(
                ErrorCode.MODEL_NETWORK_ERROR,
                "无法连接模型 API。",
                retryable=True,
                exit_code=ExitCode.MODEL_API_ERROR,
            ) from exc
        except ModelHttpError as exc:
            retryable = exc.status_code == 429 or exc.status_code >= 500
            if retryable and attempt < MAX_REQUEST_ATTEMPTS - 1:
                sleeper(RETRY_DELAYS_SECONDS[attempt])
                continue
            raise AppError(
                ErrorCode.MODEL_HTTP_ERROR,
                f"模型 API 返回 HTTP {exc.status_code}。",
                retryable=retryable,
                exit_code=ExitCode.MODEL_API_ERROR,
            ) from exc

    raise AssertionError("retry loop ended without returning or raising")
