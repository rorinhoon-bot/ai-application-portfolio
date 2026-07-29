"""Run the locked MiMo answer/refusal set with resumable five-call batches."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from typing import Any

from pydantic import ValidationError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ["HF_HUB_OFFLINE"] = "1"

from cited_rag.adapters import create_answer_model_client  # noqa: E402
from cited_rag.adapters.fastembed_local import (  # noqa: E402
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.answering import AnsweringService  # noqa: E402
from cited_rag.config import Settings  # noqa: E402
from cited_rag.embedding import EmbeddingService  # noqa: E402
from cited_rag.errors import CitedRagError  # noqa: E402
from cited_rag.indexing import load_active_index  # noqa: E402
from cited_rag.model_assets import load_verified_model_assets  # noqa: E402
from cited_rag.models import (  # noqa: E402
    AnswerEvaluationCaseResult,
    AnswerEvaluationReport,
    AnswerEvaluationSet,
)
from cited_rag.retrieval import (  # noqa: E402
    DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    QdrantRetrievalService,
    make_retrieval_query,
)

MODEL_REPORT = PROJECT_ROOT / "data" / "model-assets.json"
INDEX_ROOT = PROJECT_ROOT / "data" / "indexes"
EVALUATION_SET_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "answering-v1.json"
)
PROGRESS_PATH = PROJECT_ROOT / "data" / "answering-evaluation-progress.json"
REPORT_PATH = PROJECT_ROOT / "data" / "answering-evaluation-report.json"
MAX_NEW_CALLS_PER_RUN = 5


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform up to five new real API calls",
    )
    parser.add_argument(
        "--diagnose-case-id",
        help="rerun one locked case without changing its locked result",
    )
    parser.add_argument(
        "--set-id",
        choices=("answering-v1", "answering-v2", "answering-v3"),
        default="answering-v1",
    )
    arguments = parser.parse_args()

    evaluation_set_path = (
        EVALUATION_SET_PATH
        if arguments.set_id == "answering-v1"
        else (
            PROJECT_ROOT
            / "data"
            / "evaluation"
            / f"{arguments.set_id}.json"
        )
    )
    progress_path = (
        PROGRESS_PATH
        if arguments.set_id == "answering-v1"
        else PROJECT_ROOT / "data" / f"{arguments.set_id}-progress.json"
    )
    report_path = (
        REPORT_PATH
        if arguments.set_id == "answering-v1"
        else PROJECT_ROOT / "data" / f"{arguments.set_id}-report.json"
    )
    raw_set = evaluation_set_path.read_bytes()
    evaluation_set = AnswerEvaluationSet.model_validate_json(raw_set)
    set_sha256 = sha256(raw_set).hexdigest()
    _, index_manifest = load_active_index(index_root=INDEX_ROOT)
    if (
        evaluation_set.index_fingerprint
        != index_manifest.index_fingerprint
    ):
        raise ValueError("answer evaluation set does not match active index")
    if arguments.diagnose_case_id:
        if not arguments.execute:
            raise ValueError("--diagnose-case-id requires --execute")
        matches = [
            case
            for case in evaluation_set.cases
            if case.case_id == arguments.diagnose_case_id
        ]
        if len(matches) != 1:
            raise ValueError("diagnostic case_id is unknown")
        diagnostic_path = (
            PROJECT_ROOT
            / "data"
            / f"answer-diagnostic-{matches[0].case_id}.json"
        )
        if diagnostic_path.exists():
            raise ValueError("diagnostic report already exists")
        settings = Settings(_env_file=PROJECT_ROOT / ".env")
        diagnostic, api_call_attempted = _run_case(
            case=matches[0],
            retriever=_make_retriever(),
            answerer=AnsweringService(
                model_client=create_answer_model_client(settings)
            ),
        )
        _write_json(
            diagnostic_path,
            {
                "schema_version": "1",
                "purpose": "diagnostic-only",
                "locked_result_unchanged": True,
                "api_call_attempted": api_call_attempted,
                "result": diagnostic.model_dump(mode="json"),
            },
        )
        print(
            json.dumps(
                {
                    "case_id": diagnostic.case_id,
                    "observed_status": diagnostic.observed_status,
                    "error_code": diagnostic.error_code,
                    "error_reason": diagnostic.error_reason,
                    "prompt_tokens": diagnostic.prompt_tokens,
                    "completion_tokens": diagnostic.completion_tokens,
                    "locked_result_unchanged": True,
                    "report": str(diagnostic_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if report_path.exists():
        print(
            json.dumps(
                {
                    "status": "complete",
                    "report": str(report_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    progress = _load_progress(
        evaluation_set=evaluation_set,
        set_sha256=set_sha256,
        progress_path=progress_path,
    )
    completed_ids = {
        item["case_id"] for item in progress["cases"]
    }
    remaining = [
        case
        for case in evaluation_set.cases
        if case.case_id not in completed_ids
    ]
    if not arguments.execute:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "evaluation_set_id": evaluation_set.evaluation_set_id,
                    "case_count": len(evaluation_set.cases),
                    "completed_count": len(completed_ids),
                    "remaining_count": len(remaining),
                    "next_batch_count": min(
                        len(remaining),
                        MAX_NEW_CALLS_PER_RUN,
                    ),
                    "maximum_new_api_calls": MAX_NEW_CALLS_PER_RUN,
                    "automatic_retries": 0,
                    "authorized_cny_limit": 5,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    settings = Settings(_env_file=PROJECT_ROOT / ".env")
    retriever = _make_retriever()
    answerer = AnsweringService(
        model_client=create_answer_model_client(settings)
    )
    for case in remaining[:MAX_NEW_CALLS_PER_RUN]:
        result, api_call_attempted = _run_case(
            case=case,
            retriever=retriever,
            answerer=answerer,
        )
        progress["cases"].append(result.model_dump(mode="json"))
        progress["api_call_count"] += int(api_call_attempted)
        _write_json(progress_path, progress)
        print(
            json.dumps(
                {
                    "case_id": result.case_id,
                    "expected_status": result.expected_status,
                    "observed_status": result.observed_status,
                    "correct": result.correct,
                    "error_code": result.error_code,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    if len(progress["cases"]) == len(evaluation_set.cases):
        report = _make_report(
            progress=progress,
            evaluation_set=evaluation_set,
            set_sha256=set_sha256,
            index_id=index_manifest.index_id,
            build_id=index_manifest.build_id,
            settings=settings,
        )
        _write_json(report_path, report.model_dump(mode="json"))
        print(
            json.dumps(
                {
                    "status": "complete",
                    "answerable_recall": report.answerable_recall,
                    "refusal_accuracy": report.refusal_accuracy,
                    "citation_binding_validity": (
                        report.citation_binding_validity
                    ),
                    "target_met": report.target_met,
                    "api_call_count": report.api_call_count,
                    "total_tokens": report.total_tokens,
                    "report": str(report_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            json.dumps(
                {
                    "status": "in_progress",
                    "completed_count": len(progress["cases"]),
                    "remaining_count": (
                        len(evaluation_set.cases)
                        - len(progress["cases"])
                    ),
                    "progress": str(progress_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


def _make_retriever() -> QdrantRetrievalService:
    assets = load_verified_model_assets(
        project_root=PROJECT_ROOT,
        report_path=MODEL_REPORT,
    )
    provider = FastEmbedLocalProvider(
        model_dir=assets.snapshot_path,
        config=assets.config,
    )
    token_counter = FastEmbedNoTruncationTokenCounter(
        model_dir=assets.snapshot_path
    )
    embedding_service = EmbeddingService.from_config(
        provider=provider,
        token_counter=token_counter,
        config=assets.config,
    )
    return QdrantRetrievalService(
        embedding_service=embedding_service,
        index_root=INDEX_ROOT,
        retrieval_config=DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    )


def _run_case(*, case, retriever, answerer):
    api_call_attempted = False
    try:
        retrieval = retriever.retrieve(
            make_retrieval_query(
                question=case.question,
                python_version=case.python_version,
            )
        )
        api_call_attempted = bool(retrieval.results)
        answer = answerer.answer(retrieval)
        return (
            AnswerEvaluationCaseResult(
                case_id=case.case_id,
                expected_status=case.expected_status,
                observed_status=answer.status,
                correct=answer.status == case.expected_status,
                answer=answer,
                error_code=None,
                error_reason=None,
                prompt_tokens=answer.prompt_tokens,
                completion_tokens=answer.completion_tokens,
                total_tokens=answer.total_tokens,
            ),
            api_call_attempted,
        )
    except CitedRagError as error:
        usage = getattr(error, "model_usage", (None, None, None))
        return (
            AnswerEvaluationCaseResult(
                case_id=case.case_id,
                expected_status=case.expected_status,
                observed_status=None,
                correct=False,
                answer=None,
                error_code=error.code,
                error_reason=error.reason,
                prompt_tokens=usage[0],
                completion_tokens=usage[1],
                total_tokens=usage[2],
            ),
            api_call_attempted,
        )


def _load_progress(
    *,
    evaluation_set: AnswerEvaluationSet,
    set_sha256: str,
    progress_path: Path,
) -> dict[str, Any]:
    if not progress_path.exists():
        return {
            "schema_version": "1",
            "evaluation_set_id": evaluation_set.evaluation_set_id,
            "evaluation_set_sha256": set_sha256,
            "api_call_count": 0,
            "automatic_retries": 0,
            "authorized_cny_limit": 5,
            "cases": [],
        }
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    if (
        progress.get("evaluation_set_id")
        != evaluation_set.evaluation_set_id
        or progress.get("evaluation_set_sha256") != set_sha256
        or progress.get("automatic_retries") != 0
        or progress.get("authorized_cny_limit") != 5
    ):
        raise ValueError("answer evaluation progress identity changed")
    for item in progress.get("cases", []):
        AnswerEvaluationCaseResult.model_validate(item)
    return progress


def _make_report(
    *,
    progress: dict[str, Any],
    evaluation_set: AnswerEvaluationSet,
    set_sha256: str,
    index_id,
    build_id,
    settings: Settings,
) -> AnswerEvaluationReport:
    cases = tuple(
        AnswerEvaluationCaseResult.model_validate(item)
        for item in progress["cases"]
    )
    answer_cases = [
        case
        for case in cases
        if case.expected_status == "answered"
    ]
    refusal_cases = [
        case
        for case in cases
        if case.expected_status == "refused"
    ]
    returned = [
        case.answer
        for case in cases
        if case.answer is not None
        and case.answer.status in {"answered", "conflict"}
    ]
    citation_binding_validity = (
        sum(bool(answer.citations) for answer in returned) / len(returned)
        if returned
        else 1.0
    )
    prompt_tokens = sum(
        (
            case.prompt_tokens
            if case.prompt_tokens is not None
            else (
                case.answer.prompt_tokens
                if case.answer is not None
                else 0
            )
        )
        or 0
        for case in cases
    )
    completion_tokens = sum(
        (
            case.completion_tokens
            if case.completion_tokens is not None
            else (
                case.answer.completion_tokens
                if case.answer is not None
                else 0
            )
        )
        or 0
        for case in cases
    )
    usage_response_count = sum(
        (
            case.total_tokens
            if case.total_tokens is not None
            else (
                case.answer.total_tokens
                if case.answer is not None
                else None
            )
        )
        is not None
        for case in cases
    )
    answerable_recall = (
        sum(case.correct for case in answer_cases) / len(answer_cases)
    )
    refusal_accuracy = (
        sum(case.correct for case in refusal_cases) / len(refusal_cases)
    )
    return AnswerEvaluationReport(
        schema_version="1",
        evaluation_set_id=evaluation_set.evaluation_set_id,
        evaluation_set_sha256=set_sha256,
        generated_at=datetime.now(timezone.utc),
        index_id=index_id,
        build_id=build_id,
        model_provider=settings.model_provider,
        model_name=settings.model_name,
        api_call_count=progress["api_call_count"],
        usage_response_count=usage_response_count,
        usage_complete=(
            usage_response_count == progress["api_call_count"]
        ),
        automatic_retries=0,
        authorized_cny_limit=5,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        answerable_recall=answerable_recall,
        refusal_accuracy=refusal_accuracy,
        citation_binding_validity=citation_binding_validity,
        minimum_class_target=evaluation_set.minimum_class_target,
        target_met=(
            answerable_recall >= evaluation_set.minimum_class_target
            and refusal_accuracy >= evaluation_set.minimum_class_target
            and citation_binding_validity == 1.0
        ),
        cases=cases,
    )


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, ValidationError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
