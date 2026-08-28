from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import log2
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from cited_rag.errors import EvaluationError, RetrievalError
from cited_rag.evaluation import (
    evaluate_retrieval_v2,
    load_retrieval_evaluation_set,
    load_retrieval_evaluation_set_v2,
    make_retrieval_evaluation_set_v2_sha256,
)
from cited_rag.models import (
    IndexManifest,
    RetrievalEvaluationCaseResultV2,
    RetrievalEvaluationObservationV2,
    RetrievalEvaluationSetV2,
    RetrievalEvaluationReportV2,
    RetrievalQuery,
    RetrievalResult,
    RetrievalCandidate,
    RetrievedChunk,
    RetrievalRuntimeMetadataV2,
)
from cited_rag.retrieval import (
    BASELINE_DENSE_RETRIEVAL_CONFIG,
    HYBRID_RRF_RETRIEVAL_CONFIG,
)
from cited_rag.indexing import make_chunk_payload
from tests.test_retrieval import chunks
from scripts.evaluate_retrieval_v2 import _resolve_report_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXED_TIME = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)


def load_manifest() -> IndexManifest:
    report = json.loads(
        (PROJECT_ROOT / "data" / "index-build-report.json").read_text(
            encoding="utf-8"
        )
    )
    return IndexManifest.model_validate(report["index_manifest"])


def make_evaluation_set() -> RetrievalEvaluationSetV2:
    kinds = (
        ["semantic-paraphrase"] * 12
        + ["exact-identifier"] * 12
        + ["mixed-semantic-identifier"] * 10
        + ["version-specific"] * 8
        + ["known-hard"] * 8
    )
    return RetrievalEvaluationSetV2.model_validate(
        {
            "schema_version": "2",
            "evaluation_set_id": "retrieval-v2-test",
            "index_fingerprint": load_manifest().index_fingerprint,
            "top_k": 5,
            "candidate_k": 20,
            "authoring_method": "manual-from-verified-corpus",
            "cases": [
                {
                    "case_id": f"case-{number:02d}",
                    "question": f"固定问题 {number}",
                    "python_version": "3.14",
                    "case_kind": kind,
                    "split": (
                        "development" if number <= 30 else "locked-test"
                    ),
                    "relevant_chunk_ids": [
                        str(uuid5(NAMESPACE_URL, f"relevant-{number}"))
                    ],
                    "rationale": "固定人工证据。",
                }
                for number, kind in enumerate(kinds, start=1)
            ],
        }
    )


def runtime() -> RetrievalRuntimeMetadataV2:
    return RetrievalRuntimeMetadataV2(
        qdrant_profile="server",
        python_version="3.14.3",
        qdrant_server_version="1.19.0",
        qdrant_client_version="1.18.0",
        fastembed_version="0.8.0",
        model_revision="4" * 40,
        model_asset_bytes=1,
        collection_storage_bytes=1,
        docker_memory_bytes=1,
        logical_cpu_count=1,
        process_thread_count=1,
        cold_start_ms=1,
        candidate_count=20,
        external_api_calls=0,
    )


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


class MillisecondClock:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> int:
        current = self.value
        self.value += 1_000_000
        return current


def test_v2_set_enforces_exact_strata_and_splits() -> None:
    evaluation_set = make_evaluation_set()
    value = evaluation_set.model_dump(mode="json")
    value["cases"][0]["case_kind"] = "known-hard"

    with pytest.raises(ValidationError, match="case_kind counts"):
        RetrievalEvaluationSetV2.model_validate(value)


def test_fixed_v2_fixture_preserves_v1_questions_and_index_binding() -> None:
    evaluation_set = load_retrieval_evaluation_set_v2(
        PROJECT_ROOT / "data" / "evaluation" / "retrieval-v2.json"
    )
    old_set = load_retrieval_evaluation_set(
        PROJECT_ROOT / "data" / "evaluation" / "retrieval-v1.json"
    )
    old_questions = {case.case_id: case.question for case in old_set.cases}
    new_questions = {case.case_id: case.question for case in evaluation_set.cases}

    assert evaluation_set.index_fingerprint == load_manifest().index_fingerprint
    assert all(new_questions[case_id] == question for case_id, question in old_questions.items())
    assert make_retrieval_evaluation_set_v2_sha256(evaluation_set) == (
        "a3b30c755dc2a4036b9d715a9df2bd891bfb850ce2bc2c369b43447c2a8abd13"
    )


def test_v2_evaluator_reports_zero_quality_and_fixed_latency_protocol() -> None:
    manifest = load_manifest()
    report = evaluate_retrieval_v2(
        evaluation_set=make_evaluation_set(),
        retriever=EmptyRetriever(manifest),
        manifest=manifest,
        retrieval_config=BASELINE_DENSE_RETRIEVAL_CONFIG,
        generated_at=FIXED_TIME,
        runtime=runtime(),
        clock_ns=MillisecondClock(),
    )

    assert report.overall.case_count == 50
    assert report.overall.recall_at_5 == 0
    assert report.overall.mrr_at_5 == 0
    assert report.overall.ndcg_at_5 == 0
    assert report.overall.candidate_recall_at_20 is None
    assert report.latency.sample_count == 150
    assert report.latency.p50_ms == report.latency.p95_ms == 1
    assert report.candidate_metric_status.startswith("unavailable-")


def test_v2_evaluator_reports_available_hybrid_candidates() -> None:
    manifest = load_manifest()
    payloads = tuple(make_chunk_payload(chunk) for chunk in chunks())

    class CandidateRetriever:
        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            selected_payloads = tuple(
                payload
                for payload in payloads
                if query.python_version is None
                or payload.python_version == query.python_version
            )
            candidates = tuple(
                RetrievalCandidate(
                    rank=rank,
                    score=1 / (rank + 2),
                    payload=payload,
                    citation_url=f"{payload.source_url}#{payload.section_anchor}",
                    retrieval_reason="hybrid-rrf",
                    score_kind="rrf",
                    dense_rank=rank,
                )
                for rank, payload in enumerate(selected_payloads, start=1)
            )
            results = tuple(
                RetrievedChunk(
                    rank=item.rank,
                    score=item.score,
                    payload=item.payload,
                    citation_url=item.citation_url,
                    retrieval_reason="hybrid-rrf",
                    score_kind="rrf",
                )
                for item in candidates
            )
            return RetrievalResult(
                query=query,
                retrieval_config=HYBRID_RRF_RETRIEVAL_CONFIG,
                index_id=manifest.index_id,
                build_id=manifest.build_id,
                collection_name=manifest.collection_name,
                results=results,
                candidates=candidates,
            )

    report = evaluate_retrieval_v2(
        evaluation_set=make_evaluation_set(),
        retriever=CandidateRetriever(),
        manifest=manifest,
        retrieval_config=HYBRID_RRF_RETRIEVAL_CONFIG,
        generated_at=FIXED_TIME,
        runtime=runtime(),
        clock_ns=MillisecondClock(),
    )

    assert report.candidate_metric_status == "available"
    assert report.overall.candidate_recall_at_20 == 0
    assert all(case.candidates is not None for case in report.cases)


def test_v2_case_contract_recomputes_rr_and_binary_ndcg() -> None:
    relevant = uuid5(NAMESPACE_URL, "relevant")
    observations = tuple(
        RetrievalEvaluationObservationV2(
            rank=rank,
            score=1 / rank,
            chunk_id=(
                relevant
                if rank == 2
                else uuid5(NAMESPACE_URL, f"other-{rank}")
            ),
            source_id="source-one",
            python_version="3.14",
            section_anchor=f"anchor-{rank}",
            retrieval_reason="dense",
        )
        for rank in range(1, 4)
    )
    valid = {
        "case_id": "metric-case",
        "question": "固定问题",
        "python_version": "3.14",
        "case_kind": "known-hard",
        "split": "development",
        "relevant_chunk_ids": [str(relevant)],
        "retrieved": [item.model_dump(mode="json") for item in observations],
        "candidates": None,
        "hit_at_5": True,
        "first_relevant_rank_at_5": 2,
        "reciprocal_rank_at_5": 0.5,
        "ndcg_at_5": 1 / log2(3),
        "candidate_hit_at_20": None,
        "first_relevant_rank_at_20": None,
        "latency_ms": [1, 1, 1],
    }

    RetrievalEvaluationCaseResultV2.model_validate(valid)
    with pytest.raises(ValidationError, match="ndcg_at_5"):
        RetrievalEvaluationCaseResultV2.model_validate(
            {**valid, "ndcg_at_5": 1.0}
        )


def test_v1_fixture_and_reports_remain_byte_identical() -> None:
    expected = {
        "data/evaluation/retrieval-v1.json": (
            "bc65366079c32e5a348986cf6ebe1ab7b3b1c2f3aaf5e7a97ee8abae92d1e4cc"
        ),
        "data/retrieval-evaluation-report.json": (
            "e728afcb6d2f1286a14e46776d99f64ee77df6201e9d1bc877b0f95fad91b3c4"
        ),
        "data/retrieval-evaluation-optimized-report.json": (
            "3b6afa1c0892b1101043253e17a7d98f8147546fff23d75b62f5d1fc4316777c"
        ),
    }

    for relative_path, expected_sha256 in expected.items():
        assert sha256((PROJECT_ROOT / relative_path).read_bytes()).hexdigest() == (
            expected_sha256
        )


def test_real_v2_reports_match_fixed_quality_and_measurement_protocol() -> None:
    artifact_sha256 = {
        "data/evaluation/retrieval-v2.json": (
            "30d789ee100a145280be8e499d2b2be04ef99d0cb2b1e5ddcf0d1ed7216e0b7c"
        ),
        "data/retrieval-v2-dense-report.json": (
            "3def9db243f39a4f2d7282de5d6c44e269804dba0363f1fce340216595bb8394"
        ),
        "data/retrieval-v2-dense-plus-identifiers-report.json": (
            "c91c42bbf359810e8fe9c08a04a8aac27e2dfad8d7221f726d116652d28bf19c"
        ),
    }
    for relative_path, expected_sha256 in artifact_sha256.items():
        assert sha256((PROJECT_ROOT / relative_path).read_bytes()).hexdigest() == (
            expected_sha256
        )

    expected = {
        "data/retrieval-v2-dense-report.json": (
            "dense",
            42,
            0.84,
            0.6313333333333333,
            0.6839867307981148,
            5303.8008,
        ),
        "data/retrieval-v2-dense-plus-identifiers-report.json": (
            "dense-plus-identifiers",
            45,
            0.9,
            0.7216666666666667,
            0.7672804922758361,
            5802.3314,
        ),
    }

    for relative_path, values in expected.items():
        report = RetrievalEvaluationReportV2.model_validate_json(
            (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        )
        mode, hits, recall, mrr, ndcg, p95 = values
        assert report.retrieval_config.mode == mode
        assert (
            report.overall.hit_count,
            report.overall.recall_at_5,
            report.overall.mrr_at_5,
            report.overall.ndcg_at_5,
            report.latency.p95_ms,
        ) == (hits, recall, mrr, ndcg, p95)
        assert report.evaluation_set_sha256 == (
            "a3b30c755dc2a4036b9d715a9df2bd891bfb850ce2bc2c369b43447c2a8abd13"
        )
        assert report.latency.sample_count == 150
        assert report.overall.candidate_recall_at_20 is None
        assert report.runtime.external_api_calls == 0


def test_v2_report_rejects_falsified_latency_and_candidate_aggregate() -> None:
    report = json.loads(
        (PROJECT_ROOT / "data" / "retrieval-v2-dense-report.json").read_text(
            encoding="utf-8"
        )
    )
    falsified_latency = json.loads(json.dumps(report))
    falsified_latency["latency"]["p95_ms"] += 1
    falsified_candidate = json.loads(json.dumps(report))
    falsified_candidate["by_split"][0]["candidate_recall_at_20"] = 0.0

    with pytest.raises(ValidationError, match="latency summary"):
        RetrievalEvaluationReportV2.model_validate(falsified_latency)
    with pytest.raises(ValidationError, match="candidate aggregate"):
        RetrievalEvaluationReportV2.model_validate(falsified_candidate)


def test_v2_rejects_mixed_success_and_error_repetitions() -> None:
    manifest = load_manifest()

    class UnstableRetriever(EmptyRetriever):
        def __init__(self, manifest: IndexManifest) -> None:
            super().__init__(manifest)
            self.calls = 0

        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            self.calls += 1
            if self.calls == 6:
                raise RetrievalError("synthetic unstable failure")
            return super().retrieve(query)

    with pytest.raises(EvaluationError, match="outcome changed"):
        evaluate_retrieval_v2(
            evaluation_set=make_evaluation_set(),
            retriever=UnstableRetriever(manifest),
            manifest=manifest,
            retrieval_config=BASELINE_DENSE_RETRIEVAL_CONFIG,
            generated_at=FIXED_TIME,
            runtime=runtime(),
            clock_ns=MillisecondClock(),
        )


def test_v2_runner_allows_only_new_json_paths_inside_project() -> None:
    path = _resolve_report_path(
        mode="dense",
        requested=Path("data/retrieval-v2-dense-rerun.json"),
    )

    assert path == PROJECT_ROOT / "data" / "retrieval-v2-dense-rerun.json"
    with pytest.raises(ValueError, match="inside project root"):
        _resolve_report_path(
            mode="dense",
            requested=PROJECT_ROOT.parent / "escaped.json",
        )
    with pytest.raises(ValueError, match=".json suffix"):
        _resolve_report_path(
            mode="dense",
            requested=Path("data/report.txt"),
        )
