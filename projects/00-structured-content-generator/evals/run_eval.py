import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from pydantic import ValidationError  # noqa: E402

from structured_notes.adapters import create_model_client  # noqa: E402
from structured_notes.config import Settings  # noqa: E402
from structured_notes.errors import AppError, ErrorCode, ExitCode  # noqa: E402
from structured_notes.evaluation import (  # noqa: E402
    load_eval_cases,
    run_evaluation,
    write_evaluation_result,
)
from structured_notes.service import PROMPT_FILENAMES, load_prompt  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prompt-version",
        choices=sorted(PROMPT_FILENAMES),
        required=True,
    )
    args = parser.parse_args()

    try:
        try:
            settings = Settings()
        except ValidationError as exc:
            raise AppError(
                ErrorCode.CONFIG_ERROR,
                "模型配置缺失或无效。",
                retryable=False,
                exit_code=ExitCode.INPUT_OR_CONFIG_ERROR,
            ) from exc

        client = create_model_client(settings)
        cases = load_eval_cases(PROJECT_ROOT / "evals" / "cases.jsonl")
        prompt = load_prompt(args.prompt_version)
        result = run_evaluation(
            cases,
            client,
            system_prompt=prompt,
            prompt_version=args.prompt_version,
            model_name=settings.model_name,
            progress_callback=lambda current, total, case_id, status: print(
                f"[{current}/{total}] {case_id}: {status}",
                flush=True,
            ),
        )
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        result_path = (
            PROJECT_ROOT
            / "evals"
            / "results"
            / f"{run_id}-{args.prompt_version}-automatic.json"
        )
        write_evaluation_result(result, result_path)
        print(result_path)
        return int(ExitCode.SUCCESS)
    except AppError as exc:
        print(
            json.dumps(
                exc.to_payload().model_dump(mode="json"),
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return int(exc.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
