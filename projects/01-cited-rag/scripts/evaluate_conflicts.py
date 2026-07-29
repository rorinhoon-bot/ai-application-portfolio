"""Run one locked cross-version evaluation set with no retries."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.cli import build_local_application  # noqa: E402
from cited_rag.errors import CitedRagError  # noqa: E402
from cited_rag.indexing import load_active_index  # noqa: E402

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evaluation-set",
        choices=(
            "conflict-v1",
            "conflict-v2",
            "ambiguous-conflict-v1",
        ),
        default="conflict-v1",
    )
    arguments = parser.parse_args()
    evaluation_set_id = arguments.evaluation_set
    set_path = (
        PROJECT_ROOT
        / "data"
        / "evaluation"
        / f"{evaluation_set_id}.json"
    )
    report_names = {
        "conflict-v1": "conflict-evaluation-report.json",
        "conflict-v2": "conflict-v2-evaluation-report.json",
        "ambiguous-conflict-v1": (
            "ambiguous-conflict-v1-evaluation-report.json"
        ),
    }
    report_path = PROJECT_ROOT / "data" / report_names[evaluation_set_id]
    if report_path.exists():
        raise FileExistsError("conflict evaluation report already exists")
    raw_set = set_path.read_bytes()
    evaluation = json.loads(raw_set)
    cases = evaluation["cases"]
    case_ids = [case["case_id"] for case in cases]
    if (
        evaluation["schema_version"] != "1"
        or evaluation["evaluation_set_id"] != evaluation_set_id
        or not 2 <= len(cases) <= 5
        or len(case_ids) != len(set(case_ids))
    ):
        raise ValueError("conflict evaluation set is invalid")
    _, manifest = load_active_index(
        index_root=PROJECT_ROOT / "data" / "indexes"
    )
    if (
        evaluation["index_fingerprint"]
        != manifest.index_fingerprint
    ):
        raise ValueError("conflict set does not match active index")

    application = build_local_application()
    results = []
    for case in cases:
        try:
            answer = application.answer(
                question=case["question"],
                python_version=None,
            )
            versions = sorted(
                {
                    citation.python_version
                    for citation in answer.citations
                }
            )
            correct = (
                answer.status == "conflict"
                and versions == ["3.13", "3.14"]
            )
            results.append(
                {
                    "case_id": case["case_id"],
                    "question": case["question"],
                    "expected_status": "conflict",
                    "observed_status": answer.status,
                    "cited_versions": versions,
                    "correct": correct,
                    "answer": answer.model_dump(mode="json"),
                    "error_code": None,
                    "error_reason": None,
                }
            )
        except CitedRagError as error:
            usage = getattr(error, "model_usage", (None, None, None))
            results.append(
                {
                    "case_id": case["case_id"],
                    "question": case["question"],
                    "expected_status": "conflict",
                    "observed_status": None,
                    "cited_versions": [],
                    "correct": False,
                    "answer": None,
                    "error_code": error.code,
                    "error_reason": error.reason,
                    "prompt_tokens": usage[0],
                    "completion_tokens": usage[1],
                    "total_tokens": usage[2],
                }
            )
        print(
            json.dumps(
                {
                    "case_id": results[-1]["case_id"],
                    "observed_status": results[-1]["observed_status"],
                    "cited_versions": results[-1]["cited_versions"],
                    "correct": results[-1]["correct"],
                    "error_code": results[-1]["error_code"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    successful_answers = [
        result["answer"]
        for result in results
        if result["answer"] is not None
    ]
    prompt_tokens = sum(
        answer["prompt_tokens"] or 0 for answer in successful_answers
    ) + sum(
        result.get("prompt_tokens") or 0
        for result in results
        if result["answer"] is None
    )
    completion_tokens = sum(
        answer["completion_tokens"] or 0
        for answer in successful_answers
    ) + sum(
        result.get("completion_tokens") or 0
        for result in results
        if result["answer"] is None
    )
    accuracy = sum(result["correct"] for result in results) / len(results)
    report = {
        "schema_version": "1",
        "evaluation_set_id": evaluation["evaluation_set_id"],
        "evaluation_set_sha256": sha256(raw_set).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "index_id": str(manifest.index_id),
        "build_id": str(manifest.build_id),
        "model": "mimo-v2.5",
        "temperature": 0,
        "api_call_count": len(cases),
        "automatic_retries": 0,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "conflict_accuracy": accuracy,
        "minimum_target": evaluation["minimum_target"],
        "target_met": accuracy >= evaluation["minimum_target"],
        "cases": results,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "conflict_accuracy": accuracy,
                "target_met": report["target_met"],
                "total_tokens": report["total_tokens"],
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["target_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
