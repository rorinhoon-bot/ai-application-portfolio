"""Application service composing retrieval and validated answering."""

import re

from cited_rag.answering import AnsweringService
from cited_rag.models import (
    AnswerResult,
    PythonVersion,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
)
from cited_rag.retrieval import QdrantRetrievalService, make_retrieval_query

_VERSION_PATTERN = re.compile(
    r"(?<![0-9])3\.(?:13|14)(?![0-9])",
    flags=re.IGNORECASE,
)


class CitedRagService:
    def __init__(
        self,
        *,
        retriever: QdrantRetrievalService,
        answerer: AnsweringService,
    ) -> None:
        self._retriever = retriever
        self._answerer = answerer

    def answer(
        self,
        *,
        question: str,
        python_version: PythonVersion | None = None,
    ) -> AnswerResult:
        query = make_retrieval_query(
            question=question,
            python_version=python_version,
        )
        if (
            python_version is None
            and extract_comparison_versions(question)
            == ("3.13", "3.14")
        ):
            search_text = make_comparison_search_text(question)
            retrieval = merge_version_retrievals(
                query=query,
                retrievals=tuple(
                    self._retriever.retrieve(
                        make_retrieval_query(
                            question=search_text,
                            python_version=version,
                        )
                    )
                    for version in ("3.13", "3.14")
                ),
            )
        else:
            retrieval = self._retriever.retrieve(query)
        return self._answerer.answer(retrieval)


def extract_comparison_versions(
    question: str,
) -> tuple[PythonVersion, ...]:
    """Return supported version series explicitly present in a question."""

    found = set(_VERSION_PATTERN.findall(question))
    return tuple(
        version
        for version in ("3.13", "3.14")
        if version in found
    )


def make_comparison_search_text(question: str) -> str:
    """Remove version labels already enforced by per-version filters."""

    normalized = re.sub(
        r"(?:Python\s*)?3\.(?:13|14)",
        " ",
        question,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(
        r"在\s*(?:与|和|及|、|/)?\s*中",
        " ",
        normalized,
    )
    normalized = re.sub(r"^[\s与和及、/中的，,]+", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or question


def merge_version_retrievals(
    *,
    query: RetrievalQuery,
    retrievals: tuple[RetrievalResult, RetrievalResult],
) -> RetrievalResult:
    """Interleave two filtered result sets into one five-item prompt."""

    first, second = retrievals
    if (
        first.index_id != second.index_id
        or first.build_id != second.build_id
        or first.collection_name != second.collection_name
        or first.retrieval_config != second.retrieval_config
        or first.query.python_version != "3.13"
        or second.query.python_version != "3.14"
    ):
        raise ValueError("comparison retrieval results are inconsistent")

    selected: list[RetrievedChunk] = []
    for position in range(2):
        for retrieval in retrievals:
            if position < len(retrieval.results):
                selected.append(retrieval.results[position])

    selected_ids = {item.payload.chunk_id for item in selected}
    remaining = sorted(
        (
            item
            for retrieval in retrievals
            for item in retrieval.results
            if item.payload.chunk_id not in selected_ids
        ),
        key=lambda item: (
            -item.score,
            item.payload.python_version,
            str(item.payload.chunk_id),
        ),
    )
    selected.extend(remaining[: 5 - len(selected)])
    reranked = tuple(
        RetrievedChunk.model_validate(
            {
                **item.model_dump(mode="python"),
                "rank": rank,
            }
        )
        for rank, item in enumerate(selected[:5], start=1)
    )
    return RetrievalResult(
        query=query,
        retrieval_config=first.retrieval_config,
        index_id=first.index_id,
        build_id=first.build_id,
        collection_name=first.collection_name,
        results=reranked,
    )
