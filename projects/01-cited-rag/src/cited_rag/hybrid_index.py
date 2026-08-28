"""Build and validate one inactive Dense+Sparse Qdrant candidate."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    Modifier,
    PointStruct,
    SparseVectorParams,
    VectorParams,
)

from cited_rag.errors import IndexBuildError, IndexConsistencyError
from cited_rag.indexing import (
    load_active_index,
    make_active_pointer,
    make_chunk_payload,
    make_hybrid_index_specification,
    make_index_manifest,
    write_index_manifest,
)
from cited_rag.models import DocumentChunk, IndexManifest
from cited_rag.qdrant_connection import ClientFactory
from cited_rag.sparse import SparseCorpus, build_sparse_corpus, write_sparse_vocabulary

Clock = Callable[[], datetime]
BuildIdFactory = Callable[[], UUID]


@dataclass(frozen=True, slots=True)
class HybridCollectionValidation:
    point_count: int
    payload_count: int
    unique_point_count: int
    dense_self_query_top_score: float
    sparse_self_query_returned: bool
    version_filter_checked: bool
    sparse_nonzero_count: int


@dataclass(frozen=True, slots=True)
class HybridBuildResult:
    manifest: IndexManifest
    validation: HybridCollectionValidation
    vocabulary_path: Path
    copied_dense_count: int
    sparse_vector_count: int


class QdrantHybridCandidateBuilder:
    """Copy verified Dense vectors, add Sparse vectors, never activate."""

    def __init__(
        self,
        *,
        clock: Clock,
        build_id_factory: BuildIdFactory,
        qdrant_client_version: str,
        client_factory: ClientFactory,
        batch_size: int = 64,
    ) -> None:
        self._clock = clock
        self._build_id_factory = build_id_factory
        self._qdrant_client_version = qdrant_client_version
        self._client_factory = client_factory
        self._batch_size = batch_size

    def build(self, *, chunks: Sequence[DocumentChunk], index_root: Path) -> HybridBuildResult:
        ordered = tuple(sorted(chunks, key=lambda item: (item.source_id, item.chunk_order)))
        if not ordered or len({item.chunk_id for item in ordered}) != len(ordered):
            raise IndexConsistencyError("hybrid build chunks are empty or duplicated")
        resolved_root = index_root.resolve(strict=True)
        _, source_manifest = load_active_index(index_root=resolved_root)
        if source_manifest.specification.schema_version != "1":
            raise IndexConsistencyError("active source index must be dense schema v1")
        if source_manifest.point_count != len(ordered):
            raise IndexConsistencyError("active source point count does not match chunks")

        sparse_corpus = build_sparse_corpus(ordered)
        specification = make_hybrid_index_specification(
            source_manifest=source_manifest,
            sparse_corpus=sparse_corpus,
        )
        manifest = make_index_manifest(
            specification=specification,
            build_id=self._build_id_factory(),
            built_at=self._clock(),
            qdrant_client_version=self._qdrant_client_version,
        )
        vocabulary_path = write_sparse_vocabulary(
            root=resolved_root / "vocabularies",
            corpus=sparse_corpus,
        )
        client = self._client_factory(resolved_root / "qdrant")
        created = False
        try:
            if client.collection_exists(manifest.collection_name):
                raise IndexConsistencyError("new hybrid collection name already exists")
            client.create_collection(
                collection_name=manifest.collection_name,
                vectors_config={
                    "dense-bge-v1": VectorParams(
                        size=specification.embedding_dimension,
                        distance=Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    "lexical-bm25-v1": SparseVectorParams(modifier=Modifier.IDF)
                },
            )
            created = True
            source_records = _read_verified_source_records(
                client=client,
                source_manifest=source_manifest,
                chunks=ordered,
            )
            for start in range(0, len(ordered), self._batch_size):
                batch = ordered[start : start + self._batch_size]
                points = [
                    PointStruct(
                        id=str(chunk.chunk_id),
                        vector={
                            "dense-bge-v1": source_records[str(chunk.chunk_id)],
                            "lexical-bm25-v1": sparse_corpus.vectors[chunk.chunk_id],
                        },
                        payload=make_chunk_payload(chunk).model_dump(mode="json"),
                    )
                    for chunk in batch
                ]
                try:
                    client.upsert(
                        collection_name=manifest.collection_name,
                        points=points,
                        wait=True,
                    )
                except Exception as error:
                    raise IndexBuildError(
                        f"Qdrant hybrid upsert failed for batch {start // self._batch_size + 1}"
                    ) from error
            validation = validate_hybrid_collection(
                client=client,
                manifest=manifest,
                chunks=ordered,
                sparse_corpus=sparse_corpus,
            )
            pointer = make_active_pointer(manifest)
            write_index_manifest(
                index_root=resolved_root,
                pointer=pointer,
                manifest=manifest,
            )
            return HybridBuildResult(
                manifest=manifest,
                validation=validation,
                vocabulary_path=vocabulary_path,
                copied_dense_count=len(source_records),
                sparse_vector_count=len(sparse_corpus.vectors),
            )
        except Exception:
            if created and client.collection_exists(manifest.collection_name):
                client.delete_collection(manifest.collection_name)
            raise
        finally:
            client.close()


def _read_verified_source_records(
    *,
    client: QdrantClient,
    source_manifest: IndexManifest,
    chunks: tuple[DocumentChunk, ...],
) -> dict[str, list[float]]:
    expected = {str(chunk.chunk_id): chunk for chunk in chunks}
    observed: dict[str, list[float]] = {}
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=source_manifest.collection_name,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        for record in records:
            point_id = str(record.id)
            chunk = expected.get(point_id)
            if chunk is None or point_id in observed:
                raise IndexConsistencyError("dense source point identity changed")
            if record.payload != make_chunk_payload(chunk).model_dump(mode="json"):
                raise IndexConsistencyError("dense source payload changed")
            if not isinstance(record.vector, list) or len(record.vector) != 512:
                raise IndexConsistencyError("dense source vector changed")
            observed[point_id] = [float(value) for value in record.vector]
        if offset is None:
            break
    if set(observed) != set(expected):
        raise IndexConsistencyError("dense source point set changed")
    return observed


def validate_hybrid_collection(
    *,
    client: QdrantClient,
    manifest: IndexManifest,
    chunks: tuple[DocumentChunk, ...],
    sparse_corpus: SparseCorpus,
) -> HybridCollectionValidation:
    if manifest.specification.schema_version != "2":
        raise IndexConsistencyError("hybrid manifest must use schema v2")
    info = client.get_collection(manifest.collection_name)
    vectors = info.config.params.vectors
    sparse_vectors = info.config.params.sparse_vectors
    dense = vectors.get("dense-bge-v1") if isinstance(vectors, dict) else None
    sparse = (
        sparse_vectors.get("lexical-bm25-v1")
        if isinstance(sparse_vectors, dict)
        else None
    )
    if not isinstance(dense, VectorParams) or dense.size != 512 or dense.distance != Distance.COSINE:
        raise IndexConsistencyError("hybrid dense vector configuration changed")
    if not isinstance(sparse, SparseVectorParams) or sparse.modifier != Modifier.IDF:
        raise IndexConsistencyError("hybrid sparse vector configuration changed")
    point_count = client.count(collection_name=manifest.collection_name, exact=True).count
    if point_count != len(chunks):
        raise IndexConsistencyError("hybrid point count changed")

    expected = {str(chunk.chunk_id): chunk for chunk in chunks}
    observed: set[str] = set()
    sparse_nonzero_count = 0
    offset = None
    while True:
        records, offset = client.scroll(
            collection_name=manifest.collection_name,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        for record in records:
            point_id = str(record.id)
            chunk = expected.get(point_id)
            if chunk is None or point_id in observed:
                raise IndexConsistencyError("hybrid point identity changed")
            observed.add(point_id)
            if record.payload != make_chunk_payload(chunk).model_dump(mode="json"):
                raise IndexConsistencyError("hybrid payload changed")
            if not isinstance(record.vector, dict):
                raise IndexConsistencyError("hybrid named vectors are missing")
            dense_value = record.vector.get("dense-bge-v1")
            sparse_value = record.vector.get("lexical-bm25-v1")
            if not isinstance(dense_value, list) or len(dense_value) != 512:
                raise IndexConsistencyError("hybrid dense vector changed")
            if sparse_value is None or not sparse_value.indices:
                raise IndexConsistencyError("hybrid sparse vector changed")
            sparse_nonzero_count += len(sparse_value.indices)
        if offset is None:
            break
    if observed != set(expected):
        raise IndexConsistencyError("hybrid point set changed")

    first_id = sorted(expected)[0]
    dense_query = client.retrieve(
        collection_name=manifest.collection_name,
        ids=[first_id],
        with_payload=False,
        with_vectors=True,
    )[0].vector["dense-bge-v1"]
    dense_hits = client.query_points(
        collection_name=manifest.collection_name,
        query=dense_query,
        using="dense-bge-v1",
        limit=1,
    ).points
    dense_score = float(dense_hits[0].score) if dense_hits else 0.0
    if not dense_hits or str(dense_hits[0].id) != first_id or dense_score < 0.999:
        raise IndexConsistencyError("hybrid dense self-query failed")
    sparse_hits = client.query_points(
        collection_name=manifest.collection_name,
        query=sparse_corpus.vectors[UUID(first_id)],
        using="lexical-bm25-v1",
        limit=1,
    ).points
    if not sparse_hits:
        raise IndexConsistencyError("hybrid sparse self-query failed")

    version_filter = Filter(
        must=[FieldCondition(key="python_version", match=MatchValue(value="3.13"))]
    )
    filtered = client.query_points(
        collection_name=manifest.collection_name,
        query=dense_query,
        using="dense-bge-v1",
        query_filter=version_filter,
        limit=5,
        with_payload=True,
    ).points
    if not filtered or any(point.payload.get("python_version") != "3.13" for point in filtered):
        raise IndexConsistencyError("hybrid version filter failed")
    return HybridCollectionValidation(
        point_count=point_count,
        payload_count=len(observed),
        unique_point_count=len(observed),
        dense_self_query_top_score=dense_score,
        sparse_self_query_returned=True,
        version_filter_checked=True,
        sparse_nonzero_count=sparse_nonzero_count,
    )
