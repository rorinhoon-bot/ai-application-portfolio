"""Fixed, auditable Recall@5 evaluation for local retrieval."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from math import ceil, log2
from pathlib import Path
from time import perf_counter_ns
from typing import Callable, Protocol

from pydantic import ValidationError

from cited_rag.errors import (
    CitedRagError,
    EvaluationError,
    IndexVersionMismatchError,
)
from cited_rag.models import (
    IndexManifest,
    RetrievalConfig,
    RetrievalEvaluationCaseResult,
    RetrievalEvaluationObservation,
    RetrievalEvaluationReport,
    RetrievalEvaluationSet,
    RetrievalEvaluationCaseResultV2,
    RetrievalEvaluationObservationV2,
    RetrievalEvaluationReportV2,
    RetrievalEvaluationSetV2,
    RetrievalEvaluationSetV3,
    RetrievalLatencySummaryV2,
    RetrievalMetricAggregateV2,
    RetrievalRuntimeMetadataV2,
    RetrievalQuery,
    RetrievalResult,
)
from cited_rag.retrieval import make_retrieval_query


class Retriever(Protocol):
    """Minimal retrieval behavior needed by the evaluator."""

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Return ranked results for one validated query."""


def load_retrieval_evaluation_set(
    path: Path,
) -> RetrievalEvaluationSet:
    """Load one strict UTF-8 evaluation fixture."""

    try:
        text = path.read_text(encoding="utf-8")
        return RetrievalEvaluationSet.model_validate_json(text)
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise EvaluationError("retrieval evaluation set is invalid") from error


def make_retrieval_evaluation_set_sha256(
    evaluation_set: RetrievalEvaluationSet,
) -> str:
    """Hash semantic fixture content independent of JSON formatting."""

    canonical = json.dumps(
        evaluation_set.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def load_retrieval_evaluation_set_v2(path: Path) -> RetrievalEvaluationSetV2:
    """Load one strict UTF-8 V2 evaluation fixture."""

    try:
        text = path.read_text(encoding="utf-8")
        return RetrievalEvaluationSetV2.model_validate_json(text)
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise EvaluationError("V2 retrieval evaluation set is invalid") from error


def make_retrieval_evaluation_set_v2_sha256(
    evaluation_set: RetrievalEvaluationSetV2,
) -> str:
    """Hash V2 semantic fixture content independent of JSON formatting."""

    canonical = json.dumps(
        evaluation_set.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def load_retrieval_evaluation_set_v3(path: Path) -> RetrievalEvaluationSetV3:
    """Load one fresh, release-locked V3 evaluation fixture."""

    try:
        text = path.read_text(encoding="utf-8")
        return RetrievalEvaluationSetV3.model_validate_json(text)
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise EvaluationError("V3 retrieval evaluation set is invalid") from error


def make_retrieval_evaluation_set_v3_sha256(
    evaluation_set: RetrievalEvaluationSetV3,
) -> str:
    """Hash V3 semantic fixture content independent of JSON formatting."""

    canonical = json.dumps(
        evaluation_set.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def evaluate_retrieval(
    *,
    evaluation_set: RetrievalEvaluationSet,
    retriever: Retriever,
    manifest: IndexManifest,
    retrieval_config: RetrievalConfig,
    generated_at: datetime,
) -> RetrievalEvaluationReport:
    """Execute every fixed case and calculate binary Recall@5."""

    if evaluation_set.index_fingerprint != manifest.index_fingerprint:
        raise IndexVersionMismatchError(
            "evaluation set does not match active index fingerprint"
        )

    case_results: list[RetrievalEvaluationCaseResult] = []
    for case in evaluation_set.cases:
        query = make_retrieval_query(
            question=case.question,
            python_version=case.python_version,
            top_k=evaluation_set.top_k,
        )
        try:
            result = retriever.retrieve(query)
        except CitedRagError as error:
            case_results.append(
                RetrievalEvaluationCaseResult(
                    case_id=case.case_id,
                    question=case.question,
                    python_version=case.python_version,
                    relevant_chunk_ids=case.relevant_chunk_ids,
                    retrieved=(),
                    hit=False,
                    first_relevant_rank=None,
                    error_code=error.code,
                    error_reason=error.reason,
                )
            )
            continue

        if (
            result.index_id != manifest.index_id
            or result.build_id != manifest.build_id
            or result.collection_name != manifest.collection_name
        ):
            raise IndexVersionMismatchError(
                "retrieval result does not match evaluation index build"
            )
        if result.retrieval_config != retrieval_config:
            raise IndexVersionMismatchError(
                "retrieval result does not match evaluation configuration"
            )
        observations = tuple(
            RetrievalEvaluationObservation(
                rank=item.rank,
                score=item.score,
                chunk_id=item.payload.chunk_id,
                source_id=item.payload.source_id,
                python_version=item.payload.python_version,
                section_anchor=item.payload.section_anchor,
                retrieval_reason=item.retrieval_reason,
            )
            for item in result.results
        )
        relevant = set(case.relevant_chunk_ids)
        first_rank = next(
            (
                item.rank
                for item in observations
                if item.chunk_id in relevant
            ),
            None,
        )
        case_results.append(
            RetrievalEvaluationCaseResult(
                case_id=case.case_id,
                question=case.question,
                python_version=case.python_version,
                relevant_chunk_ids=case.relevant_chunk_ids,
                retrieved=observations,
                hit=first_rank is not None,
                first_relevant_rank=first_rank,
            )
        )

    hit_count = sum(case.hit for case in case_results)
    recall = hit_count / len(case_results)
    return RetrievalEvaluationReport(
        schema_version="1",
        evaluation_set_id=evaluation_set.evaluation_set_id,
        evaluation_set_sha256=make_retrieval_evaluation_set_sha256(
            evaluation_set
        ),
        generated_at=generated_at,
        index_id=manifest.index_id,
        build_id=manifest.build_id,
        index_fingerprint=manifest.index_fingerprint,
        top_k=evaluation_set.top_k,
        retrieval_config=retrieval_config,
        case_count=len(case_results),
        hit_count=hit_count,
        recall_at_5=recall,
        target_recall_at_5=0.8,
        target_met=recall >= 0.8,
        cases=tuple(case_results),
    )


def evaluate_retrieval_v2(
    *,
    evaluation_set: RetrievalEvaluationSetV2,
    retriever: Retriever,
    manifest: IndexManifest,
    retrieval_config: RetrievalConfig,
    generated_at: datetime,
    runtime: RetrievalRuntimeMetadataV2,
    clock_ns: Callable[[], int] = perf_counter_ns,
) -> RetrievalEvaluationReportV2:
    """Run the fixed V2 protocol with five warm-ups and three measurements."""

    if not _evaluation_set_matches_manifest(
        evaluation_fingerprint=evaluation_set.index_fingerprint,
        manifest=manifest,
    ):
        raise IndexVersionMismatchError(
            "V2 evaluation set does not match active index fingerprint"
        )

    for case in evaluation_set.cases[:5]:
        query = make_retrieval_query(
            question=case.question,
            python_version=case.python_version,
            top_k=evaluation_set.top_k,
        )
        try:
            result = retriever.retrieve(query)
        except CitedRagError as error:
            raise EvaluationError("V2 retrieval warm-up failed") from error
        _validate_v2_result_identity(
            result=result,
            manifest=manifest,
            retrieval_config=retrieval_config,
        )

    case_results: list[RetrievalEvaluationCaseResultV2] = []
    for case in evaluation_set.cases:
        query = make_retrieval_query(
            question=case.question,
            python_version=case.python_version,
            top_k=evaluation_set.top_k,
        )
        measured_results: list[RetrievalResult] = []
        measured_errors: list[CitedRagError] = []
        latency_ms: list[float] = []
        for _ in range(3):
            started_ns = clock_ns()
            try:
                result = retriever.retrieve(query)
            except CitedRagError as error:
                measured_errors.append(error)
            else:
                _validate_v2_result_identity(
                    result=result,
                    manifest=manifest,
                    retrieval_config=retrieval_config,
                )
                measured_results.append(result)
            finally:
                elapsed_ns = clock_ns() - started_ns
                if elapsed_ns < 0:
                    raise EvaluationError("V2 evaluation clock moved backwards")
                latency_ms.append(elapsed_ns / 1_000_000)

        if measured_errors:
            if measured_results or len(measured_errors) != 3:
                raise EvaluationError("V2 repeated retrieval outcome changed")
            first_error = measured_errors[0]
            if any(
                (error.code, error.reason)
                != (first_error.code, first_error.reason)
                for error in measured_errors[1:]
            ):
                raise EvaluationError("V2 repeated retrieval error changed")
            case_results.append(
                RetrievalEvaluationCaseResultV2(
                    case_id=case.case_id,
                    question=case.question,
                    python_version=case.python_version,
                    case_kind=case.case_kind,
                    split=case.split,
                    relevant_chunk_ids=case.relevant_chunk_ids,
                    retrieved=(),
                    candidates=None,
                    hit_at_5=False,
                    first_relevant_rank_at_5=None,
                    reciprocal_rank_at_5=0,
                    ndcg_at_5=0,
                    candidate_hit_at_20=None,
                    first_relevant_rank_at_20=None,
                    latency_ms=tuple(latency_ms),
                    error_code=first_error.code,
                    error_reason=first_error.reason,
                )
            )
            continue

        first_result = measured_results[0]
        first_signature = _make_result_signature(first_result)
        if any(
            _make_result_signature(result) != first_signature
            for result in measured_results[1:]
        ):
            raise EvaluationError("V2 repeated retrieval ranking changed")
        observations = tuple(
            RetrievalEvaluationObservationV2(
                rank=item.rank,
                score=item.score,
                chunk_id=item.payload.chunk_id,
                source_id=item.payload.source_id,
                python_version=item.payload.python_version,
                section_anchor=item.payload.section_anchor,
                retrieval_reason=item.retrieval_reason,
            )
            for item in first_result.results
        )
        candidate_observations = (
            tuple(
                RetrievalEvaluationObservationV2(
                    rank=item.rank,
                    score=item.score,
                    chunk_id=item.payload.chunk_id,
                    source_id=item.payload.source_id,
                    python_version=item.payload.python_version,
                    section_anchor=item.payload.section_anchor,
                    retrieval_reason=item.retrieval_reason,
                )
                for item in first_result.candidates
            )
            if first_result.candidates is not None
            else None
        )
        relevant = set(case.relevant_chunk_ids)
        first_rank = next(
            (item.rank for item in observations if item.chunk_id in relevant),
            None,
        )
        ndcg = _binary_ndcg_at_5(
            observations=observations,
            relevant_chunk_ids=relevant,
        )
        candidate_rank = (
            next(
                (
                    item.rank
                    for item in candidate_observations
                    if item.chunk_id in relevant
                ),
                None,
            )
            if candidate_observations is not None
            else None
        )
        case_results.append(
            RetrievalEvaluationCaseResultV2(
                case_id=case.case_id,
                question=case.question,
                python_version=case.python_version,
                case_kind=case.case_kind,
                split=case.split,
                relevant_chunk_ids=case.relevant_chunk_ids,
                retrieved=observations,
                candidates=candidate_observations,
                hit_at_5=first_rank is not None,
                first_relevant_rank_at_5=first_rank,
                reciprocal_rank_at_5=(
                    0.0 if first_rank is None else 1.0 / first_rank
                ),
                ndcg_at_5=ndcg,
                candidate_hit_at_20=(
                    candidate_rank is not None
                    if candidate_observations is not None
                    else None
                ),
                first_relevant_rank_at_20=candidate_rank,
                latency_ms=tuple(latency_ms),
            )
        )

    all_results = tuple(case_results)
    samples = sorted(
        sample for case in all_results for sample in case.latency_ms
    )
    return RetrievalEvaluationReportV2(
        schema_version="2",
        evaluation_set_id=evaluation_set.evaluation_set_id,
        evaluation_set_sha256=make_retrieval_evaluation_set_v2_sha256(
            evaluation_set
        ),
        generated_at=generated_at,
        index_id=manifest.index_id,
        build_id=manifest.build_id,
        index_fingerprint=manifest.index_fingerprint,
        top_k=evaluation_set.top_k,
        candidate_k=evaluation_set.candidate_k,
        retrieval_config=retrieval_config,
        candidate_metric_status=(
            "available"
            if all(case.candidates is not None for case in all_results)
            else "unavailable-current-retriever-no-candidate-layer"
        ),
        overall=_aggregate_v2("overall", all_results),
        by_split=tuple(
            _aggregate_v2(
                split,
                tuple(case for case in all_results if case.split == split),
            )
            for split in ("development", "locked-test")
        ),
        by_case_kind=tuple(
            _aggregate_v2(
                kind,
                tuple(
                    case for case in all_results if case.case_kind == kind
                ),
            )
            for kind in (
                "semantic-paraphrase",
                "exact-identifier",
                "mixed-semantic-identifier",
                "version-specific",
                "known-hard",
            )
        ),
        latency=RetrievalLatencySummaryV2(
            warm_up_count=5,
            repetitions_per_case=3,
            sample_count=len(samples),
            percentile_method="nearest-rank",
            minimum_ms=samples[0],
            p50_ms=_nearest_rank_percentile(samples, 0.50),
            p95_ms=_nearest_rank_percentile(samples, 0.95),
            maximum_ms=samples[-1],
        ),
        runtime=runtime,
        cases=all_results,
    )


def _validate_v2_result_identity(
    *,
    result: RetrievalResult,
    manifest: IndexManifest,
    retrieval_config: RetrievalConfig,
) -> None:
    if (
        result.index_id != manifest.index_id
        or result.build_id != manifest.build_id
        or result.collection_name != manifest.collection_name
    ):
        raise IndexVersionMismatchError(
            "V2 retrieval result does not match evaluation index build"
        )
    if result.retrieval_config != retrieval_config:
        raise IndexVersionMismatchError(
            "V2 retrieval result does not match evaluation configuration"
        )


def _make_result_signature(result: RetrievalResult) -> tuple[tuple[object, ...], ...]:
    result_signature = tuple(
        (
            item.rank,
            item.score,
            item.payload.chunk_id,
            item.retrieval_reason,
        )
        for item in result.results
    )
    candidate_signature = tuple(
        (
            item.rank,
            item.score,
            item.payload.chunk_id,
            item.dense_rank,
            item.sparse_rank,
        )
        for item in (result.candidates or ())
    )
    return result_signature + candidate_signature


def _binary_ndcg_at_5(
    *,
    observations: tuple[RetrievalEvaluationObservationV2, ...],
    relevant_chunk_ids: set[object],
) -> float:
    dcg = sum(
        1.0 / log2(item.rank + 1)
        for item in observations
        if item.chunk_id in relevant_chunk_ids
    )
    ideal_count = min(len(relevant_chunk_ids), 5)
    idcg = sum(1.0 / log2(rank + 1) for rank in range(1, ideal_count + 1))
    return 0.0 if idcg == 0 else dcg / idcg


def _aggregate_v2(
    slice_name: str,
    cases: tuple[RetrievalEvaluationCaseResultV2, ...],
) -> RetrievalMetricAggregateV2:
    case_count = len(cases)
    hit_count = sum(case.hit_at_5 for case in cases)
    return RetrievalMetricAggregateV2(
        slice_name=slice_name,
        case_count=case_count,
        hit_count=hit_count,
        recall_at_5=hit_count / case_count,
        mrr_at_5=(
            sum(case.reciprocal_rank_at_5 for case in cases) / case_count
        ),
        ndcg_at_5=sum(case.ndcg_at_5 for case in cases) / case_count,
        candidate_recall_at_20=(
            sum(case.candidate_hit_at_20 is True for case in cases) / case_count
            if all(case.candidates is not None for case in cases)
            else None
        ),
    )


def _evaluation_set_matches_manifest(
    *,
    evaluation_fingerprint: str,
    manifest: IndexManifest,
) -> bool:
    return evaluation_fingerprint in {
        manifest.index_fingerprint,
        manifest.specification.source_index_fingerprint,
    }


def _nearest_rank_percentile(
    sorted_samples: list[float],
    fraction: float,
) -> float:
    rank = ceil(fraction * len(sorted_samples))
    return sorted_samples[max(rank - 1, 0)]
