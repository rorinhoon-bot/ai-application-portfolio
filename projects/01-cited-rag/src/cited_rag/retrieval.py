"""Validated dense retrieval against one active local Qdrant index."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re

from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchText,
    MatchValue,
    VectorParams,
)

from cited_rag.embedding import EmbeddingService
from cited_rag.errors import (
    CitedRagError,
    IndexConsistencyError,
    RetrievalError,
    RetrievalInputError,
)
from cited_rag.indexing import load_active_index
from cited_rag.models import (
    ChunkPayload,
    PythonVersion,
    RetrievalConfig,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
)

ClientFactory = Callable[[Path], QdrantClient]

BASELINE_DENSE_RETRIEVAL_CONFIG = RetrievalConfig(
    schema_version="1",
    mode="dense",
    top_k=5,
    remove_filtered_version_terms=False,
    identifier_result_limit=0,
)
DENSE_IDENTIFIER_RETRIEVAL_CONFIG = RetrievalConfig(
    schema_version="1",
    mode="dense-plus-identifiers",
    top_k=5,
    remove_filtered_version_terms=True,
    identifier_result_limit=2,
)
_ASCII_IDENTIFIER = re.compile(
    r"(?<![A-Za-z0-9_.])"
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    r"(?![A-Za-z0-9_.])"
)
_IDENTIFIER_STOP_WORDS = frozenset(
    {
        "ascii",
        "false",
        "none",
        "python",
        "true",
    }
)


def make_retrieval_query(
    *,
    question: str,
    python_version: PythonVersion | None = None,
    top_k: int = 5,
) -> RetrievalQuery:
    """Convert external values into the strict public query contract."""

    try:
        return RetrievalQuery(
            question=question,
            python_version=python_version,
            top_k=top_k,
        )
    except ValidationError as error:
        raise RetrievalInputError("retrieval query is invalid") from error


class QdrantRetrievalService:
    """Embed a validated question and return traceable ranked chunks."""

    def __init__(
        self,
        *,
        embedding_service: EmbeddingService,
        index_root: Path,
        retrieval_config: RetrievalConfig = BASELINE_DENSE_RETRIEVAL_CONFIG,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._embedding_service = embedding_service
        self._index_root = index_root
        self._retrieval_config = retrieval_config
        self._client_factory = client_factory or (
            lambda path: QdrantClient(path=str(path))
        )

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Search only after active metadata and physical storage agree."""

        _, manifest = load_active_index(index_root=self._index_root)
        if (
            self._embedding_service.dimension
            != manifest.specification.embedding_dimension
        ):
            raise IndexConsistencyError(
                "query embedding dimension does not match active index"
            )
        if query.top_k != self._retrieval_config.top_k:
            raise RetrievalInputError(
                "query top_k does not match retrieval configuration"
            )

        client = self._client_factory(
            self._index_root.resolve(strict=True) / "qdrant"
        )
        try:
            _validate_collection_for_query(
                client=client,
                collection_name=manifest.collection_name,
                dimension=manifest.specification.embedding_dimension,
                point_count=manifest.point_count,
            )
            embedding_text = _make_query_embedding_text(
                query=query,
                config=self._retrieval_config,
            )
            vector = self._embedding_service.embed_query(embedding_text)
            version_conditions = _make_version_conditions(query)
            query_filter = (
                Filter(must=version_conditions)
                if version_conditions
                else None
            )
            try:
                dense_points = client.query_points(
                    collection_name=manifest.collection_name,
                    query=list(vector),
                    query_filter=query_filter,
                    limit=query.top_k,
                    with_payload=True,
                    with_vectors=False,
                ).points
                ranked_points = [
                    (point, "dense") for point in dense_points
                ]
                if self._retrieval_config.mode == "dense-plus-identifiers":
                    identifier_points = _query_identifier_candidates(
                        client=client,
                        collection_name=manifest.collection_name,
                        vector=vector,
                        question=query.question,
                        version_conditions=version_conditions,
                        limit=self._retrieval_config.identifier_result_limit,
                    )
                    identifier_ids = {
                        str(point.id) for point in identifier_points
                    }
                    ranked_points = [
                        (point, "identifier")
                        for point in identifier_points
                    ]
                    ranked_points.extend(
                        (point, "dense")
                        for point in dense_points
                        if str(point.id) not in identifier_ids
                    )
                    ranked_points = ranked_points[: query.top_k]
            except Exception as error:
                raise RetrievalError("Qdrant query failed") from error

            results: list[RetrievedChunk] = []
            for rank, (point, retrieval_reason) in enumerate(
                ranked_points,
                start=1,
            ):
                if point.payload is None:
                    raise IndexConsistencyError(
                        "retrieved Qdrant payload is missing"
                    )
                try:
                    payload = ChunkPayload.model_validate(point.payload)
                except ValidationError as error:
                    raise IndexConsistencyError(
                        "retrieved Qdrant payload is invalid"
                    ) from error
                if str(point.id) != str(payload.chunk_id):
                    raise IndexConsistencyError(
                        "retrieved point ID does not match payload chunk_id"
                    )
                if (
                    payload.chunking_schema_version
                    != manifest.specification.chunking_schema_version
                    or payload.chunk_config_sha256
                    != manifest.specification.chunk_config_sha256
                ):
                    raise IndexConsistencyError(
                        "retrieved payload does not match active index"
                    )
                try:
                    results.append(
                        RetrievedChunk(
                            rank=rank,
                            score=float(point.score),
                            payload=payload,
                            citation_url=(
                                f"{payload.source_url}"
                                f"#{payload.section_anchor}"
                            ),
                            retrieval_reason=retrieval_reason,
                        )
                    )
                except ValidationError as error:
                    raise IndexConsistencyError(
                        "retrieved result violates result contract"
                    ) from error

            return RetrievalResult(
                query=query,
                retrieval_config=self._retrieval_config,
                index_id=manifest.index_id,
                build_id=manifest.build_id,
                collection_name=manifest.collection_name,
                results=tuple(results),
            )
        except CitedRagError:
            raise
        except Exception as error:
            raise RetrievalError("local retrieval failed") from error
        finally:
            client.close()


def _validate_collection_for_query(
    *,
    client: QdrantClient,
    collection_name: str,
    dimension: int,
    point_count: int,
) -> None:
    try:
        if not client.collection_exists(collection_name):
            raise IndexConsistencyError("active Qdrant collection is missing")
        info = client.get_collection(collection_name)
        vector_params = info.config.params.vectors
        if (
            not isinstance(vector_params, VectorParams)
            or vector_params.size != dimension
            or vector_params.distance != Distance.COSINE
        ):
            raise IndexConsistencyError(
                "active Qdrant vector configuration changed"
            )
        observed_count = client.count(
            collection_name=collection_name,
            exact=True,
        ).count
        if observed_count != point_count:
            raise IndexConsistencyError(
                "active Qdrant point count does not match manifest"
            )
    except CitedRagError:
        raise
    except Exception as error:
        raise IndexConsistencyError(
            "active Qdrant collection could not be validated"
        ) from error


def _make_version_conditions(
    query: RetrievalQuery,
) -> list[FieldCondition]:
    if query.python_version is None:
        return []
    return [
        FieldCondition(
            key="python_version",
            match=MatchValue(value=query.python_version),
        )
    ]


def _make_query_embedding_text(
    *,
    query: RetrievalQuery,
    config: RetrievalConfig,
) -> str:
    if (
        not config.remove_filtered_version_terms
        or query.python_version is None
    ):
        return query.question
    version_pattern = re.compile(
        rf"Python\s*{re.escape(query.python_version)}(?:\s*[中的])?\s*",
        flags=re.IGNORECASE,
    )
    normalized = version_pattern.sub("", query.question).strip()
    return normalized or query.question


def extract_query_identifiers(question: str) -> tuple[str, ...]:
    """Extract only explicit code-like ASCII identifiers from user text."""

    identifiers: list[str] = []
    seen: set[str] = set()
    for match in _ASCII_IDENTIFIER.finditer(question):
        value = match.group(0)
        lowered = value.lower()
        code_like = (
            "." in value
            or "_" in value
            or (len(value) >= 3 and value.islower())
            or (
                len(value) >= 2
                and any(character.islower() for character in value)
                and any(character.isupper() for character in value)
            )
        )
        if (
            code_like
            and lowered not in _IDENTIFIER_STOP_WORDS
            and lowered not in seen
        ):
            seen.add(lowered)
            identifiers.append(value)
    return tuple(identifiers)


def _query_identifier_candidates(
    *,
    client: QdrantClient,
    collection_name: str,
    vector: tuple[float, ...],
    question: str,
    version_conditions: list[FieldCondition],
    limit: int,
):
    candidates = {}
    for identifier in extract_query_identifiers(question):
        points = client.query_points(
            collection_name=collection_name,
            query=list(vector),
            query_filter=Filter(
                must=[
                    *version_conditions,
                    FieldCondition(
                        key="text",
                        match=MatchText(text=identifier),
                    ),
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        ).points
        for point in points:
            point_id = str(point.id)
            existing = candidates.get(point_id)
            if existing is None or point.score > existing.score:
                candidates[point_id] = point
    return sorted(
        candidates.values(),
        key=lambda point: (-float(point.score), str(point.id)),
    )[:limit]
