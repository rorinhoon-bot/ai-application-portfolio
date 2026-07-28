import json
from collections.abc import Callable
from pathlib import Path

import pytest

from structured_notes.errors import AppError, ErrorCode, ExitCode
from structured_notes.model_client import (
    ModelHttpError,
    ModelNetworkError,
    ModelTimeoutError,
)
from structured_notes.models import GenerationInput, ModelRequest, ModelResponse
from structured_notes.service import generate_note, load_prompt


def valid_output_data() -> dict[str, object]:
    return {
        "title": "Transformer 基础",
        "summary": "Transformer 使用注意力机制处理序列。",
        "learning_objectives": ["理解注意力机制"],
        "key_concepts": [
            {
                "name": "注意力机制",
                "explanation": "根据相关程度关注输入信息。",
                "example": None,
                "common_mistakes": [],
            }
        ],
        "review_points": ["注意力权重取决于输入。"],
        "quiz": [
            {
                "question": "注意力机制有什么作用？",
                "reference_answer": "根据相关程度关注输入信息。",
            }
        ],
        "missing_information": [],
    }


def valid_generation_input() -> GenerationInput:
    return GenerationInput(
        topic="Transformer",
        material="a" * 100,
        learner_level="beginner",
    )


class RecordingClient:
    def __init__(self, actions: list[object]) -> None:
        self.actions = actions
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return ModelResponse(content=str(action))


def test_load_prompt_reads_only_registered_version(tmp_path: Path) -> None:
    (tmp_path / "improved_v1.txt").write_text(
        "  trusted system prompt  ",
        encoding="utf-8",
    )

    prompt = load_prompt("improved_v1", prompt_directory=tmp_path)

    assert prompt == "  trusted system prompt  "


def test_load_prompt_rejects_unknown_version(tmp_path: Path) -> None:
    with pytest.raises(AppError) as exc_info:
        load_prompt("../../secret", prompt_directory=tmp_path)

    assert exc_info.value.code is ErrorCode.CONFIG_ERROR


def test_generate_note_returns_validated_learning_note() -> None:
    client = RecordingClient([json.dumps(valid_output_data(), ensure_ascii=False)])

    note = generate_note(
        valid_generation_input(),
        client,
        system_prompt="Follow the schema.",
    )

    assert note.title == "Transformer 基础"
    assert len(client.requests) == 1
    assert client.requests[0].user_payload["material"] == "a" * 100
    assert "material" not in client.requests[0].system_prompt
    assert client.requests[0].response_schema["title"] == "LearningNote"


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        ("", ErrorCode.EMPTY_MODEL_RESPONSE),
        ("not-json", ErrorCode.INVALID_MODEL_JSON),
        ('{"title":"incomplete"}', ErrorCode.OUTPUT_SCHEMA_ERROR),
    ],
)
def test_generate_note_rejects_invalid_model_output_without_retry(
    content: str,
    expected_code: ErrorCode,
) -> None:
    client = RecordingClient([content])

    with pytest.raises(AppError) as exc_info:
        generate_note(
            valid_generation_input(),
            client,
            system_prompt="Follow the schema.",
        )

    assert exc_info.value.code is expected_code
    assert exc_info.value.exit_code is ExitCode.MODEL_OUTPUT_ERROR
    assert exc_info.value.retryable is False
    assert len(client.requests) == 1


def test_generate_note_retries_timeout_then_succeeds() -> None:
    client = RecordingClient(
        [
            ModelTimeoutError(),
            json.dumps(valid_output_data(), ensure_ascii=False),
        ]
    )
    delays: list[float] = []

    note = generate_note(
        valid_generation_input(),
        client,
        system_prompt="Follow the schema.",
        sleeper=delays.append,
    )

    assert note.title == "Transformer 基础"
    assert len(client.requests) == 2
    assert delays == [1.0]


@pytest.mark.parametrize(
    ("error_factory", "expected_code"),
    [
        (ModelTimeoutError, ErrorCode.MODEL_TIMEOUT),
        (ModelNetworkError, ErrorCode.MODEL_NETWORK_ERROR),
        (lambda: ModelHttpError(429), ErrorCode.MODEL_HTTP_ERROR),
        (lambda: ModelHttpError(500), ErrorCode.MODEL_HTTP_ERROR),
    ],
)
def test_generate_note_stops_after_three_retryable_failures(
    error_factory: Callable[[], Exception],
    expected_code: ErrorCode,
) -> None:
    client = RecordingClient([error_factory(), error_factory(), error_factory()])
    delays: list[float] = []

    with pytest.raises(AppError) as exc_info:
        generate_note(
            valid_generation_input(),
            client,
            system_prompt="Follow the schema.",
            sleeper=delays.append,
        )

    assert exc_info.value.code is expected_code
    assert exc_info.value.retryable is True
    assert len(client.requests) == 3
    assert delays == [1.0, 2.0]


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_generate_note_does_not_retry_non_retryable_http_error(
    status_code: int,
) -> None:
    client = RecordingClient([ModelHttpError(status_code)])
    delays: list[float] = []

    with pytest.raises(AppError) as exc_info:
        generate_note(
            valid_generation_input(),
            client,
            system_prompt="Follow the schema.",
            sleeper=delays.append,
        )

    assert exc_info.value.code is ErrorCode.MODEL_HTTP_ERROR
    assert exc_info.value.retryable is False
    assert len(client.requests) == 1
    assert delays == []
