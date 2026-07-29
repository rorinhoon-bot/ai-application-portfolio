from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from cited_rag.models import (
    AnswerEvaluationCaseResult,
    AnswerEvaluationReport,
    AnswerEvaluationSet,
    AnswerResult,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_SET = (
    PROJECT_ROOT / "data" / "evaluation" / "answering-v1.json"
)
EVALUATION_REPORT = (
    PROJECT_ROOT / "data" / "answering-evaluation-report.json"
)


def result(
    case_id: str,
    *,
    expected: str,
    observed: str,
) -> AnswerEvaluationCaseResult:
    answer = AnswerResult(
        question=f"问题 {case_id}",
        status=observed,
        answer="证据不足。" if observed == "refused" else "回答。",
        citations=(),
        index_id=UUID("614f6c23-7c35-5832-8086-c29651d60866"),
        build_id=UUID("4facb454-cca4-476f-b623-fa29b40fcf00"),
        prompt_tokens=10,
        completion_tokens=2,
        total_tokens=12,
    )
    return AnswerEvaluationCaseResult(
        case_id=case_id,
        expected_status=expected,
        observed_status=observed,
        correct=expected == observed,
        answer=answer,
        error_code=None,
        error_reason=None,
        prompt_tokens=10,
        completion_tokens=2,
        total_tokens=12,
    )


def test_locked_answer_evaluation_set_is_balanced_and_index_bound() -> None:
    evaluation = AnswerEvaluationSet.model_validate_json(
        EVALUATION_SET.read_bytes()
    )

    assert evaluation.evaluation_set_id == "answering-v1"
    assert len(evaluation.cases) == 10
    assert sum(
        case.expected_status == "answered" for case in evaluation.cases
    ) == 5
    assert sum(
        case.expected_status == "refused" for case in evaluation.cases
    ) == 5
    assert evaluation.index_fingerprint == (
        "ea641fef238f3e74d6f64fa923feb53f9"
        "a7f36d88b082f14cafdcaabb541c4cd"
    )


def test_real_answer_evaluation_report_preserves_incomplete_usage() -> None:
    report = AnswerEvaluationReport.model_validate_json(
        EVALUATION_REPORT.read_bytes()
    )

    assert report.api_call_count == 10
    assert report.usage_response_count == 7
    assert report.usage_complete is False
    assert report.target_met is False


def test_case_result_requires_exactly_one_answer_or_error() -> None:
    with pytest.raises(ValidationError):
        AnswerEvaluationCaseResult(
            case_id="bad-case",
            expected_status="refused",
            observed_status=None,
            correct=False,
            answer=None,
            error_code=None,
            error_reason=None,
        )


def test_report_recomputes_class_metrics() -> None:
    cases = tuple(
        [
            result(
                f"answer-{index}",
                expected="answered",
                observed="refused",
            )
            for index in range(5)
        ]
        + [
            result(
                f"refuse-{index}",
                expected="refused",
                observed="refused",
            )
            for index in range(5)
        ]
    )

    report = AnswerEvaluationReport(
        schema_version="1",
        evaluation_set_id="answering-v1",
        evaluation_set_sha256="a" * 64,
        generated_at=datetime.now(timezone.utc),
        index_id=UUID("614f6c23-7c35-5832-8086-c29651d60866"),
        build_id=UUID("4facb454-cca4-476f-b623-fa29b40fcf00"),
        model_provider="mimo",
        model_name="mimo-v2.5",
        api_call_count=10,
        usage_response_count=10,
        usage_complete=True,
        automatic_retries=0,
        authorized_cny_limit=5,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        answerable_recall=0,
        refusal_accuracy=1,
        citation_binding_validity=1,
        minimum_class_target=0.8,
        target_met=False,
        cases=cases,
    )

    assert report.target_met is False
