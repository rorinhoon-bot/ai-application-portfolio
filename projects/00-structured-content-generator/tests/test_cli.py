import json
from io import StringIO
from pathlib import Path

import pytest

from structured_notes.adapters import create_model_client
from structured_notes.cli import run
from structured_notes.config import Settings
from structured_notes.errors import AppError, ErrorCode
from structured_notes.models import ModelRequest, ModelResponse


def valid_settings() -> Settings:
    return Settings(
        _env_file=None,
        model_provider="fake-provider",
        model_api_key="test-only-key",
        model_base_url="https://example.com/v1",
        model_name="test-model",
    )


def valid_output_json() -> str:
    return json.dumps(
        {
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
        },
        ensure_ascii=False,
    )


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(content=self.content)


def run_cli(
    material_path: Path,
    client: FakeClient,
) -> tuple[int, StringIO, StringIO]:
    stdout = StringIO()
    stderr = StringIO()
    exit_code = run(
        [
            "generate",
            "--topic",
            "Transformer",
            "--material-file",
            str(material_path),
        ],
        settings_factory=valid_settings,
        client_factory=lambda settings: client,
        stdout=stdout,
        stderr=stderr,
    )
    return exit_code, stdout, stderr


def test_cli_success_writes_json_to_stdout(tmp_path: Path) -> None:
    material_path = tmp_path / "material.txt"
    material_path.write_text("a" * 100, encoding="utf-8")
    client = FakeClient(valid_output_json())

    exit_code, stdout, stderr = run_cli(material_path, client)

    output = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert output["title"] == "Transformer 基础"
    assert stderr.getvalue() == ""
    assert len(client.requests) == 1


def test_cli_material_file_error_writes_only_to_stderr(tmp_path: Path) -> None:
    client = FakeClient(valid_output_json())

    exit_code, stdout, stderr = run_cli(tmp_path / "missing.txt", client)

    error = json.loads(stderr.getvalue())
    assert exit_code == 2
    assert error["code"] == "MATERIAL_FILE_ERROR"
    assert stdout.getvalue() == ""
    assert client.requests == []


def test_cli_invalid_input_stops_before_creating_client(tmp_path: Path) -> None:
    material_path = tmp_path / "material.txt"
    material_path.write_text("a" * 99, encoding="utf-8")
    factory_called = False

    def client_factory(settings: Settings) -> FakeClient:
        nonlocal factory_called
        factory_called = True
        return FakeClient(valid_output_json())

    stderr = StringIO()
    exit_code = run(
        [
            "generate",
            "--topic",
            "Transformer",
            "--material-file",
            str(material_path),
        ],
        settings_factory=valid_settings,
        client_factory=client_factory,
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert json.loads(stderr.getvalue())["code"] == "INPUT_VALIDATION_ERROR"
    assert factory_called is False


def test_cli_missing_config_stops_before_creating_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material_path = tmp_path / "material.txt"
    material_path.write_text("a" * 100, encoding="utf-8")
    for name in (
        "MODEL_PROVIDER",
        "MODEL_API_KEY",
        "MODEL_BASE_URL",
        "MODEL_NAME",
    ):
        monkeypatch.delenv(name, raising=False)

    stderr = StringIO()
    exit_code = run(
        [
            "generate",
            "--topic",
            "Transformer",
            "--material-file",
            str(material_path),
        ],
        settings_factory=lambda: Settings(_env_file=None),
        client_factory=lambda settings: FakeClient(valid_output_json()),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert json.loads(stderr.getvalue())["code"] == "CONFIG_ERROR"


def test_cli_model_output_error_uses_exit_code_four(tmp_path: Path) -> None:
    material_path = tmp_path / "material.txt"
    material_path.write_text("a" * 100, encoding="utf-8")
    client = FakeClient("not-json")

    exit_code, stdout, stderr = run_cli(material_path, client)

    assert exit_code == 4
    assert json.loads(stderr.getvalue())["code"] == "INVALID_MODEL_JSON"
    assert stdout.getvalue() == ""


def test_cli_argument_error_is_json() -> None:
    stderr = StringIO()

    exit_code = run(
        ["generate"],
        settings_factory=valid_settings,
        client_factory=lambda settings: FakeClient(valid_output_json()),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert json.loads(stderr.getvalue())["code"] == "INPUT_VALIDATION_ERROR"


def test_unregistered_provider_fails_before_network() -> None:
    with pytest.raises(AppError) as exc_info:
        create_model_client(valid_settings())

    assert exc_info.value.code is ErrorCode.UNKNOWN_MODEL_PROVIDER
