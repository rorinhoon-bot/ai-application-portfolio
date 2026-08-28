import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from cited_rag.hybrid_index import QdrantHybridCandidateBuilder
from cited_rag.indexing import (
    activate_index,
    load_active_index,
    make_active_pointer,
    make_chunk_payload,
    make_index_manifest,
    write_index_manifest,
    make_embedding_config_sha256,
    make_index_fingerprint,
)
from cited_rag.models import EmbeddingConfig, IndexManifest, IndexSpecification
from tests.test_retrieval import chunks

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_sparse_schema_extension_preserves_frozen_dense_identity() -> None:
    report = json.loads(
        (PROJECT_ROOT / "data" / "model-assets.json").read_text(encoding="utf-8")
    )
    config = EmbeddingConfig(
        schema_version=report["schema_version"],
        provider=report["provider"],
        model_name=report["public_model_name"],
        resolved_model_source=report["repository_id"],
        model_revision=report["revision"],
        model_assets_sha256=report["model_assets_sha256"],
        model_license=report["license"],
        model_cache_relative_path="data/models/fastembed",
        dimension=512,
        max_input_tokens=512,
        batch_size=64,
        distance="cosine",
        normalize=True,
    )
    build_report = json.loads(
        (PROJECT_ROOT / "data/server-index-build-report.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = IndexManifest.model_validate(build_report["index_manifest"])

    assert make_embedding_config_sha256(config) == (
        "db152eac59c563e8867b8debc577cccc0a267a632173845b3ac9a21013cd21bd"
    )
    assert make_index_fingerprint(manifest.specification) == (
        "ea641fef238f3e74d6f64fa923feb53f9a7f36d88b082f14cafdcaabb541c4cd"
    )


def test_hybrid_builder_keeps_dense_pointer_inactive(tmp_path: Path) -> None:
    index_root = tmp_path / "indexes"
    index_root.mkdir()
    source_specification = IndexSpecification(
        schema_version="1",
        corpus_id=UUID("5386ccee-bb5f-5417-b70a-33395abe9669"),
        source_manifest_sha256="a" * 64,
        parser_schema_version="parser-v1",
        chunking_schema_version="chunker-v1",
        chunk_config_sha256="c" * 64,
        chunk_count=3,
        embedding_config_sha256="d" * 64,
        embedding_dimension=512,
        distance="cosine",
        payload_schema_version="payload-v1",
    )
    source_manifest = make_index_manifest(
        specification=source_specification,
        build_id=UUID("00000000-0000-4000-8000-000000000051"),
        built_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        qdrant_client_version="1.18.0",
    )
    client = QdrantClient(path=str(index_root / "qdrant"))
    try:
        client.create_collection(
            collection_name=source_manifest.collection_name,
            vectors_config=VectorParams(size=512, distance=Distance.COSINE),
        )
        dense_vectors = (
            [1.0, 0.0, 0.0] + [0.0] * 509,
            [0.0, 1.0, 0.0] + [0.0] * 509,
            [0.0, 0.0, 1.0] + [0.0] * 509,
        )
        client.upsert(
            collection_name=source_manifest.collection_name,
            points=[
                PointStruct(
                    id=str(chunk.chunk_id),
                    vector=vector,
                    payload=make_chunk_payload(chunk).model_dump(mode="json"),
                )
                for chunk, vector in zip(chunks(), dense_vectors, strict=True)
            ],
            wait=True,
        )
    finally:
        client.close()
    source_pointer = make_active_pointer(source_manifest)
    write_index_manifest(
        index_root=index_root,
        pointer=source_pointer,
        manifest=source_manifest,
    )
    activate_index(
        index_root=index_root,
        pointer=source_pointer,
        manifest=source_manifest,
    )

    result = QdrantHybridCandidateBuilder(
        clock=lambda: datetime(2026, 8, 25, tzinfo=timezone.utc),
        build_id_factory=lambda: UUID("00000000-0000-4000-8000-000000000052"),
        qdrant_client_version="1.18.0",
        client_factory=lambda path: QdrantClient(path=str(path)),
    ).build(chunks=chunks(), index_root=index_root)

    active_pointer, active_manifest = load_active_index(index_root=index_root)
    assert active_pointer.build_id == source_manifest.build_id
    assert active_manifest == source_manifest
    assert result.manifest.specification.schema_version == "2"
    assert result.manifest.collection_name != source_manifest.collection_name
    assert result.validation.point_count == 3
    assert result.validation.sparse_nonzero_count > 0
    assert result.copied_dense_count == result.sparse_vector_count == 3
    assert result.vocabulary_path.is_file()
