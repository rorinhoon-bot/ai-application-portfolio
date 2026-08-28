from copy import deepcopy
import json
from pathlib import Path
from uuid import UUID

import pytest

from cited_rag.models import RetrievalEvaluationReportV2
from scripts.activate_hybrid_index import require_passed_release_gate
from scripts.evaluate_hybrid_release_gate import (
    evaluate_failed_locked_run,
    evaluate_gate,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def report(path: str) -> RetrievalEvaluationReportV2:
    return RetrievalEvaluationReportV2.model_validate_json(
        (PROJECT_ROOT / path).read_text(encoding="utf-8")
    )


def test_gate_rejects_current_production_report_as_fake_hybrid() -> None:
    dense = report("data/retrieval-v2-dense-report.json")
    production = report("data/retrieval-v2-dense-plus-identifiers-report.json")

    result = evaluate_gate(dense=dense, production=production, hybrid=production)

    assert result["passed"] is False
    assert result["checks"]["candidate_metric_available"] is False


def test_gate_rejects_new_failure_even_when_aggregate_metrics_are_high() -> None:
    dense = report("data/retrieval-v2-dense-report.json")
    production = report("data/retrieval-v2-dense-plus-identifiers-report.json")
    value = deepcopy(json.loads((PROJECT_ROOT / "data/retrieval-v2-dense-plus-identifiers-report.json").read_text(encoding="utf-8")))
    value["candidate_metric_status"] = "available"
    for case in value["cases"]:
        case["candidates"] = case["retrieved"]
        case["candidate_hit_at_20"] = case["hit_at_5"]
        case["first_relevant_rank_at_20"] = case["first_relevant_rank_at_5"]
    for aggregate in [value["overall"], *value["by_split"], *value["by_case_kind"]]:
        matching = value["cases"] if aggregate["slice_name"] == "overall" else [
            case for case in value["cases"]
            if case.get("split") == aggregate["slice_name"] or case.get("case_kind") == aggregate["slice_name"]
        ]
        aggregate["candidate_recall_at_20"] = sum(case["candidate_hit_at_20"] for case in matching) / len(matching)
    hybrid = RetrievalEvaluationReportV2.model_validate(value)

    result = evaluate_gate(dense=dense, production=production, hybrid=hybrid)

    assert result["checks"]["no_new_dense_failure_case"] is False
    assert "template-string-314" in result["new_failure_case_ids"]


def test_gate_fails_closed_when_locked_ranking_is_unstable() -> None:
    build = json.loads(
        (PROJECT_ROOT / "data/hybrid-index-build-report.json").read_text(
            encoding="utf-8"
        )
    )
    candidate = build["candidate_manifest"]
    failure = {
        "candidate_index_id": candidate["index_id"],
        "candidate_build_id": candidate["build_id"],
        "candidate_collection_name": candidate["collection_name"],
        "external_api_calls": 0,
    }

    result = evaluate_failed_locked_run(failure=failure, build=build)

    assert result["passed"] is False
    assert result["metrics_available"] is False
    assert result["checks"]["repeated_ranking_stable"] is False
    assert result["checks"]["external_api_calls_zero"] is True


def test_activation_refuses_failed_or_mismatched_gate() -> None:
    build_id = UUID("740d893f-20e4-4677-8e7c-74a4d45de92e")

    with pytest.raises(RuntimeError, match="release gate did not pass"):
        require_passed_release_gate(
            gate={"passed": False, "candidate_build_id": str(build_id)},
            candidate_build_id=build_id,
        )
    with pytest.raises(RuntimeError, match="release gate did not pass"):
        require_passed_release_gate(
            gate={"passed": True, "candidate_build_id": str(UUID(int=0))},
            candidate_build_id=build_id,
        )
