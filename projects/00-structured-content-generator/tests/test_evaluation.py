import json
from pathlib import Path

from structured_notes.evaluation import (
    load_eval_cases,
    run_evaluation,
    write_evaluation_result,
)
from structured_notes.models import ModelRequest, ModelResponse


def output_json(*, with_example: bool) -> str:
    example = (
        {
            "text": "阅读时重点关注相关句子。",
            "label": "生成示例",
        }
        if with_example
        else None
    )
    return json.dumps(
        {
            "title": "测试笔记",
            "summary": "测试总结。",
            "learning_objectives": [],
            "key_concepts": [
                {
                    "name": "测试概念",
                    "explanation": "测试解释。",
                    "example": example,
                    "common_mistakes": [],
                }
            ],
            "review_points": [],
            "quiz": [],
            "missing_information": [],
        },
        ensure_ascii=False,
    )


def eval_case(case_id: str) -> dict[str, object]:
    return {
        "id": case_id,
        "input": {
            "topic": "测试主题",
            "material": "a" * 100,
            "learner_level": "beginner",
        },
    }


class SequenceClient:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(content=self.contents.pop(0))


def test_run_evaluation_calculates_automatic_metrics() -> None:
    result = run_evaluation(
        [eval_case("case-1"), eval_case("case-2")],
        SequenceClient([output_json(with_example=True), "not-json"]),
        system_prompt="Follow the schema.",
        prompt_version="baseline_v1",
        model_name="fake-model",
    )

    assert result["case_count"] == 2
    assert result["metrics"] == {
        "schema_pass_rate": 0.5,
        "generated_example_label_rate": 1.0,
        "fact_support_rate": None,
    }
    assert result["failures"] == [
        {
            "case_id": "case-2",
            "code": "INVALID_MODEL_JSON",
        }
    ]


def test_run_evaluation_marks_example_metric_not_applicable() -> None:
    result = run_evaluation(
        [eval_case("case-1")],
        SequenceClient([output_json(with_example=False)]),
        system_prompt="Follow the schema.",
        prompt_version="improved_v1",
        model_name="fake-model",
    )

    assert result["metrics"]["generated_example_label_rate"] is None


def test_eval_case_loader_and_result_writer_round_trip(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(eval_case("case-1"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result_path = tmp_path / "results" / "automatic.json"
    result = {"metrics": {"schema_pass_rate": 1.0}}

    assert load_eval_cases(cases_path) == [eval_case("case-1")]

    write_evaluation_result(result, result_path)

    assert json.loads(result_path.read_text(encoding="utf-8")) == result
