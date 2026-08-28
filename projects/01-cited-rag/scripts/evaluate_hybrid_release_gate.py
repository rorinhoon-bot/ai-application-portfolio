"""Apply the frozen V2-C2 release gate to the one locked Hybrid report."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.models import RetrievalEvaluationReportV2  # noqa: E402

DENSE_REPORT = PROJECT_ROOT / "data" / "retrieval-v2-dense-report.json"
PRODUCTION_REPORT = PROJECT_ROOT / "data" / "retrieval-v2-dense-plus-identifiers-report.json"
HYBRID_REPORT = PROJECT_ROOT / "data" / "retrieval-v2-hybrid-rrf-report.json"
LOCKED_FAILURE_REPORT = PROJECT_ROOT / "data" / "hybrid-locked-run-failure.json"
BUILD_REPORT = PROJECT_ROOT / "data" / "hybrid-index-build-report.json"
GATE_REPORT = PROJECT_ROOT / "data" / "hybrid-release-gate.json"


def evaluate_gate(
    *,
    dense: RetrievalEvaluationReportV2,
    production: RetrievalEvaluationReportV2,
    hybrid: RetrievalEvaluationReportV2,
) -> dict[str, object]:
    dense_locked = _slice(dense, "locked-test")
    production_locked = _slice(production, "locked-test")
    hybrid_locked = _slice(hybrid, "locked-test")
    dense_hits = {case.case_id: case.hit_at_5 for case in dense.cases}
    new_failures = [
        case.case_id
        for case in hybrid.cases
        if dense_hits[case.case_id] and not case.hit_at_5
    ]
    checks = {
        "candidate_metric_available": hybrid.candidate_metric_status == "available",
        "locked_recall_not_below_dense": (
            hybrid_locked.recall_at_5 >= dense_locked.recall_at_5
        ),
        "locked_mrr_not_below_dense_minus_0_02": (
            hybrid_locked.mrr_at_5 >= dense_locked.mrr_at_5 - 0.02
        ),
        "locked_ndcg_not_below_dense_minus_0_02": (
            hybrid_locked.ndcg_at_5 >= dense_locked.ndcg_at_5 - 0.02
        ),
        "one_locked_metric_improves_dense_by_0_03": max(
            hybrid_locked.recall_at_5 - dense_locked.recall_at_5,
            hybrid_locked.mrr_at_5 - dense_locked.mrr_at_5,
            hybrid_locked.ndcg_at_5 - dense_locked.ndcg_at_5,
        ) >= 0.03,
        "locked_recall_meets_current_production_floor": (
            hybrid_locked.recall_at_5 >= 0.90
        ),
        "locked_mrr_meets_current_production_floor": (
            hybrid_locked.mrr_at_5 >= 0.6467
        ),
        "locked_ndcg_meets_current_production_floor": (
            hybrid_locked.ndcg_at_5 >= 0.7074
        ),
        "warm_p95_within_dense_2x": hybrid.latency.p95_ms <= dense.latency.p95_ms * 2,
        "no_new_dense_failure_case": not new_failures,
        "external_api_calls_zero": hybrid.runtime.external_api_calls == 0,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "new_failure_case_ids": new_failures,
        "dense_locked": dense_locked.model_dump(mode="json"),
        "production_locked": production_locked.model_dump(mode="json"),
        "hybrid_locked": hybrid_locked.model_dump(mode="json"),
        "hybrid_overall": hybrid.overall.model_dump(mode="json"),
        "latency": {
            "dense_p95_ms": dense.latency.p95_ms,
            "hybrid_p95_ms": hybrid.latency.p95_ms,
            "limit_ms": dense.latency.p95_ms * 2,
        },
    }


def evaluate_failed_locked_run(
    *,
    failure: dict[str, object],
    build: dict[str, object],
) -> dict[str, object]:
    """Make a fail-closed gate when locked evaluation produced no metrics."""

    candidate = build["candidate_manifest"]
    if not isinstance(candidate, dict):
        raise RuntimeError("Hybrid build report candidate manifest is invalid")
    for field in ("index_id", "build_id", "collection_name"):
        if failure.get(f"candidate_{field}") != candidate.get(field):
            raise RuntimeError(f"locked failure report candidate {field} mismatch")
    checks = {
        "locked_report_available": False,
        "repeated_ranking_stable": False,
        "candidate_metric_available": False,
        "locked_recall_not_below_dense": False,
        "locked_mrr_not_below_dense_minus_0_02": False,
        "locked_ndcg_not_below_dense_minus_0_02": False,
        "one_locked_metric_improves_dense_by_0_03": False,
        "locked_recall_meets_current_production_floor": False,
        "locked_mrr_meets_current_production_floor": False,
        "locked_ndcg_meets_current_production_floor": False,
        "warm_p95_within_dense_2x": False,
        "no_new_dense_failure_case": False,
        "external_api_calls_zero": failure.get("external_api_calls") == 0,
    }
    return {
        "passed": False,
        "checks": checks,
        "new_failure_case_ids": [],
        "locked_failure": failure,
        "metrics_available": False,
    }


def main() -> int:
    if GATE_REPORT.exists():
        raise FileExistsError("hybrid release gate report already exists")
    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    if HYBRID_REPORT.exists():
        dense = RetrievalEvaluationReportV2.model_validate_json(
            DENSE_REPORT.read_text(encoding="utf-8")
        )
        production = RetrievalEvaluationReportV2.model_validate_json(
            PRODUCTION_REPORT.read_text(encoding="utf-8")
        )
        hybrid = RetrievalEvaluationReportV2.model_validate_json(
            HYBRID_REPORT.read_text(encoding="utf-8")
        )
        if str(hybrid.build_id) != build["candidate_manifest"]["build_id"]:
            raise RuntimeError("Hybrid report does not match candidate build")
        result = evaluate_gate(dense=dense, production=production, hybrid=hybrid)
        candidate = {
            "index_id": str(hybrid.index_id),
            "build_id": str(hybrid.build_id),
            "collection_name": build["candidate_manifest"]["collection_name"],
        }
    else:
        if not LOCKED_FAILURE_REPORT.exists():
            raise FileNotFoundError(
                "neither Hybrid locked report nor locked failure report exists"
            )
        failure = json.loads(LOCKED_FAILURE_REPORT.read_text(encoding="utf-8"))
        result = evaluate_failed_locked_run(failure=failure, build=build)
        candidate = {
            "index_id": build["candidate_manifest"]["index_id"],
            "build_id": build["candidate_manifest"]["build_id"],
            "collection_name": build["candidate_manifest"]["collection_name"],
        }
    report = {
        "schema_version": "1",
        "slice": "V2-C2-release-gate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_index_id": candidate["index_id"],
        "candidate_build_id": candidate["build_id"],
        "candidate_collection_name": candidate["collection_name"],
        **result,
    }
    with GATE_REPORT.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


def _slice(report: RetrievalEvaluationReportV2, name: str):
    return next(item for item in report.by_split if item.slice_name == name)


if __name__ == "__main__":
    raise SystemExit(main())
