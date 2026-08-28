"""Validated dense retrieval against one active local Qdrant index."""

from __future__ import annotations

from fractions import Fraction
from math import isfinite
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
    Modifier,
    Prefetch,
    Rrf,
    RrfQuery,
    SearchParams,
    SparseVectorParams,
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
    IndexManifest,
    PythonVersion,
    RetrievalConfig,
    RetrievalCandidate,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
)
from cited_rag.observability import current_observability
from cited_rag.qdrant_connection import ClientFactory
from cited_rag.sparse import load_sparse_vocabulary, make_sparse_query_vector

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
HYBRID_RRF_RETRIEVAL_CONFIG = RetrievalConfig(
    schema_version="2",
    mode="hybrid-rrf",
    top_k=5,
    remove_filtered_version_terms=True,
    identifier_result_limit=0,
    dense_vector_name="dense-bge-v1",
    sparse_vector_name="lexical-bm25-v1",
    dense_prefetch=20,
    sparse_prefetch=20,
    fusion_candidate_count=20,
    rrf_k=2,
    rrf_weights=(1.0, 1.0),
    tie_break="score-desc-point-id-asc",
)
HYBRID_CLIENT_RRF_RETRIEVAL_CONFIG = RetrievalConfig(
    schema_version="3",
    mode="hybrid-client-rrf-v1",
    top_k=5,
    remove_filtered_version_terms=True,
    identifier_result_limit=0,
    dense_vector_name="dense-bge-v1",
    sparse_vector_name="lexical-bm25-v1",
    dense_prefetch=20,
    sparse_prefetch=20,
    fusion_candidate_count=20,
    rrf_k=2,
    rrf_weights=(1.0, 1.0),
    tie_break="score-desc-point-id-asc",
    dense_exact=True,
    lane_candidate_count=20,
    tie_window_initial_limit=64,
    tie_window_growth_factor=2,
    tie_window_cap="manifest-point-count",
    rrf_rank_base="zero-based",
    rrf_arithmetic="fraction-exact",
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
        manifest_override: IndexManifest | None = None,
    ) -> None:
        self._embedding_service = embedding_service
        self._index_root = index_root
        self._retrieval_config = retrieval_config
        self._client_factory = client_factory or (
            lambda path: QdrantClient(path=str(path))
        )
        self._manifest_override = manifest_override

    def check_ready(self) -> None:
        """Validate the active read index without embedding or model calls."""

        manifest = self._load_ready_manifest()
        client = self._client_factory(
            self._index_root.resolve(strict=True) / "qdrant"
        )
        try:
            _validate_collection_for_query(
                client=client,
                manifest=manifest,
                retrieval_config=self._retrieval_config,
                vocabulary_root=self._index_root / "vocabularies",
            )
        finally:
            client.close()

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        """Search only after active metadata and physical storage agree."""

        telemetry = current_observability()
        manifest = self._load_ready_manifest()
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
                manifest=manifest,
                retrieval_config=self._retrieval_config,
                vocabulary_root=self._index_root / "vocabularies",
            )
            embedding_text = _make_query_embedding_text(
                query=query,
                config=self._retrieval_config,
            )
            with telemetry.stage(
                "rag.embedding",
                stage="embedding",
                attributes={"python_version": query.python_version},
            ):
                vector = self._embedding_service.embed_query(
                    embedding_text
                )
            version_conditions = _make_version_conditions(query)
            query_filter = (
                Filter(must=version_conditions)
                if version_conditions
                else None
            )
            try:
                if self._retrieval_config.mode == "hybrid-client-rrf-v1":
                    return self._retrieve_hybrid_client_rrf(
                        client=client,
                        manifest=manifest,
                        query=query,
                        embedding_text=embedding_text,
                        vector=vector,
                        query_filter=query_filter,
                    )
                if self._retrieval_config.mode == "hybrid-rrf":
                    return self._retrieve_hybrid(
                        client=client,
                        manifest=manifest,
                        query=query,
                        embedding_text=embedding_text,
                        vector=vector,
                        query_filter=query_filter,
                    )
                with telemetry.stage(
                    "rag.qdrant.dense",
                    stage="qdrant.dense",
                    attributes={
                        "index_id": manifest.index_id,
                        "build_id": manifest.build_id,
                    },
                ):
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

            telemetry.record_candidates(
                source="dense",
                count=len(dense_points),
            )
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

    def _load_ready_manifest(self) -> IndexManifest:
        manifest = self._manifest_override
        if manifest is None:
            _, manifest = load_active_index(index_root=self._index_root)
        if (
            self._embedding_service.dimension
            != manifest.specification.embedding_dimension
        ):
            raise IndexConsistencyError(
                "query embedding dimension does not match active index"
            )
        return manifest

    def _retrieve_hybrid(
        self,
        *,
        client: QdrantClient,
        manifest: IndexManifest,
        query: RetrievalQuery,
        embedding_text: str,
        vector: tuple[float, ...],
        query_filter: Filter | None,
    ) -> RetrievalResult:
        telemetry = current_observability()
        specification = manifest.specification
        vocabulary_hash = specification.sparse_vocabulary_sha256
        if specification.schema_version != "2" or vocabulary_hash is None:
            raise IndexConsistencyError("hybrid retrieval requires index schema v2")
        vocabulary = load_sparse_vocabulary(
            root=self._index_root / "vocabularies",
            expected_sha256=vocabulary_hash,
        )
        if vocabulary.sparse_config_sha256 != specification.sparse_config_sha256:
            raise IndexConsistencyError("sparse vocabulary config does not match index")
        sparse_query = make_sparse_query_vector(
            text=embedding_text,
            vocabulary=vocabulary,
        )
        with telemetry.stage(
            "rag.qdrant.dense",
            stage="qdrant.dense",
        ):
            dense_points = client.query_points(
                collection_name=manifest.collection_name,
                query=list(vector),
                using="dense-bge-v1",
                query_filter=query_filter,
                limit=20,
                with_payload=False,
                with_vectors=False,
            ).points
        with telemetry.stage(
            "rag.qdrant.sparse",
            stage="qdrant.sparse",
        ):
            sparse_points = client.query_points(
                collection_name=manifest.collection_name,
                query=sparse_query,
                using="lexical-bm25-v1",
                query_filter=query_filter,
                limit=20,
                with_payload=False,
                with_vectors=False,
            ).points
        with telemetry.stage("rag.fusion", stage="fusion"):
            fused_points = client.query_points(
                collection_name=manifest.collection_name,
                prefetch=[
                    Prefetch(
                        query=list(vector),
                        using="dense-bge-v1",
                        filter=query_filter,
                        limit=20,
                    ),
                    Prefetch(
                        query=sparse_query,
                        using="lexical-bm25-v1",
                        filter=query_filter,
                        limit=20,
                    ),
                ],
                query=RrfQuery(
                    rrf=Rrf(k=2, weights=[1.0, 1.0])
                ),
                limit=20,
                with_payload=True,
                with_vectors=False,
            ).points
        dense_points = _stable_points(dense_points)
        sparse_points = _stable_points(sparse_points)
        fused_points = _stable_points(fused_points)
        dense_ranks = {str(point.id): rank for rank, point in enumerate(dense_points, 1)}
        sparse_ranks = {str(point.id): rank for rank, point in enumerate(sparse_points, 1)}
        candidates = tuple(
            _make_hybrid_candidate(
                point=point,
                rank=rank,
                manifest=manifest,
                dense_rank=dense_ranks.get(str(point.id)),
                sparse_rank=sparse_ranks.get(str(point.id)),
            )
            for rank, point in enumerate(fused_points, start=1)
        )
        results = tuple(
            RetrievedChunk(
                rank=candidate.rank,
                score=candidate.score,
                payload=candidate.payload,
                citation_url=candidate.citation_url,
                retrieval_reason="hybrid-rrf",
                score_kind="rrf",
            )
            for candidate in candidates[: query.top_k]
        )
        telemetry.record_candidates(
            source="dense",
            count=len(dense_points),
        )
        telemetry.record_candidates(
            source="sparse",
            count=len(sparse_points),
        )
        telemetry.record_candidates(
            source="fused",
            count=len(candidates),
        )
        return RetrievalResult(
            query=query,
            retrieval_config=self._retrieval_config,
            index_id=manifest.index_id,
            build_id=manifest.build_id,
            collection_name=manifest.collection_name,
            results=results,
            candidates=candidates,
        )

    def _retrieve_hybrid_client_rrf(
        self,
        *,
        client: QdrantClient,
        manifest: IndexManifest,
        query: RetrievalQuery,
        embedding_text: str,
        vector: tuple[float, ...],
        query_filter: Filter | None,
    ) -> RetrievalResult:
        telemetry = current_observability()
        specification = manifest.specification
        vocabulary_hash = specification.sparse_vocabulary_sha256
        if specification.schema_version != "2" or vocabulary_hash is None:
            raise IndexConsistencyError("hybrid retrieval requires index schema v2")
        vocabulary = load_sparse_vocabulary(
            root=self._index_root / "vocabularies",
            expected_sha256=vocabulary_hash,
        )
        if vocabulary.sparse_config_sha256 != specification.sparse_config_sha256:
            raise IndexConsistencyError("sparse vocabulary config does not match index")
        sparse_query = make_sparse_query_vector(
            text=embedding_text,
            vocabulary=vocabulary,
        )
        with telemetry.stage(
            "rag.qdrant.dense",
            stage="qdrant.dense",
        ):
            dense_points, dense_limit, dense_rounds = (
                _query_tie_closed_lane(
                    client=client,
                    collection_name=manifest.collection_name,
                    query=list(vector),
                    using="dense-bge-v1",
                    query_filter=query_filter,
                    point_count=manifest.point_count,
                    exact=True,
                )
            )
        with telemetry.stage(
            "rag.qdrant.sparse",
            stage="qdrant.sparse",
        ):
            sparse_points, sparse_limit, sparse_rounds = (
                _query_tie_closed_lane(
                    client=client,
                    collection_name=manifest.collection_name,
                    query=sparse_query,
                    using="lexical-bm25-v1",
                    query_filter=query_filter,
                    point_count=manifest.point_count,
                    exact=False,
                )
            )
        with telemetry.stage("rag.fusion", stage="fusion"):
            fused = _fraction_rrf(
                dense_points=dense_points,
                sparse_points=sparse_points,
            )
            records = client.retrieve(
                collection_name=manifest.collection_name,
                ids=[item["point_id"] for item in fused],
                with_payload=True,
                with_vectors=False,
            )
            records_by_id = _validate_retrieved_records(
                records=records,
                expected_ids=[str(item["point_id"]) for item in fused],
            )
        candidates = tuple(
            _make_client_hybrid_candidate(
                record=records_by_id[str(item["point_id"])],
                rank=rank,
                score=item["score"],
                manifest=manifest,
                dense_rank=item["dense_rank"],
                sparse_rank=item["sparse_rank"],
            )
            for rank, item in enumerate(fused, start=1)
        )
        results = tuple(
            RetrievedChunk(
                rank=candidate.rank,
                score=candidate.score,
                payload=candidate.payload,
                citation_url=candidate.citation_url,
                retrieval_reason="hybrid-client-rrf-v1",
                score_kind="rrf",
            )
            for candidate in candidates[: query.top_k]
        )
        telemetry.record_candidates(
            source="dense",
            count=len(dense_points),
        )
        telemetry.record_candidates(
            source="sparse",
            count=len(sparse_points),
        )
        telemetry.record_candidates(
            source="fused",
            count=len(candidates),
        )
        return RetrievalResult(
            query=query,
            retrieval_config=self._retrieval_config,
            index_id=manifest.index_id,
            build_id=manifest.build_id,
            collection_name=manifest.collection_name,
            results=results,
            candidates=candidates,
            dense_fetch_limit=dense_limit,
            sparse_fetch_limit=sparse_limit,
            dense_fetch_rounds=dense_rounds,
            sparse_fetch_rounds=sparse_rounds,
        )


def _validate_collection_for_query(
    *,
    client: QdrantClient,
    manifest: IndexManifest,
    retrieval_config: RetrievalConfig,
    vocabulary_root: Path,
) -> None:
    try:
        collection_name = manifest.collection_name
        if not client.collection_exists(collection_name):
            raise IndexConsistencyError("active Qdrant collection is missing")
        info = client.get_collection(collection_name)
        vector_params = info.config.params.vectors
        if retrieval_config.mode in {"hybrid-rrf", "hybrid-client-rrf-v1"}:
            sparse_params = info.config.params.sparse_vectors
            dense = vector_params.get("dense-bge-v1") if isinstance(vector_params, dict) else None
            sparse = sparse_params.get("lexical-bm25-v1") if isinstance(sparse_params, dict) else None
            if (
                manifest.specification.schema_version != "2"
                or not isinstance(dense, VectorParams)
                or dense.size != manifest.specification.embedding_dimension
                or dense.distance != Distance.COSINE
                or not isinstance(sparse, SparseVectorParams)
                or sparse.modifier != Modifier.IDF
            ):
                raise IndexConsistencyError("active Hybrid vector configuration changed")
            load_sparse_vocabulary(
                root=vocabulary_root,
                expected_sha256=manifest.specification.sparse_vocabulary_sha256 or "",
            )
        elif (
            not isinstance(vector_params, VectorParams)
            or vector_params.size != manifest.specification.embedding_dimension
            or vector_params.distance != Distance.COSINE
        ):
            raise IndexConsistencyError("active Qdrant vector configuration changed")
        observed_count = client.count(
            collection_name=collection_name,
            exact=True,
        ).count
        if observed_count != manifest.point_count:
            raise IndexConsistencyError(
                "active Qdrant point count does not match manifest"
            )
    except CitedRagError:
        raise
    except Exception as error:
        raise IndexConsistencyError(
            "active Qdrant collection could not be validated"
        ) from error


def _make_hybrid_candidate(
    *,
    point,
    rank: int,
    manifest: IndexManifest,
    dense_rank: int | None,
    sparse_rank: int | None,
) -> RetrievalCandidate:
    if point.payload is None:
        raise IndexConsistencyError("retrieved Hybrid payload is missing")
    try:
        payload = ChunkPayload.model_validate(point.payload)
    except ValidationError as error:
        raise IndexConsistencyError("retrieved Hybrid payload is invalid") from error
    if str(point.id) != str(payload.chunk_id):
        raise IndexConsistencyError("retrieved Hybrid point ID does not match payload")
    if (
        payload.chunking_schema_version
        != manifest.specification.chunking_schema_version
        or payload.chunk_config_sha256
        != manifest.specification.chunk_config_sha256
    ):
        raise IndexConsistencyError("retrieved Hybrid payload does not match index")
    try:
        return RetrievalCandidate(
            rank=rank,
            score=float(point.score),
            payload=payload,
            citation_url=f"{payload.source_url}#{payload.section_anchor}",
            retrieval_reason="hybrid-rrf",
            score_kind="rrf",
            dense_rank=dense_rank,
            sparse_rank=sparse_rank,
        )
    except ValidationError as error:
        raise IndexConsistencyError("retrieved Hybrid candidate is invalid") from error


def _stable_points(points):
    """Use one explicit tie-break because Qdrant tie order is unspecified."""

    return sorted(
        points,
        key=lambda point: (-float(point.score), str(point.id)),
    )


def _query_tie_closed_lane(
    *,
    client,
    collection_name: str,
    query,
    using: str,
    query_filter: Filter | None,
    point_count: int,
    exact: bool,
):
    """Return a deterministic top-20 after closing the score-tie boundary."""

    if point_count < 1:
        raise IndexConsistencyError("manifest point count must be positive")
    limit = min(64, point_count)
    rounds = 0
    while True:
        rounds += 1
        response = client.query_points(
            collection_name=collection_name,
            query=query,
            using=using,
            query_filter=query_filter,
            search_params=SearchParams(exact=True) if exact else None,
            limit=limit,
            with_payload=False,
            with_vectors=False,
        )
        points = list(response.points)
        if len(points) > limit:
            raise IndexConsistencyError("Qdrant lane returned more points than requested")
        ids = [str(point.id) for point in points]
        if len(ids) != len(set(ids)):
            raise IndexConsistencyError("Qdrant lane returned duplicate point IDs")
        if any(not isfinite(float(point.score)) for point in points):
            raise IndexConsistencyError("Qdrant lane returned a non-finite score")
        points = _stable_points(points)
        closed = (
            len(points) < limit
            or len(points) <= 20
            or float(points[19].score) != float(points[-1].score)
            or limit >= point_count
        )
        if closed:
            return points[:20], limit, rounds
        next_limit = min(limit * 2, point_count)
        if next_limit <= limit:
            raise IndexConsistencyError("tie-window expansion did not advance")
        limit = next_limit


def _fraction_rrf(*, dense_points, sparse_points):
    """Fuse two deterministic top-20 lanes with exact zero-based RRF."""

    by_id: dict[str, dict[str, object]] = {}
    for lane_name, points in (
        ("dense", dense_points),
        ("sparse", sparse_points),
    ):
        for zero_rank, point in enumerate(points):
            point_id = str(point.id)
            item = by_id.setdefault(
                point_id,
                {
                    "point_id": point.id,
                    "score": Fraction(0, 1),
                    "dense_rank": None,
                    "sparse_rank": None,
                },
            )
            item["score"] = item["score"] + Fraction(1, 2 + zero_rank)
            item[f"{lane_name}_rank"] = zero_rank + 1
    ordered = sorted(
        by_id.values(),
        key=lambda item: (-item["score"], str(item["point_id"])),
    )
    return ordered[:20]


def _validate_retrieved_records(*, records, expected_ids: list[str]):
    expected = set(expected_ids)
    by_id = {str(record.id): record for record in records}
    if len(by_id) != len(records):
        raise IndexConsistencyError("retrieved Hybrid payloads contain duplicate IDs")
    if set(by_id) != expected:
        raise IndexConsistencyError("retrieved Hybrid payload IDs do not match candidates")
    return by_id


def _make_client_hybrid_candidate(
    *,
    record,
    rank: int,
    score: Fraction,
    manifest: IndexManifest,
    dense_rank: int | None,
    sparse_rank: int | None,
) -> RetrievalCandidate:
    if record.payload is None:
        raise IndexConsistencyError("retrieved Hybrid payload is missing")
    try:
        payload = ChunkPayload.model_validate(record.payload)
    except ValidationError as error:
        raise IndexConsistencyError("retrieved Hybrid payload is invalid") from error
    if str(record.id) != str(payload.chunk_id):
        raise IndexConsistencyError("retrieved Hybrid point ID does not match payload")
    if (
        payload.chunking_schema_version
        != manifest.specification.chunking_schema_version
        or payload.chunk_config_sha256
        != manifest.specification.chunk_config_sha256
    ):
        raise IndexConsistencyError("retrieved Hybrid payload does not match index")
    try:
        return RetrievalCandidate(
            rank=rank,
            score=float(score),
            payload=payload,
            citation_url=f"{payload.source_url}#{payload.section_anchor}",
            retrieval_reason="hybrid-client-rrf-v1",
            score_kind="rrf",
            dense_rank=dense_rank,
            sparse_rank=sparse_rank,
        )
    except ValidationError as error:
        raise IndexConsistencyError("retrieved Hybrid candidate is invalid") from error


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
