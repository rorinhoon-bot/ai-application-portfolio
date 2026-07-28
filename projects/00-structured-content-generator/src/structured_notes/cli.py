import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from structured_notes.adapters import create_model_client
from structured_notes.config import Settings
from structured_notes.errors import AppError, ErrorCode, ExitCode
from structured_notes.model_client import ModelClient
from structured_notes.models import GenerationInput, LearnerLevel
from structured_notes.service import PROMPT_FILENAMES, generate_note, load_prompt

SettingsFactory = Callable[[], Settings]
ClientFactory = Callable[[Settings], ModelClient]


class CliUsageError(ValueError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliUsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="structured_notes")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--topic", required=True)
    generate_parser.add_argument("--material-file", required=True, type=Path)
    generate_parser.add_argument(
        "--learner-level",
        choices=[level.value for level in LearnerLevel],
        default=LearnerLevel.BEGINNER.value,
    )
    generate_parser.add_argument(
        "--prompt-version",
        choices=sorted(PROMPT_FILENAMES),
        default="improved_v1",
    )
    return parser


def run(
    argv: Sequence[str] | None = None,
    *,
    settings_factory: SettingsFactory = Settings,
    client_factory: ClientFactory = create_model_client,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output_stream = stdout if stdout is not None else sys.stdout
    error_stream = stderr if stderr is not None else sys.stderr

    try:
        try:
            args = build_parser().parse_args(argv)
        except CliUsageError as exc:
            raise AppError(
                ErrorCode.INPUT_VALIDATION_ERROR,
                f"命令行参数无效：{exc}",
                retryable=False,
                exit_code=ExitCode.INPUT_OR_CONFIG_ERROR,
            ) from exc

        material = _read_material(args.material_file)
        generation_input = _validate_input(args, material)
        settings = _load_settings(settings_factory)
        client = client_factory(settings)
        system_prompt = load_prompt(args.prompt_version)
        note = generate_note(
            generation_input,
            client,
            system_prompt=system_prompt,
        )
        print(
            json.dumps(
                note.model_dump(mode="json"),
                ensure_ascii=False,
            ),
            file=output_stream,
        )
        return int(ExitCode.SUCCESS)
    except AppError as exc:
        print(
            json.dumps(
                exc.to_payload().model_dump(mode="json"),
                ensure_ascii=False,
            ),
            file=error_stream,
        )
        return int(exc.exit_code)
    except Exception:
        error = AppError(
            ErrorCode.INTERNAL_ERROR,
            "程序发生内部错误。",
            retryable=False,
            exit_code=ExitCode.INTERNAL_ERROR,
        )
        print(
            json.dumps(
                error.to_payload().model_dump(mode="json"),
                ensure_ascii=False,
            ),
            file=error_stream,
        )
        return int(error.exit_code)


def _read_material(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AppError(
            ErrorCode.MATERIAL_FILE_ERROR,
            "无法读取 UTF-8 材料文件。",
            retryable=False,
            exit_code=ExitCode.INPUT_OR_CONFIG_ERROR,
        ) from exc


def _validate_input(args: argparse.Namespace, material: str) -> GenerationInput:
    try:
        return GenerationInput(
            topic=args.topic,
            material=material,
            learner_level=args.learner_level,
        )
    except ValidationError as exc:
        raise AppError(
            ErrorCode.INPUT_VALIDATION_ERROR,
            "输入内容不符合要求。",
            retryable=False,
            exit_code=ExitCode.INPUT_OR_CONFIG_ERROR,
        ) from exc


def _load_settings(settings_factory: SettingsFactory) -> Settings:
    try:
        return settings_factory()
    except ValidationError as exc:
        raise AppError(
            ErrorCode.CONFIG_ERROR,
            "模型配置缺失或无效。",
            retryable=False,
            exit_code=ExitCode.INPUT_OR_CONFIG_ERROR,
        ) from exc


def main() -> int:
    return run()
