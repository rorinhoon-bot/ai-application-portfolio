from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from math import isclose
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
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
from cited_rag.errors import (
    EmbeddingError,
    EmbeddingInputTooLongError,
    IndexBuildError,
    IndexConsistencyError,
    VectorDimensionMismatchError,
    VectorValueInvalidError,
)
from cited_rag.indexing import (
    active_index_matches,
    activate_index,
    load_active_index,
    make_active_pointer,
    make_chunk_payload,
    make_embedding_config_sha256,
    make_index_fingerprint,
    make_index_id,
    make_index_manifest,
    write_index_manifest,
)
from cited_rag.models import (
    ActiveIndexPointer,
    DocumentChunk,
    EmbeddingConfig,
    IndexManifest,
    IndexSpecification,
)

FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "embedding"
    / "fake_vectors.json"
)
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
FIXED_TIME = datetime(2026, 7, 28, 14, 0, tzinfo=timezone.utc)
QDRANT_CLIENT_VERSION = version("qdrant-client")


class FakeTokenCounter:
    def __init__(self, overrides: dict[str, int] | None = None) -> None:
        self.overrides = overrides or {}
        self.calls: list[str] = []

    def count_tokens(self, text: str) -> int:
        self.calls.append(text)
        return self.overrides.get(text, len(text))


class FakeEmbeddingProvider:
    def __init__(
        self,
        *,
        passages: dict[str, list[float]] | None = None,
        queries: dict[str, list[float]] | None = None,
    ) -> None:
        self.passages = passages or FIXTURE["passages"]
        self.queries = queries or FIXTURE["queries"]
        self.passage_calls: list[tuple[tuple[str, ...], int]] = []
        self.query_calls: list[str] = []

    def embed_passages(
        self,
        texts: tuple[str, ...],
        *,
        batch_size: int,
    ):
        self.passage_calls.append((texts, batch_size))
        return (self.passages[text] for text in texts)

    def embed_query(self, text: str):
        self.query_calls.append(text)
        return self.queries[text]


def make_chunk(
    label: str,
    *,
    source_id: str,
    python_version: str = "3.14",
    chunk_order: int = 1,
) -> DocumentChunk:
    text = {
        "a": "alpha",
        "b": "beta",
        "c": "gamma",
    }[label]
    page = f"Page {label.upper()}"
    release = "3.14.6" if python_version == "3.14" else "3.13.14"
    source_url = (
        f"https://docs.python.org/zh-cn/{python_version}/"
        f"tutorial/{label}.html"
    )
    return DocumentChunk(
        chunk_id=UUID(f"00000000-0000-0000-0000-{ord(label):012d}"),
        snapshot_id=UUID(f"10000000-0000-0000-0000-{ord(label):012d}"),
        source_id=source_id,
        document_key=f"document-{label}",
        python_version=python_version,
        documentation_release=release,
        chunking_schema_version="chunker-v1",
        chunk_config_sha256="c" * 64,
        chunk_order=chunk_order,
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
        source_url=source_url,
        relative_path=(
            f"html/{release}/tutorial/{label}.html"
        ),
        content_sha256=sha256(text.encode("utf-8")).hexdigest(),
    )


def embedding_config(**overrides: object) -> EmbeddingConfig:
    values: dict[str, object] = {
        "schema_version": "1",
        "provider": "fastembed",
        "model_name": "BAAI/bge-small-zh-v1.5",
        "resolved_model_source": "Qdrant/bge-small-zh-v1.5",
        "model_revision": "1" * 40,
        "model_assets_sha256": "2" * 64,
        "model_license": "mit",
        "model_cache_relative_path": "data/models/fastembed",
        "dimension": 512,
        "max_input_tokens": 512,
        "batch_size": 64,
        "distance": "cosine",
        "normalize": True,
        "query_instruction": None,
        "passage_instruction": None,
    }
    values.update(overrides)
    return EmbeddingConfig.model_validate(values)


def index_specification(**overrides: object) -> IndexSpecification:
    values: dict[str, object] = {
        "schema_version": "1",
        "corpus_id": UUID("5386ccee-bb5f-5417-b70a-33395abe9669"),
        "source_manifest_sha256": (
            "60258d7589162244cce9dc24ef79a26fe"
            "7f1cee1d05af5692f228d614947ae43"
        ),
        "parser_schema_version": "parser-v1",
        "chunking_schema_version": "chunker-v1",
        "chunk_config_sha256": "3" * 64,
        "chunk_count": 3,
        "embedding_config_sha256": make_embedding_config_sha256(
            embedding_config()
        ),
        "embedding_dimension": 512,
        "distance": "cosine",
        "payload_schema_version": "payload-v1",
    }
    values.update(overrides)
    return IndexSpecification.model_validate(values)


def embedding_service(
    provider: FakeEmbeddingProvider,
    *,
    token_counter: FakeTokenCounter | None = None,
) -> EmbeddingService:
    return EmbeddingService(
        provider=provider,
        token_counter=token_counter or FakeTokenCounter(),
        dimension=FIXTURE["dimension"],
        max_input_tokens=FIXTURE["max_input_tokens"],
        batch_size=FIXTURE["batch_size"],
    )


def test_fake_embedding_fixture_is_explicitly_synthetic() -> None:
    assert FIXTURE["fixture_marker"] == "synthetic test fixture"
    assert FIXTURE["dimension"] == 3
    assert set(FIXTURE["passages"]) == {
        "Page A\n\nalpha",
        "Page B\n\nbeta",
        "Page C\n\ngamma",
    }


def test_embedding_batches_preserve_stable_chunk_order_and_normalize() -> None:
    provider = FakeEmbeddingProvider()
    service = embedding_service(provider)
    chunks = (
        make_chunk("c", source_id="source-c"),
        make_chunk("a", source_id="source-a"),
        make_chunk("b", source_id="source-b"),
    )

    embedded = service.embed_chunks(chunks)

    assert [item.chunk_id for item in embedded] == [
        make_chunk("a", source_id="source-a").chunk_id,
        make_chunk("b", source_id="source-b").chunk_id,
        make_chunk("c", source_id="source-c").chunk_id,
    ]
    assert provider.passage_calls == [
        (("Page A\n\nalpha", "Page B\n\nbeta"), 2),
        (("Page C\n\ngamma",), 2),
    ]
    assert embedded[0].vector == (1.0, 0.0, 0.0)
    assert embedded[1].vector == (0.0, 1.0, 0.0)
    assert isclose(embedded[2].vector[0], 2**-0.5, rel_tol=1e-6)
    assert isclose(embedded[2].vector[1], 2**-0.5, rel_tol=1e-6)


def test_token_preflight_rejects_all_chunks_before_provider_call() -> None:
    provider = FakeEmbeddingProvider()
    too_long = "Page C\n\ngamma"
    counter = FakeTokenCounter({too_long: 513})
    service = embedding_service(provider, token_counter=counter)

    with pytest.raises(
        EmbeddingInputTooLongError,
        match="EMBEDDING_INPUT_TOO_LONG.*512",
    ):
        service.embed_chunks(
            (
                make_chunk("a", source_id="source-a"),
                make_chunk("c", source_id="source-c"),
            )
        )

    assert provider.passage_calls == []


def test_provider_count_mismatch_fails_batch() -> None:
    class MissingVectorProvider(FakeEmbeddingProvider):
        def embed_passages(self, texts, *, batch_size):
            self.passage_calls.append((tuple(texts), batch_size))
            return []

    provider = MissingVectorProvider()

    with pytest.raises(EmbeddingError, match="EMBEDDING_ERROR.*count mismatch"):
        embedding_service(provider).embed_chunks(
            (make_chunk("a", source_id="source-a"),)
        )


@pytest.mark.parametrize(
    ("vector", "error_type", "reason"),
    [
        ([1.0, 0.0], VectorDimensionMismatchError, "expected 3"),
        ([float("nan"), 0.0, 1.0], VectorValueInvalidError, "non-finite"),
        ([float("inf"), 0.0, 1.0], VectorValueInvalidError, "non-finite"),
        ([0.0, 0.0, 0.0], VectorValueInvalidError, "non-zero"),
    ],
)
def test_vector_contract_rejects_invalid_output(
    vector: list[float],
    error_type: type[Exception],
    reason: str,
) -> None:
    provider = FakeEmbeddingProvider(
        passages={"Page A\n\nalpha": vector}
    )

    with pytest.raises(error_type, match=reason):
        embedding_service(provider).embed_chunks(
            (make_chunk("a", source_id="source-a"),)
        )


def test_query_uses_same_token_and_vector_contract() -> None:
    provider = FakeEmbeddingProvider()
    service = embedding_service(provider)

    vector = service.embed_query("alpha query")

    assert vector == (1.0, 0.0, 0.0)
    assert provider.query_calls == ["alpha query"]


def test_embedding_config_is_strict_and_pinned() -> None:
    config = embedding_config()

    assert config.dimension == 512
    assert config.model_cache_relative_path == "data/models/fastembed"
    with pytest.raises(ValidationError):
        embedding_config(dimension=3)
    with pytest.raises(ValidationError):
        embedding_config(extra_field="forbidden")


@pytest.mark.parametrize(
    "changed_config",
    [
        {"model_revision": "4" * 40},
        {"model_assets_sha256": "5" * 64},
        {"batch_size": 32},
    ],
)
def test_embedding_config_hash_tracks_all_pinned_inputs(
    changed_config: dict[str, object],
) -> None:
    assert make_embedding_config_sha256(
        embedding_config(**changed_config)
    ) != make_embedding_config_sha256(embedding_config())


@pytest.mark.parametrize(
    "change",
    [
        {"corpus_id": UUID("6386ccee-bb5f-5417-b70a-33395abe9669")},
        {"chunk_config_sha256": "4" * 64},
        {"embedding_config_sha256": "5" * 64},
        {"embedding_dimension": 3},
    ],
)
def test_index_fingerprint_changes_with_logical_input(
    change: dict[str, object],
) -> None:
    original = index_specification()
    changed = original.model_copy(update=change)

    assert make_index_fingerprint(changed) != make_index_fingerprint(original)
    assert make_index_id(changed) != make_index_id(original)


def test_index_specification_rejects_unknown_payload_schema() -> None:
    values = index_specification().model_dump(mode="json")
    values["payload_schema_version"] = "payload-v2"

    with pytest.raises(ValidationError, match="payload-v1"):
        IndexSpecification.model_validate(values)


def test_index_identity_and_manifest_are_repeatable() -> None:
    specification = index_specification()
    build_id = UUID("00000000-0000-4000-8000-000000000001")

    first = make_index_manifest(
        specification=specification,
        build_id=build_id,
        built_at=FIXED_TIME,
        qdrant_client_version=QDRANT_CLIENT_VERSION,
    )
    repeated = make_index_manifest(
        specification=specification,
        build_id=build_id,
        built_at=FIXED_TIME,
        qdrant_client_version=QDRANT_CLIENT_VERSION,
    )

    assert first == repeated
    assert first.index_id.version == 5
    assert first.collection_name.startswith("cited-rag-")
    assert first.point_count == specification.chunk_count


def test_index_manifest_rejects_point_count_mismatch() -> None:
    manifest = make_index_manifest(
        specification=index_specification(),
        build_id=UUID("00000000-0000-4000-8000-000000000001"),
        built_at=FIXED_TIME,
        qdrant_client_version=QDRANT_CLIENT_VERSION,
    )

    with pytest.raises(ValidationError, match="point_count"):
        IndexManifest.model_validate(
            {
                **manifest.model_dump(mode="json"),
                "point_count": 2,
            }
        )


def test_payload_contains_trace_fields_but_not_embedding_or_raw_html() -> None:
    chunk = make_chunk("a", source_id="source-a")

    payload = make_chunk_payload(chunk)
    dumped = payload.model_dump(mode="json")

    assert dumped["text"] == "alpha"
    assert (
        str(payload.source_url) + "#" + payload.section_anchor
        == "https://docs.python.org/zh-cn/3.14/tutorial/a.html#section-a"
    )
    assert "embedding_text" not in dumped
    assert "raw_text" not in dumped
    assert "absolute_path" not in dumped
    assert "license_name" not in dumped


def test_payload_preserves_code_chunk_trailing_newline() -> None:
    chunk = make_chunk("a", source_id="source-a").model_copy(
        update={
            "text": "print('alpha')\n",
            "embedding_text": "Page A\n\nprint('alpha')\n",
            "content_sha256": sha256(
                "print('alpha')\n".encode("utf-8")
            ).hexdigest(),
            "block_end_offset": len("print('alpha')\n"),
        }
    )

    payload = make_chunk_payload(chunk)

    assert payload.text == "print('alpha')\n"


def test_manifest_and_active_pointer_round_trip(tmp_path: Path) -> None:
    specification = index_specification()
    manifest = make_index_manifest(
        specification=specification,
        build_id=UUID("00000000-0000-4000-8000-000000000001"),
        built_at=FIXED_TIME,
        qdrant_client_version=QDRANT_CLIENT_VERSION,
    )
    pointer = make_active_pointer(manifest)

    write_index_manifest(
        index_root=tmp_path,
        pointer=pointer,
        manifest=manifest,
    )
    active_path = activate_index(
        index_root=tmp_path,
        pointer=pointer,
        manifest=manifest,
    )
    loaded_pointer, loaded_manifest = load_active_index(index_root=tmp_path)

    assert active_path == tmp_path / "active-index.json"
    assert loaded_pointer == pointer
    assert loaded_manifest == manifest
    assert active_index_matches(
        pointer=loaded_pointer,
        specification=specification,
    )


def test_failed_final_replace_preserves_old_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_manifest = make_index_manifest(
        specification=index_specification(),
        build_id=UUID("00000000-0000-4000-8000-000000000001"),
        built_at=FIXED_TIME,
        qdrant_client_version=QDRANT_CLIENT_VERSION,
    )
    old_pointer = make_active_pointer(old_manifest)
    write_index_manifest(
        index_root=tmp_path,
        pointer=old_pointer,
        manifest=old_manifest,
    )
    active_path = activate_index(
        index_root=tmp_path,
        pointer=old_pointer,
        manifest=old_manifest,
    )
    old_bytes = active_path.read_bytes()

    new_manifest = make_index_manifest(
        specification=index_specification(chunk_config_sha256="9" * 64),
        build_id=UUID("00000000-0000-4000-8000-000000000002"),
        built_at=FIXED_TIME,
        qdrant_client_version=QDRANT_CLIENT_VERSION,
    )
    new_pointer = make_active_pointer(new_manifest)
    write_index_manifest(
        index_root=tmp_path,
        pointer=new_pointer,
        manifest=new_manifest,
    )

    def fail_replace(_source, _target):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr("cited_rag.indexing.os.replace", fail_replace)

    with pytest.raises(
        IndexBuildError,
        match="INDEX_BUILD_ERROR.*replace active index pointer",
    ):
        activate_index(
            index_root=tmp_path,
            pointer=new_pointer,
            manifest=new_manifest,
        )

    assert active_path.read_bytes() == old_bytes


def test_active_pointer_rejects_path_traversal() -> None:
    manifest = make_index_manifest(
        specification=index_specification(),
        build_id=UUID("00000000-0000-4000-8000-000000000001"),
        built_at=FIXED_TIME,
        qdrant_client_version=QDRANT_CLIENT_VERSION,
    )
    values = make_active_pointer(manifest).model_dump(mode="json")
    values["manifest_relative_path"] = "../outside.json"

    with pytest.raises(ValidationError, match="\\.\\."):
        ActiveIndexPointer.model_validate(values)


def test_qdrant_memory_retrieval_and_version_filter() -> None:
    chunks = (
        make_chunk("a", source_id="source-a", python_version="3.14"),
        make_chunk("b", source_id="source-b", python_version="3.13"),
        make_chunk("c", source_id="source-c", python_version="3.14"),
    )
    provider = FakeEmbeddingProvider()
    embedded = embedding_service(provider).embed_chunks(chunks)
    vectors = {item.chunk_id: item.vector for item in embedded}
    client = QdrantClient(":memory:")
    collection = "synthetic-cited-rag"
    try:
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(
                size=FIXTURE["dimension"],
                distance=Distance.COSINE,
            ),
        )
        client.upsert(
            collection_name=collection,
            wait=True,
            points=[
                PointStruct(
                    id=str(chunk.chunk_id),
                    vector=list(vectors[chunk.chunk_id]),
                    payload=make_chunk_payload(chunk).model_dump(mode="json"),
                )
                for chunk in chunks
            ],
        )

        unfiltered = client.query_points(
            collection_name=collection,
            query=[1.0, 0.0, 0.0],
            limit=3,
            with_payload=True,
        ).points
        filtered = client.query_points(
            collection_name=collection,
            query=[1.0, 0.0, 0.0],
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="python_version",
                        match=MatchValue(value="3.13"),
                    )
                ]
            ),
            limit=3,
            with_payload=True,
        ).points

        assert str(unfiltered[0].id) == str(chunks[0].chunk_id)
        assert [point.payload["python_version"] for point in filtered] == [
            "3.13"
        ]
        assert filtered[0].payload["chunk_id"] == str(chunks[1].chunk_id)
        assert (
            filtered[0].payload["source_url"]
            + "#"
            + filtered[0].payload["section_anchor"]
            == "https://docs.python.org/zh-cn/3.13/tutorial/b.html#section-b"
        )
    finally:
        client.close()
