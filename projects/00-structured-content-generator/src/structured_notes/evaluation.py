import json
from collections.abc import Callable, Iterable
from pathlib import Path

from structured_notes.errors import AppError
from structured_notes.model_client import ModelClient
from structured_notes.models import GenerationInput, LearningNote
from structured_notes.service import generate_note


def load_eval_cases(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_evaluation(
    cases: Iterable[dict[str, object]],
    client: ModelClient,
    *,
    system_prompt: str,
    prompt_version: str,
    model_name: str,
    progress_callback: Callable[[int, int, str, str], None] | None = None,
) -> dict[str, object]:
    case_list = list(cases)
    case_results: list[dict[str, object]] = []
    successful_notes: list[LearningNote] = []
    failures: list[dict[str, str]] = []

    for index, case in enumerate(case_list, start=1):
        case_id = str(case["id"])
        generation_input = GenerationInput.model_validate(case["input"])
        try:
            note = generate_note(
                generation_input,
                client,
                system_prompt=system_prompt,
            )
        except AppError as exc:
            failure = {
                "case_id": case_id,
                "code": exc.code.value,
            }
            failures.append(failure)
            case_results.append(
                {
                    "case_id": case_id,
                    "status": "failed",
                    "error": failure,
                }
            )
            if progress_callback is not None:
                progress_callback(
                    index,
                    len(case_list),
                    case_id,
                    "failed",
                )
            continue

        successful_notes.append(note)
        case_results.append(
            {
                "case_id": case_id,
                "status": "passed",
                "output": note.model_dump(mode="json"),
            }
        )
        if progress_callback is not None:
            progress_callback(
                index,
                len(case_list),
                case_id,
                "passed",
            )

    example_labels = [
        concept.example.label
        for note in successful_notes
        for concept in note.key_concepts
        if concept.example is not None
    ]
    schema_pass_rate = (
        len(successful_notes) / len(case_list) if case_list else None
    )
    example_label_rate = (
        sum(label == "生成示例" for label in example_labels) / len(example_labels)
        if example_labels
        else None
    )

    return {
        "prompt_version": prompt_version,
        "model_name": model_name,
        "case_count": len(case_list),
        "metrics": {
            "schema_pass_rate": schema_pass_rate,
            "generated_example_label_rate": example_label_rate,
            "fact_support_rate": None,
        },
        "failures": failures,
        "cases": case_results,
    }


def write_evaluation_result(result: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
