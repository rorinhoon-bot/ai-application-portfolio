from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cited_rag.errors import IndexVersionMismatchError, RetrievalError
from cited_rag.evaluation import (
    evaluate_retrieval,
    load_retrieval_evaluation_set,
    make_retrieval_evaluation_set_sha256,
)
from cited_rag.models import (
    IndexManifest,
    RetrievalQuery,
    RetrievalResult,
)
from cited_rag.retrieval import BASELINE_DENSE_RETRIEVAL_CONFIG

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXED_TIME = datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc)


def load_manifest() -> IndexManifest:
    report = json.loads(
        (PROJECT_ROOT / "data" / "index-build-report.json").read_text(
            encoding="utf-8"
        )
    )
    return IndexManifest.model_validate(report["index_manifest"])


class EmptyRetriever:
    def __init__(self, manifest: IndexManifest) -> None:
        self.manifest = manifest

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        return RetrievalResult(
            query=query,
            retrieval_config=BASELINE_DENSE_RETRIEVAL_CONFIG,
            index_id=self.manifest.index_id,
            build_id=self.manifest.build_id,
            collection_name=self.manifest.collection_name,
            results=(),
        )


class ErrorRetriever:
    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        raise RetrievalError("synthetic retrieval failure")


def test_fixed_evaluation_fixture_is_bound_to_real_index() -> None:
    evaluation_set = load_retrieval_evaluation_set(
        PROJECT_ROOT / "data" / "evaluation" / "retrieval-v1.json"
    )
    manifest = load_manifest()

    assert len(evaluation_set.cases) == 15
    assert evaluation_set.index_fingerprint == manifest.index_fingerprint
    assert make_retrieval_evaluation_set_sha256(evaluation_set) == (
        "4832420a4470611d200737208ca682efbba142658f7e22876d15f13f0d2adedf"
    )


def test_evaluator_calculates_auditable_zero_hit_report() -> None:
    evaluation_set = load_retrieval_evaluation_set(
        PROJECT_ROOT / "data" / "evaluation" / "retrieval-v1.json"
    )
    manifest = load_manifest()

    report = evaluate_retrieval(
        evaluation_set=evaluation_set,
        retriever=EmptyRetriever(manifest),
        manifest=manifest,
        retrieval_config=BASELINE_DENSE_RETRIEVAL_CONFIG,
        generated_at=FIXED_TIME,
    )

    assert report.case_count == 15
    assert report.hit_count == 0
    assert report.recall_at_5 == 0
    assert not report.target_met
    assert all(not case.hit and case.error_code is None for case in report.cases)


def test_evaluator_records_stable_domain_errors_per_case() -> None:
    evaluation_set = load_retrieval_evaluation_set(
        PROJECT_ROOT / "data" / "evaluation" / "retrieval-v1.json"
    )
    manifest = load_manifest()

    report = evaluate_retrieval(
        evaluation_set=evaluation_set,
        retriever=ErrorRetriever(),
        manifest=manifest,
        retrieval_config=BASELINE_DENSE_RETRIEVAL_CONFIG,
        generated_at=FIXED_TIME,
    )

    assert report.hit_count == 0
    assert {
        (case.error_code, case.error_reason) for case in report.cases
    } == {("RETRIEVAL_ERROR", "synthetic retrieval failure")}


def test_evaluator_rejects_fixture_for_another_index() -> None:
    evaluation_set = load_retrieval_evaluation_set(
        PROJECT_ROOT / "data" / "evaluation" / "retrieval-v1.json"
    ).model_copy(update={"index_fingerprint": "0" * 64})

    with pytest.raises(
        IndexVersionMismatchError,
        match="evaluation set does not match",
    ):
        evaluate_retrieval(
            evaluation_set=evaluation_set,
            retriever=ErrorRetriever(),
            manifest=load_manifest(),
            retrieval_config=BASELINE_DENSE_RETRIEVAL_CONFIG,
            generated_at=FIXED_TIME,
        )
