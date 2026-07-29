"""Fixed, auditable Recall@5 evaluation for local retrieval."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol

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
