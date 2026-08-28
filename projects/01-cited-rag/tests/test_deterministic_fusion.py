from __future__ import annotations

import json
from pathlib import Path

import pytest

from cited_rag.evaluation import (
    load_retrieval_evaluation_set_v2,
    load_retrieval_evaluation_set_v3,
    make_retrieval_evaluation_set_v3_sha256,
)
from cited_rag.models import RetrievalConfig, RetrievalEvaluationReportV2
from cited_rag.retrieval import HYBRID_CLIENT_RRF_RETRIEVAL_CONFIG
from scripts.activate_deterministic_index import require_deterministic_release_gate
from scripts import evaluate_retrieval_v3

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_deterministic_config_identity_is_fully_frozen() -> None:
    config = HYBRID_CLIENT_RRF_RETRIEVAL_CONFIG

    assert config.schema_version == "3"
    assert config.mode == "hybrid-client-rrf-v1"
    assert config.dense_exact is True
    assert config.lane_candidate_count == 20
    assert config.tie_window_initial_limit == 64
    assert config.tie_window_growth_factor == 2
    assert config.tie_window_cap == "manifest-point-count"
    assert config.rrf_rank_base == "zero-based"
    assert config.rrf_arithmetic == "fraction-exact"


def test_old_retrieval_configs_and_v2_reports_still_parse() -> None:
    for path in (
        PROJECT_ROOT / "data" / "retrieval-v2-dense-report.json",
        PROJECT_ROOT / "data" / "retrieval-v2-dense-plus-identifiers-report.json",
    ):
        report = RetrievalEvaluationReportV2.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        assert report.retrieval_config.schema_version == "1"
    old_hybrid = json.loads(
        (PROJECT_ROOT / "data" / "retrieval-v2-hybrid-development-report.json")
        .read_text(encoding="utf-8")
    )["retrieval_config"]
    assert RetrievalConfig.model_validate(old_hybrid).mode == "hybrid-rrf"


def test_v3_is_fresh_stratified_and_semantically_frozen() -> None:
    v2 = load_retrieval_evaluation_set_v2(
        PROJECT_ROOT / "data" / "evaluation" / "retrieval-v2.json"
    )
    v3 = load_retrieval_evaluation_set_v3(
        PROJECT_ROOT / "data" / "evaluation" / "retrieval-v3.json"
    )

    assert len(v3.cases) == 20
    assert make_retrieval_evaluation_set_v3_sha256(v3) == (
        "689873c28f5b9528a9d5b32c73e1cbac80fcfa9abe5aa6cb12057641235b4c01"
    )
    assert {case.question for case in v2.cases}.isdisjoint(
        case.question for case in v3.cases
    )
    v2_chunks = {
        chunk_id for case in v2.cases for chunk_id in case.relevant_chunk_ids
    }
    v3_chunks = {
        chunk_id for case in v3.cases for chunk_id in case.relevant_chunk_ids
    }
    assert v2_chunks.isdisjoint(v3_chunks)


def test_v3_evidence_was_frozen_before_queries() -> None:
    audit = json.loads(
        (PROJECT_ROOT / "data" / "retrieval-v3-evidence-audit.json")
        .read_text(encoding="utf-8")
    )

    assert audit["passed"] is True
    assert audit["query_runs_before_freeze"] == 0
    assert audit["authoring_used_retrieval_top_k"] is False
    assert audit["verified_payload_count"] == 20
    assert audit["question_overlap_with_v2_count"] == 0
    assert audit["relevant_chunk_overlap_with_v2_count"] == 0


def test_v3_runner_refuses_out_of_order_and_overwrite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reports = {
        mode: tmp_path / f"{mode}.json"
        for mode in evaluate_retrieval_v3.MODES
    }
    monkeypatch.setattr(evaluate_retrieval_v3, "REPORTS", reports)

    with pytest.raises(SystemExit, match="missing: dense"):
        evaluate_retrieval_v3._enforce_frozen_order("dense-plus-identifiers")
    reports["dense"].write_text("{}", encoding="utf-8")
    evaluate_retrieval_v3._enforce_frozen_order("dense-plus-identifiers")
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        evaluate_retrieval_v3._enforce_frozen_order("dense")


def test_release_gate_passes_exact_candidate_and_c3_remains_closed() -> None:
    gate = json.loads(
        (PROJECT_ROOT / "data" / "deterministic-fusion-release-gate.json")
        .read_text(encoding="utf-8")
    )
    hybrid = json.loads(
        (
            PROJECT_ROOT
            / "data"
            / "retrieval-v3-hybrid-client-rrf-v1-report.json"
        ).read_text(encoding="utf-8")
    )
    build = json.loads(
        (PROJECT_ROOT / "data" / "hybrid-index-build-report.json")
        .read_text(encoding="utf-8")
    )
    from cited_rag.models import IndexManifest

    candidate = IndexManifest.model_validate(build["candidate_manifest"])

    assert gate["passed"] is True
    assert all(gate["checks"].values())
    assert gate["c3_precondition"]["passed"] is False
    require_deterministic_release_gate(
        gate=gate,
        hybrid_report=hybrid,
        candidate=candidate,
    )


def test_activation_refuses_failed_or_mismatched_deterministic_gate() -> None:
    gate = json.loads(
        (PROJECT_ROOT / "data" / "deterministic-fusion-release-gate.json")
        .read_text(encoding="utf-8")
    )
    hybrid = json.loads(
        (
            PROJECT_ROOT
            / "data"
            / "retrieval-v3-hybrid-client-rrf-v1-report.json"
        ).read_text(encoding="utf-8")
    )
    build = json.loads(
        (PROJECT_ROOT / "data" / "hybrid-index-build-report.json")
        .read_text(encoding="utf-8")
    )
    from cited_rag.models import IndexManifest

    candidate = IndexManifest.model_validate(build["candidate_manifest"])
    failed = {**gate, "passed": False}
    mismatched = {**hybrid, "build_id": "00000000-0000-4000-8000-000000000000"}

    with pytest.raises(RuntimeError, match="release gate did not pass"):
        require_deterministic_release_gate(
            gate=failed,
            hybrid_report=hybrid,
            candidate=candidate,
        )
    with pytest.raises(RuntimeError, match="release gate did not pass"):
        require_deterministic_release_gate(
            gate=gate,
            hybrid_report=mismatched,
            candidate=candidate,
        )


def test_release_report_records_bounded_success_without_external_calls() -> None:
    report = json.loads(
        (PROJECT_ROOT / "data" / "deterministic-fusion-release-report.json")
        .read_text(encoding="utf-8")
    )

    assert report["status"] == "passed-and-activated"
    assert report["release_gate"]["passed_check_count"] == 14
    assert report["active_index"]["after"]["build_id"] == (
        "740d893f-20e4-4677-8e7c-74a4d45de92e"
    )
    assert report["api"]["image_tag"] == "cited-rag-api:v2-c2-1"
    assert report["qdrant_unchanged"]["container_id_before"] == (
        report["qdrant_unchanged"]["container_id_after"]
    )
    assert report["disk"]["within_cap"] is True
    assert report["external_api_calls"] == 0
    assert report["checks"]["mimo_called"] is False
    assert report["checks"]["qdrant_write_performed"] is False
