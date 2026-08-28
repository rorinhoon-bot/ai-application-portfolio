"""Build and validate a versioned Qdrant collection."""

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
    PointStruct,
    VectorParams,
)

from cited_rag.embedding import EmbeddingService
from cited_rag.errors import IndexBuildError, IndexConsistencyError
from cited_rag.indexing import (
    ACTIVE_INDEX_FILENAME,
    active_index_matches,
    activate_index,
    load_active_index,
    make_active_pointer,
    make_chunk_payload,
    make_index_manifest,
    write_index_manifest,
)
from cited_rag.models import DocumentChunk, IndexManifest, IndexSpecification
from cited_rag.qdrant_connection import ClientFactory

Clock = Callable[[], datetime]
BuildIdFactory = Callable[[], UUID]


@dataclass(frozen=True, slots=True)
class CollectionValidation:
    """Evidence that physical collection state matches the specification."""

    point_count: int
    payload_count: int
    unique_point_count: int
    self_query_top_score: float
    version_filter_checked: bool


@dataclass(frozen=True, slots=True)
class IndexBuildResult:
    """Result of building or reusing one active index."""

    status: str
    manifest: IndexManifest
    validation: CollectionValidation
    embedded_count: int


class QdrantIndexBuilder:
    """Full-build then atomically activate a local or Server collection."""

    def __init__(
        self,
        *,
        embedding_service: EmbeddingService,
        clock: Clock,
        build_id_factory: BuildIdFactory,
        qdrant_client_version: str,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._embedding_service = embedding_service
        self._clock = clock
        self._build_id_factory = build_id_factory
        self._qdrant_client_version = qdrant_client_version
        self._client_factory = client_factory or (
            lambda path: QdrantClient(path=str(path))
        )

    def build(
        self,
        *,
        chunks: Sequence[DocumentChunk],
        specification: IndexSpecification,
        index_root: Path,
    ) -> IndexBuildResult:
        ordered_chunks = tuple(
            sorted(
                chunks,
                key=lambda chunk: (chunk.source_id, chunk.chunk_order),
            )
        )
        self._validate_inputs(
            chunks=ordered_chunks,
            specification=specification,
        )
        index_root.mkdir(parents=True, exist_ok=True)
        resolved_root = index_root.resolve(strict=True)
        qdrant_path = resolved_root / "qdrant"
        client = self._client_factory(qdrant_path)
        try:
            active_path = resolved_root / ACTIVE_INDEX_FILENAME
            if active_path.exists():
                pointer, manifest = load_active_index(
                    index_root=resolved_root
                )
                if active_index_matches(
                    pointer=pointer,
                    specification=specification,
                ):
                    validation = _validate_collection(
                        client=client,
                        manifest=manifest,
                        chunks=ordered_chunks,
                    )
                    return IndexBuildResult(
                        status="unchanged",
                        manifest=manifest,
                        validation=validation,
                        embedded_count=0,
                    )

            build_id = self._build_id_factory()
            manifest = make_index_manifest(
                specification=specification,
                build_id=build_id,
                built_at=self._clock(),
                qdrant_client_version=self._qdrant_client_version,
            )
            if client.collection_exists(manifest.collection_name):
                raise IndexConsistencyError(
                    "new build collection name already exists"
                )
            client.create_collection(
                collection_name=manifest.collection_name,
                vectors_config=VectorParams(
                    size=specification.embedding_dimension,
                    distance=Distance.COSINE,
                ),
            )

            embedded = self._embedding_service.embed_chunks(ordered_chunks)
            vectors = {item.chunk_id: item.vector for item in embedded}
            for start in range(
                0,
                len(ordered_chunks),
                self._embedding_service.batch_size,
            ):
                batch = ordered_chunks[
                    start : start + self._embedding_service.batch_size
                ]
                points = [
                    PointStruct(
                        id=str(chunk.chunk_id),
                        vector=list(vectors[chunk.chunk_id]),
                        payload=make_chunk_payload(chunk).model_dump(
                            mode="json"
                        ),
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
                        f"Qdrant upsert failed for batch "
                        f"{start // self._embedding_service.batch_size + 1}"
                    ) from error

            validation = _validate_collection(
                client=client,
                manifest=manifest,
                chunks=ordered_chunks,
            )
            pointer = make_active_pointer(manifest)
            write_index_manifest(
                index_root=resolved_root,
                pointer=pointer,
                manifest=manifest,
            )
            activate_index(
                index_root=resolved_root,
                pointer=pointer,
                manifest=manifest,
            )
            return IndexBuildResult(
                status="ready",
                manifest=manifest,
                validation=validation,
                embedded_count=len(embedded),
            )
        finally:
            client.close()

    def _validate_inputs(
        self,
        *,
        chunks: tuple[DocumentChunk, ...],
        specification: IndexSpecification,
    ) -> None:
        if len(chunks) != specification.chunk_count:
            raise IndexConsistencyError(
                "chunk count does not match index specification"
            )
        if (
            specification.embedding_dimension
            != self._embedding_service.dimension
        ):
            raise IndexConsistencyError(
                "embedding service dimension does not match specification"
            )
        chunk_ids = {chunk.chunk_id for chunk in chunks}
        if len(chunk_ids) != len(chunks):
            raise IndexConsistencyError("index contains duplicate chunk_id")
        if any(
            chunk.chunking_schema_version
            != specification.chunking_schema_version
            or chunk.chunk_config_sha256
            != specification.chunk_config_sha256
            for chunk in chunks
        ):
            raise IndexConsistencyError(
                "chunk metadata does not match index specification"
            )


def verify_active_index(
    *,
    chunks: Sequence[DocumentChunk],
    specification: IndexSpecification,
    index_root: Path,
    client_factory: ClientFactory | None = None,
) -> IndexBuildResult | None:
    """Validate an exact active index without constructing an embedder."""

    active_path = index_root / ACTIVE_INDEX_FILENAME
    if not active_path.exists():
        return None
    ordered_chunks = tuple(
        sorted(
            chunks,
            key=lambda chunk: (chunk.source_id, chunk.chunk_order),
        )
    )
    if len(ordered_chunks) != specification.chunk_count:
        raise IndexConsistencyError(
            "chunk count does not match index specification"
        )
    pointer, manifest = load_active_index(index_root=index_root)
    if not active_index_matches(
        pointer=pointer,
        specification=specification,
    ):
        return None
    factory = client_factory or (
        lambda path: QdrantClient(path=str(path))
    )
    client = factory(index_root.resolve(strict=True) / "qdrant")
    try:
        validation = _validate_collection(
            client=client,
            manifest=manifest,
            chunks=ordered_chunks,
        )
    finally:
        client.close()
    return IndexBuildResult(
        status="unchanged",
        manifest=manifest,
        validation=validation,
        embedded_count=0,
    )


def _validate_collection(
    *,
    client: QdrantClient,
    manifest: IndexManifest,
    chunks: tuple[DocumentChunk, ...],
) -> CollectionValidation:
    if not client.collection_exists(manifest.collection_name):
        raise IndexConsistencyError("Qdrant collection is missing")
    info = client.get_collection(manifest.collection_name)
    vector_params = info.config.params.vectors
    if (
        not isinstance(vector_params, VectorParams)
        or vector_params.size
        != manifest.specification.embedding_dimension
        or vector_params.distance != Distance.COSINE
    ):
        raise IndexConsistencyError("Qdrant vector configuration changed")
    point_count = client.count(
        collection_name=manifest.collection_name,
        exact=True,
    ).count
    if point_count != manifest.point_count:
        raise IndexConsistencyError("Qdrant point count does not match manifest")

    expected = {str(chunk.chunk_id): chunk for chunk in chunks}
    observed_ids: set[str] = set()
    offset = None
    payload_count = 0
    while True:
        records, offset = client.scroll(
            collection_name=manifest.collection_name,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for record in records:
            point_id = str(record.id)
            if point_id in observed_ids:
                raise IndexConsistencyError("Qdrant returned duplicate point ID")
            observed_ids.add(point_id)
            chunk = expected.get(point_id)
            if chunk is None:
                raise IndexConsistencyError("Qdrant contains an unknown point")
            expected_payload = make_chunk_payload(chunk)
            if record.payload is None:
                raise IndexConsistencyError("Qdrant point payload is missing")
            if expected_payload.model_dump(mode="json") != record.payload:
                raise IndexConsistencyError("Qdrant point payload changed")
            payload_count += 1
        if offset is None:
            break
    if observed_ids != set(expected):
        raise IndexConsistencyError("Qdrant point IDs do not match chunks")

    first_id = next(iter(sorted(expected)))
    retrieved = client.retrieve(
        collection_name=manifest.collection_name,
        ids=[first_id],
        with_payload=True,
        with_vectors=True,
    )
    if len(retrieved) != 1 or not isinstance(retrieved[0].vector, list):
        raise IndexConsistencyError("Qdrant self-query vector is unavailable")
    query_vector = retrieved[0].vector
    if len(query_vector) != manifest.specification.embedding_dimension:
        raise IndexConsistencyError("stored vector dimension changed")
    hits = client.query_points(
        collection_name=manifest.collection_name,
        query=query_vector,
        limit=5,
        with_payload=True,
    ).points
    if not hits:
        raise IndexConsistencyError("Qdrant self-query returned no points")
    top_score = float(hits[0].score)
    if top_score < 0.999:
        raise IndexConsistencyError("Qdrant self-query top score is too low")

    version_filter_checked = False
    if any(chunk.python_version == "3.13" for chunk in chunks):
        filtered = client.query_points(
            collection_name=manifest.collection_name,
            query=query_vector,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="python_version",
                        match=MatchValue(value="3.13"),
                    )
                ]
            ),
            limit=5,
            with_payload=True,
        ).points
        if not filtered or any(
            point.payload is None
            or point.payload.get("python_version") != "3.13"
            for point in filtered
        ):
            raise IndexConsistencyError(
                "Qdrant Python version filter failed"
            )
        version_filter_checked = True

    return CollectionValidation(
        point_count=point_count,
        payload_count=payload_count,
        unique_point_count=len(observed_ids),
        self_query_top_score=top_score,
        version_filter_checked=version_filter_checked,
    )
