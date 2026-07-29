"""Deterministic index metadata and safe active-pointer handling."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ValidationError

from cited_rag.errors import IndexBuildError, IndexConsistencyError
from cited_rag.models import (
    ActiveIndexPointer,
    ChunkPayload,
    DocumentChunk,
    EmbeddingConfig,
    ImportedCorpus,
    IndexManifest,
    IndexSpecification,
)

INDEX_IDENTITY_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "urn:cited-rag:index-identity:v1",
)
ACTIVE_INDEX_FILENAME = "active-index.json"


def make_embedding_config_sha256(config: EmbeddingConfig) -> str:
    """Hash the complete pinned embedding configuration."""

    return _canonical_model_sha256(config)


def make_index_specification(
    *,
    corpus: ImportedCorpus,
    chunks: Sequence[DocumentChunk],
    embedding_config: EmbeddingConfig,
) -> IndexSpecification:
    """Bind one complete corpus, Chunk set and embedding identity."""

    if not chunks:
        raise IndexConsistencyError("index requires at least one chunk")
    chunk_ids: set[UUID] = set()
    source_orders: defaultdict[str, list[int]] = defaultdict(list)
    chunking_schema_versions: set[str] = set()
    chunk_config_hashes: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in chunk_ids:
            raise IndexConsistencyError("index contains duplicate chunk_id")
        chunk_ids.add(chunk.chunk_id)
        source_orders[chunk.source_id].append(chunk.chunk_order)
        chunking_schema_versions.add(chunk.chunking_schema_version)
        chunk_config_hashes.add(chunk.chunk_config_sha256)

    expected_source_ids = {
        source.source_id for source in corpus.manifest.sources
    }
    if set(source_orders) != expected_source_ids:
        raise IndexConsistencyError(
            "chunk sources do not exactly match corpus manifest"
        )
    for source_id, orders in source_orders.items():
        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise IndexConsistencyError(
                f"chunk order is not contiguous: {source_id}"
            )
    if len(chunking_schema_versions) != 1:
        raise IndexConsistencyError(
            "chunks use different chunking schema versions"
        )
    if len(chunk_config_hashes) != 1:
        raise IndexConsistencyError(
            "chunks use different chunk configuration hashes"
        )

    return IndexSpecification(
        schema_version="1",
        corpus_id=corpus.corpus_id,
        source_manifest_sha256=corpus.manifest_sha256,
        parser_schema_version=corpus.parser_schema_version,
        chunking_schema_version=next(iter(chunking_schema_versions)),
        chunk_config_sha256=next(iter(chunk_config_hashes)),
        chunk_count=len(chunks),
        embedding_config_sha256=make_embedding_config_sha256(
            embedding_config
        ),
        embedding_dimension=embedding_config.dimension,
        distance=embedding_config.distance,
        payload_schema_version="payload-v1",
    )


def make_index_fingerprint(specification: IndexSpecification) -> str:
    """Hash every deterministic input to one logical index."""

    return _canonical_model_sha256(specification)


def make_index_id(specification: IndexSpecification) -> UUID:
    """Create a repeatable UUIDv5 for a logical index."""

    return uuid5(
        INDEX_IDENTITY_NAMESPACE,
        f"index|{make_index_fingerprint(specification)}",
    )


def make_collection_name(*, index_id: UUID, build_id: UUID) -> str:
    """Create a safe physical collection name for one build."""

    return f"cited-rag-{index_id.hex[:12]}-{build_id.hex[:12]}"


def make_index_manifest(
    *,
    specification: IndexSpecification,
    build_id: UUID,
    built_at: datetime,
    qdrant_client_version: str,
) -> IndexManifest:
    """Construct a self-consistent ready manifest after physical validation."""

    fingerprint = make_index_fingerprint(specification)
    index_id = make_index_id(specification)
    return IndexManifest(
        schema_version="1",
        index_id=index_id,
        index_fingerprint=fingerprint,
        build_id=build_id,
        collection_name=make_collection_name(
            index_id=index_id,
            build_id=build_id,
        ),
        built_at=built_at,
        status="ready",
        specification=specification,
        point_count=specification.chunk_count,
        qdrant_client_version=qdrant_client_version,
    )


def validate_index_manifest(manifest: IndexManifest) -> None:
    """Reject a manifest whose stored deterministic identity was altered."""

    expected_fingerprint = make_index_fingerprint(manifest.specification)
    if manifest.index_fingerprint != expected_fingerprint:
        raise IndexConsistencyError(
            "index fingerprint does not match specification"
        )
    expected_index_id = make_index_id(manifest.specification)
    if manifest.index_id != expected_index_id:
        raise IndexConsistencyError(
            "index_id does not match specification"
        )
    expected_collection = make_collection_name(
        index_id=manifest.index_id,
        build_id=manifest.build_id,
    )
    if manifest.collection_name != expected_collection:
        raise IndexConsistencyError(
            "collection_name does not match index and build IDs"
        )


def make_chunk_payload(chunk: DocumentChunk) -> ChunkPayload:
    """Copy only approved, traceable payload-v1 fields from a Chunk."""

    return ChunkPayload(
        payload_schema_version="payload-v1",
        chunk_id=chunk.chunk_id,
        snapshot_id=chunk.snapshot_id,
        source_id=chunk.source_id,
        document_key=chunk.document_key,
        python_version=chunk.python_version,
        documentation_release=chunk.documentation_release,
        chunk_order=chunk.chunk_order,
        block_start=chunk.block_start,
        block_start_offset=chunk.block_start_offset,
        block_end=chunk.block_end,
        block_end_offset=chunk.block_end_offset,
        paragraph_start=chunk.paragraph_start,
        paragraph_end=chunk.paragraph_end,
        text=chunk.text,
        section_path=chunk.section_path,
        section_anchor=chunk.section_anchor,
        source_url=chunk.source_url,
        relative_path=chunk.relative_path,
        content_sha256=chunk.content_sha256,
        chunking_schema_version=chunk.chunking_schema_version,
        chunk_config_sha256=chunk.chunk_config_sha256,
    )


def make_active_pointer(manifest: IndexManifest) -> ActiveIndexPointer:
    """Create the small pointer written only after build validation."""

    validate_index_manifest(manifest)
    return ActiveIndexPointer(
        schema_version="1",
        index_id=manifest.index_id,
        build_id=manifest.build_id,
        collection_name=manifest.collection_name,
        manifest_relative_path=(
            f"manifests/{manifest.build_id}.json"
        ),
        index_fingerprint=manifest.index_fingerprint,
    )


def write_index_manifest(
    *,
    index_root: Path,
    pointer: ActiveIndexPointer,
    manifest: IndexManifest,
) -> Path:
    """Write one immutable manifest before active-pointer replacement."""

    _validate_pointer_matches_manifest(pointer=pointer, manifest=manifest)
    root = _resolve_index_root(index_root)
    target = _resolve_new_index_file(
        root=root,
        relative_path=pointer.manifest_relative_path,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = _load_index_manifest(target)
        if existing != manifest:
            raise IndexConsistencyError(
                "existing build manifest has different content"
            )
        return target
    _write_new_json_file(target=target, value=manifest)
    return target


def activate_index(
    *,
    index_root: Path,
    pointer: ActiveIndexPointer,
    manifest: IndexManifest,
) -> Path:
    """Atomically replace the active pointer after manifest verification."""

    _validate_pointer_matches_manifest(pointer=pointer, manifest=manifest)
    root = _resolve_index_root(index_root)
    manifest_path = _resolve_existing_index_file(
        root=root,
        relative_path=pointer.manifest_relative_path,
    )
    stored_manifest = _load_index_manifest(manifest_path)
    if stored_manifest != manifest:
        raise IndexConsistencyError(
            "stored build manifest does not match activation request"
        )

    target = root / ACTIVE_INDEX_FILENAME
    serialized = _canonical_model_json(pointer) + "\n"
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=".active-index-",
            suffix=".tmp",
            dir=root,
            delete=False,
        ) as temporary:
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        try:
            os.replace(temporary_path, target)
        except OSError as error:
            raise IndexBuildError(
                "could not replace active index pointer"
            ) from error
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return target


def load_active_index(
    *,
    index_root: Path,
) -> tuple[ActiveIndexPointer, IndexManifest]:
    """Load and cross-check the active pointer and immutable manifest."""

    root = _resolve_index_root(index_root)
    pointer_path = root / ACTIVE_INDEX_FILENAME
    if not pointer_path.is_file():
        raise IndexConsistencyError("active index pointer is missing")
    try:
        pointer = ActiveIndexPointer.model_validate_json(
            pointer_path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise IndexConsistencyError(
            "active index pointer is invalid"
        ) from error

    manifest_path = _resolve_existing_index_file(
        root=root,
        relative_path=pointer.manifest_relative_path,
    )
    manifest = _load_index_manifest(manifest_path)
    _validate_pointer_matches_manifest(pointer=pointer, manifest=manifest)
    return pointer, manifest


def active_index_matches(
    *,
    pointer: ActiveIndexPointer,
    specification: IndexSpecification,
) -> bool:
    """Check logical identity before any provider call."""

    return (
        pointer.index_fingerprint
        == make_index_fingerprint(specification)
        and pointer.index_id == make_index_id(specification)
    )


def _validate_pointer_matches_manifest(
    *,
    pointer: ActiveIndexPointer,
    manifest: IndexManifest,
) -> None:
    validate_index_manifest(manifest)
    if (
        pointer.index_id != manifest.index_id
        or pointer.build_id != manifest.build_id
        or pointer.collection_name != manifest.collection_name
        or pointer.index_fingerprint != manifest.index_fingerprint
    ):
        raise IndexConsistencyError(
            "active pointer does not match build manifest"
        )


def _canonical_model_json(value: BaseModel) -> str:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_model_sha256(value: BaseModel) -> str:
    return sha256(_canonical_model_json(value).encode("utf-8")).hexdigest()


def _resolve_index_root(index_root: Path) -> Path:
    try:
        root = index_root.resolve(strict=True)
    except OSError as error:
        raise IndexConsistencyError("index root is unavailable") from error
    if not root.is_dir():
        raise IndexConsistencyError("index root is not a directory")
    return root


def _resolve_new_index_file(*, root: Path, relative_path: str) -> Path:
    lexical = root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        parent = lexical.parent.resolve(strict=False)
        parent.relative_to(root)
    except (OSError, ValueError) as error:
        raise IndexConsistencyError(
            "index manifest path escapes index root"
        ) from error
    return parent / lexical.name


def _resolve_existing_index_file(*, root: Path, relative_path: str) -> Path:
    lexical = root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise IndexConsistencyError(
            "index manifest path is unavailable or escapes index root"
        ) from error
    if not resolved.is_file():
        raise IndexConsistencyError("index manifest is not a regular file")
    return resolved


def _write_new_json_file(*, target: Path, value: BaseModel) -> None:
    serialized = _canonical_model_json(value) + "\n"
    try:
        with target.open("x", encoding="utf-8", newline="\n") as file:
            file.write(serialized)
            file.flush()
            os.fsync(file.fileno())
    except FileExistsError:
        raise
    except OSError as error:
        raise IndexConsistencyError(
            "could not write build manifest"
        ) from error


def _load_index_manifest(path: Path) -> IndexManifest:
    try:
        manifest = IndexManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise IndexConsistencyError("build manifest is invalid") from error
    validate_index_manifest(manifest)
    return manifest
