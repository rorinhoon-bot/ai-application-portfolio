from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from uuid import UUID

import pytest
from qdrant_client import QdrantClient

from cited_rag.embedding import EmbeddingService
from cited_rag.errors import EmbeddingError, IndexConsistencyError
from cited_rag.indexing import load_active_index
from cited_rag.models import DocumentChunk, IndexSpecification
from cited_rag.qdrant_index import QdrantIndexBuilder, verify_active_index

FIXED_TIME = datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc)
BUILD_ID = UUID("00000000-0000-4000-8000-000000000099")


class TokenCounter:
    def count_tokens(self, text: str) -> int:
        return len(text)


class Provider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.passage_calls = 0
        self.vectors = {
            "Page A\n\nalpha": [1.0, 0.0, 0.0],
            "Page B\n\nbeta": [0.0, 1.0, 0.0],
            "Page C\n\ngamma": [1.0, 1.0, 0.0],
        }

    def embed_passages(self, texts, *, batch_size):
        self.passage_calls += 1
        if self.fail:
            raise RuntimeError("synthetic provider failure")
        return (self.vectors[text] for text in texts)

    def embed_query(self, text):
        return [1.0, 0.0, 0.0]


def make_chunk(
    label: str,
    *,
    source_id: str,
    python_version: str,
) -> DocumentChunk:
    text = {"a": "alpha", "b": "beta", "c": "gamma"}[label]
    page = f"Page {label.upper()}"
    release = "3.14.6" if python_version == "3.14" else "3.13.14"
    return DocumentChunk(
        chunk_id=UUID(f"00000000-0000-0000-0000-{ord(label):012d}"),
        snapshot_id=UUID(f"10000000-0000-0000-0000-{ord(label):012d}"),
        source_id=source_id,
        document_key=f"document-{label}",
        python_version=python_version,
        documentation_release=release,
        chunking_schema_version="chunker-v1",
        chunk_config_sha256="c" * 64,
        chunk_order=1,
        block_start=1,
        block_start_offset=0,
        block_end=1,
        block_end_offset=len(text),
        paragraph_start=1,
        paragraph_end=1,
        text=text,
        embedding_text=f"{page}\n\n{text}",
        section_path=(page,),
        section_anchor=f"section-{label}",
        source_url=(
            f"https://docs.python.org/zh-cn/{python_version}/"
            f"tutorial/{label}.html"
        ),
        relative_path=f"html/{release}/tutorial/{label}.html",
        content_sha256=sha256(text.encode("utf-8")).hexdigest(),
    )


def chunks() -> tuple[DocumentChunk, ...]:
    return (
        make_chunk("a", source_id="source-a", python_version="3.14"),
        make_chunk("b", source_id="source-b", python_version="3.13"),
        make_chunk("c", source_id="source-c", python_version="3.14"),
    )


def specification() -> IndexSpecification:
    return IndexSpecification(
        schema_version="1",
        corpus_id=UUID("5386ccee-bb5f-5417-b70a-33395abe9669"),
        source_manifest_sha256="a" * 64,
        parser_schema_version="parser-v1",
        chunking_schema_version="chunker-v1",
        chunk_config_sha256="c" * 64,
        chunk_count=3,
        embedding_config_sha256="d" * 64,
        embedding_dimension=3,
        distance="cosine",
        payload_schema_version="payload-v1",
    )


def builder(provider: Provider) -> QdrantIndexBuilder:
    return QdrantIndexBuilder(
        embedding_service=EmbeddingService(
            provider=provider,
            token_counter=TokenCounter(),
            dimension=3,
            max_input_tokens=512,
            batch_size=2,
        ),
        clock=lambda: FIXED_TIME,
        build_id_factory=lambda: BUILD_ID,
        qdrant_client_version=version("qdrant-client"),
    )


def test_persistent_builder_activates_then_returns_unchanged(
    tmp_path: Path,
) -> None:
    provider = Provider()
    index_root = tmp_path / "indexes"
    index_builder = builder(provider)

    first = index_builder.build(
        chunks=chunks(),
        specification=specification(),
        index_root=index_root,
    )
    calls_after_first = provider.passage_calls
    repeated = index_builder.build(
        chunks=chunks(),
        specification=specification(),
        index_root=index_root,
    )
    pointer, manifest = load_active_index(index_root=index_root)
    verified_without_provider = verify_active_index(
        chunks=chunks(),
        specification=specification(),
        index_root=index_root,
    )

    assert first.status == "ready"
    assert first.embedded_count == 3
    assert first.validation.point_count == 3
    assert first.validation.payload_count == 3
    assert first.validation.unique_point_count == 3
    assert first.validation.self_query_top_score >= 0.999
    assert first.validation.version_filter_checked
    assert repeated.status == "unchanged"
    assert repeated.embedded_count == 0
    assert provider.passage_calls == calls_after_first
    assert verified_without_provider is not None
    assert verified_without_provider.status == "unchanged"
    assert verified_without_provider.embedded_count == 0
    assert pointer.collection_name == manifest.collection_name
    assert manifest == first.manifest


def test_embedding_failure_leaves_collection_inactive(
    tmp_path: Path,
) -> None:
    index_root = tmp_path / "indexes"

    with pytest.raises(EmbeddingError, match="provider failed"):
        builder(Provider(fail=True)).build(
            chunks=chunks(),
            specification=specification(),
            index_root=index_root,
        )

    assert not (index_root / "active-index.json").exists()
    client = QdrantClient(path=str(index_root / "qdrant"))
    try:
        assert len(client.get_collections().collections) == 1
        assert client.count(
            client.get_collections().collections[0].name,
            exact=True,
        ).count == 0
    finally:
        client.close()


def test_builder_rejects_dimension_mismatch_before_qdrant_write(
    tmp_path: Path,
) -> None:
    values = specification().model_dump(mode="json")
    values["embedding_dimension"] = 512
    mismatched = IndexSpecification.model_validate(values)

    with pytest.raises(
        IndexConsistencyError,
        match="dimension does not match",
    ):
        builder(Provider()).build(
            chunks=chunks(),
            specification=mismatched,
            index_root=tmp_path / "indexes",
        )

    assert not (tmp_path / "indexes").exists()
