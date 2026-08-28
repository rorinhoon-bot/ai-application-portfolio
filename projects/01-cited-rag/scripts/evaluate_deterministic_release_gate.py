"""Evaluate the frozen V2-C2.1 release and C3 precondition gates."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA = PROJECT_ROOT / "data"
OUTPUT = DATA / "deterministic-fusion-release-gate.json"
REPORTS = {
    "stability": DATA / "retrieval-v2-client-rrf-stability-report.json",
    "dense": DATA / "retrieval-v3-dense-report.json",
    "production": DATA / "retrieval-v3-dense-plus-identifiers-report.json",
    "hybrid": DATA / "retrieval-v3-hybrid-client-rrf-v1-report.json",
}


def main() -> int:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite existing gate: {OUTPUT}")
    reports = {name: _load(path) for name, path in REPORTS.items()}
    stability = reports["stability"]
    dense = reports["dense"]
    production = reports["production"]
    hybrid = reports["hybrid"]
    evaluation_hashes = {
        report.get("evaluation_set_sha256")
        for report in (dense, production, hybrid)
    }
    production_hits = {
        case["case_id"] for case in production["cases"] if case["hit_at_5"]
    }
    hybrid_hits = {
        case["case_id"] for case in hybrid["cases"] if case["hit_at_5"]
    }
    new_failures = sorted(production_hits - hybrid_hits)
    dense_metrics = dense["overall"]
    production_metrics = production["overall"]
    hybrid_metrics = hybrid["overall"]
    improvements = {
        name: hybrid_metrics[name] - production_metrics[name]
        for name in ("recall_at_5", "mrr_at_5", "ndcg_at_5")
    }
    checks = {
        "old_v2_stability_passed": (
            stability.get("passed") is True
            and stability.get("stable_case_count") == 50
            and stability.get("quality_metrics_used_for_release") is False
        ),
        "same_frozen_v3_set": len(evaluation_hashes) == 1,
        "all_modes_repeat_stable": all(
            report.get("repeat_stable_case_count") == 20
            for report in (dense, production, hybrid)
        ),
        "candidate_recall_available": (
            hybrid.get("candidate_metric_status") == "available"
            and hybrid_metrics.get("candidate_recall_at_20") is not None
        ),
        "hybrid_recall_not_below_dense": (
            hybrid_metrics["recall_at_5"] >= dense_metrics["recall_at_5"]
        ),
        "hybrid_recall_not_below_production": (
            hybrid_metrics["recall_at_5"] >= production_metrics["recall_at_5"]
        ),
        "hybrid_recall_at_least_080": hybrid_metrics["recall_at_5"] >= 0.80,
        "hybrid_mrr_within_002_of_production": (
            hybrid_metrics["mrr_at_5"] >= production_metrics["mrr_at_5"] - 0.02
        ),
        "hybrid_ndcg_within_002_of_production": (
            hybrid_metrics["ndcg_at_5"] >= production_metrics["ndcg_at_5"] - 0.02
        ),
        "at_least_one_quality_gain_003": max(improvements.values()) >= 0.03,
        "no_new_production_hit_failures": not new_failures,
        "hybrid_p95_within_2x_production": (
            hybrid["latency"]["p95_ms"]
            <= production["latency"]["p95_ms"] * 2
        ),
        "payload_validation_100_percent": all(
            report.get("payload_validation_rate") == 1.0
            for report in (dense, production, hybrid)
        ),
        "external_api_calls_zero": (
            stability.get("external_api_calls") == 0
            and all(
                report["runtime"].get("external_api_calls") == 0
                for report in (dense, production, hybrid)
            )
        ),
    }
    ranks_six_to_twenty = [
        case["case_id"]
        for case in hybrid["cases"]
        if case["hit_at_5"] is False
        and case["first_relevant_rank_at_20"] is not None
    ]
    candidate_gap = (
        hybrid_metrics["candidate_recall_at_20"]
        - hybrid_metrics["recall_at_5"]
    )
    c3_checks = {
        "candidate_recall_gap_at_least_010": candidate_gap >= 0.10,
        "at_least_two_cases_rank_6_to_20": len(ranks_six_to_twenty) >= 2,
    }
    output = {
        "schema_version": "1",
        "gate_id": "deterministic-fusion-release-gate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_set_sha256": next(iter(evaluation_hashes)),
        "checks": checks,
        "passed": all(checks.values()),
        "metrics": {
            "dense": dense_metrics,
            "production": production_metrics,
            "hybrid": hybrid_metrics,
            "hybrid_minus_production": improvements,
            "production_p95_ms": production["latency"]["p95_ms"],
            "hybrid_p95_ms": hybrid["latency"]["p95_ms"],
        },
        "new_production_hit_failures": new_failures,
        "c3_precondition": {
            "checks": c3_checks,
            "candidate_recall_gap": candidate_gap,
            "rank_6_to_20_case_ids": ranks_six_to_twenty,
            "passed": all(c3_checks.values()),
        },
        "external_api_calls": 0,
    }
    with OUTPUT.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["passed"] else 1


def _load(path: Path) -> dict[str, object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"required gate evidence is invalid: {path}") from error


if __name__ == "__main__":
    raise SystemExit(main())
