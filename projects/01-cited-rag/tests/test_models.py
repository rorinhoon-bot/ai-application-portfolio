from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest
from pydantic import ValidationError

from cited_rag.models import (
    ChunkingConfig,
    ContentBlock,
    ContentBlockType,
    DocumentChunk,
    DocumentSnapshot,
    SourceManifest,
    SourceManifestEntry,
)


def source_entry(**overrides: object) -> SourceManifestEntry:
    values: dict[str, object] = {
        "schema_version": "1",
        "source_id": "py314-library-venv",
        "document_key": "library-venv",
        "python_version": "3.14",
        "documentation_release": "3.14.6",
        "source_url": "https://docs.python.org/zh-cn/3.14/library/venv.html",
        "relative_path": "html/3.14/library/venv.html",
        "retrieved_at": datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc),
        "expected_title": "venv — 创建虚拟环境",
        "license_name": "Python Software Foundation License Version 2",
        "license_url": "https://docs.python.org/zh-cn/3.14/license.html",
        "raw_sha256": "a" * 64,
        "media_type": "text/html",
        "language": "zh-CN",
    }
    values.update(overrides)
    return SourceManifestEntry.model_validate(values)


def content_block(**overrides: object) -> ContentBlock:
    values: dict[str, object] = {
        "block_id": uuid4(),
        "snapshot_id": uuid4(),
        "block_order": 1,
        "paragraph_order": 1,
        "block_type": ContentBlockType.PARAGRAPH,
        "raw_text": "运行 python -m venv .venv 创建环境。",
        "clean_text": "运行 python -m venv .venv 创建环境。",
        "section_path": ("venv — 创建虚拟环境", "创建虚拟环境"),
        "section_anchor": "creating",
        "block_anchor": None,
        "list_level": None,
    }
    values.update(overrides)
    return ContentBlock.model_validate(values)


def document_chunk(**overrides: object) -> DocumentChunk:
    text = "运行 python -m venv .venv 创建环境。"
    values: dict[str, object] = {
        "chunk_id": uuid4(),
        "snapshot_id": uuid4(),
        "source_id": "py314-library-venv",
        "document_key": "library-venv",
        "python_version": "3.14",
        "documentation_release": "3.14.6",
        "chunking_schema_version": "chunker-v1",
        "chunk_config_sha256": "c" * 64,
        "chunk_order": 1,
        "block_start": 1,
        "block_start_offset": 0,
        "block_end": 2,
        "block_end_offset": 10,
        "paragraph_start": 1,
        "paragraph_end": 1,
        "text": text,
        "embedding_text": f"venv — 创建虚拟环境\n创建虚拟环境\n{text}",
        "section_path": ("venv — 创建虚拟环境", "创建虚拟环境"),
        "section_anchor": "creating",
        "source_url": "https://docs.python.org/zh-cn/3.14/library/venv.html",
        "relative_path": "html/3.14/library/venv.html",
        "content_sha256": sha256(text.encode("utf-8")).hexdigest(),
    }
    values.update(overrides)
    return DocumentChunk.model_validate(values)


def test_source_manifest_entry_accepts_approved_metadata() -> None:
    entry = source_entry()

    assert entry.source_id == "py314-library-venv"
    assert entry.python_version == "3.14"
    assert entry.documentation_release == "3.14.6"
    assert entry.relative_path == "html/3.14/library/venv.html"


@pytest.mark.parametrize(
    "relative_path",
    [
        "../secret.html",
        "/absolute/secret.html",
        "C:/secret.html",
        r"html\3.14\secret.html",
        "html//3.14/secret.html",
        "html/3.14/secret.txt",
    ],
)
def test_source_manifest_entry_rejects_unsafe_relative_path(
    relative_path: str,
) -> None:
    with pytest.raises(ValidationError):
        source_entry(relative_path=relative_path)


@pytest.mark.parametrize(
    "source_url",
    [
        "http://docs.python.org/zh-cn/3.14/library/venv.html",
        "https://example.com/zh-cn/3.14/library/venv.html",
        "https://docs.python.org/zh-cn/3.13/library/venv.html",
        "https://docs.python.org/zh-cn/3.14/library/venv.html#creating",
        "https://docs.python.org/zh-cn/3.14/library/venv.html?download=1",
    ],
)
def test_source_manifest_entry_rejects_untrusted_source_url(
    source_url: str,
) -> None:
    with pytest.raises(ValidationError):
        source_entry(source_url=source_url)


def test_source_manifest_entry_rejects_naive_retrieval_time() -> None:
    with pytest.raises(ValidationError):
        source_entry(retrieved_at=datetime(2026, 7, 28, 10, 0))


@pytest.mark.parametrize(
    "documentation_release",
    ["3.14", "3.14.x", "3.13.14", "3.15.0"],
)
def test_source_manifest_entry_rejects_invalid_documentation_release(
    documentation_release: str,
) -> None:
    with pytest.raises(ValidationError):
        source_entry(documentation_release=documentation_release)


def test_source_manifest_rejects_duplicate_source_id() -> None:
    entry = source_entry()

    with pytest.raises(ValidationError, match="duplicate source_id"):
        SourceManifest(schema_version="1", sources=(entry, entry))


def test_source_manifest_rejects_second_active_snapshot() -> None:
    first = source_entry()
    second = source_entry(
        source_id="py314-library-venv-copy",
        source_url="https://docs.python.org/zh-cn/3.14/library/venv-copy.html",
        relative_path="html/3.14/library/venv-copy.html",
        raw_sha256="b" * 64,
    )

    with pytest.raises(ValidationError, match="duplicate active document version"):
        SourceManifest(schema_version="1", sources=(first, second))


def test_source_manifest_accepts_same_document_key_across_versions() -> None:
    python_314 = source_entry()
    python_313 = source_entry(
        source_id="py313-library-venv",
        python_version="3.13",
        documentation_release="3.13.14",
        source_url="https://docs.python.org/zh-cn/3.13/library/venv.html",
        relative_path="html/3.13/library/venv.html",
        license_url="https://docs.python.org/zh-cn/3.13/license.html",
        raw_sha256="a" * 64,
    )

    manifest = SourceManifest(
        schema_version="1",
        sources=(python_314, python_313),
    )

    assert len(manifest.sources) == 2


def test_source_manifest_rejects_duplicate_source_url() -> None:
    first = source_entry()
    second = source_entry(
        source_id="py314-library-venv-alias",
        document_key="library-venv-alias",
        relative_path="html/3.14/library/venv-alias.html",
        raw_sha256="b" * 64,
    )

    with pytest.raises(ValidationError, match="duplicate source_url"):
        SourceManifest(schema_version="1", sources=(first, second))


def test_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        source_entry(model_generated_url="https://example.com")


def test_document_snapshot_requires_aware_import_time() -> None:
    with pytest.raises(ValidationError):
        DocumentSnapshot(
            snapshot_id=uuid4(),
            source_id="py314-library-venv",
            page_title="venv — 创建虚拟环境",
            html_canonical_url=(
                "https://docs.python.org/zh-cn/3.14/library/venv.html"
            ),
            raw_html_sha256="a" * 64,
            cleaned_content_sha256="b" * 64,
            parser_schema_version="parser-v1",
            imported_at=datetime(2026, 7, 28, 10, 0),
        )


def test_code_block_must_preserve_exact_text() -> None:
    with pytest.raises(
        ValidationError,
        match="code block clean_text must equal raw_text",
    ):
        content_block(
            block_type=ContentBlockType.CODE,
            paragraph_order=None,
            raw_text="  python -m venv .venv\n",
            clean_text="python -m venv .venv",
        )


def test_paragraph_requires_paragraph_order() -> None:
    with pytest.raises(ValidationError, match="require paragraph_order"):
        content_block(paragraph_order=None)


def test_list_item_requires_list_level() -> None:
    with pytest.raises(ValidationError, match="require list_level"):
        content_block(
            block_type=ContentBlockType.LIST_ITEM,
            paragraph_order=None,
        )


def test_document_chunk_accepts_consistent_metadata() -> None:
    chunk = document_chunk()

    assert chunk.block_start == 1
    assert chunk.block_start_offset == 0
    assert chunk.block_end == 2
    assert chunk.block_end_offset == 10
    assert chunk.embedding_text.endswith(chunk.text)


def test_document_chunk_preserves_code_whitespace() -> None:
    text = "  python -m venv .venv\n"

    chunk = document_chunk(
        paragraph_start=None,
        paragraph_end=None,
        text=text,
        embedding_text=f"venv — 创建虚拟环境\n{text}",
        content_sha256=sha256(text.encode("utf-8")).hexdigest(),
    )

    assert chunk.text == text


def test_document_chunk_rejects_reversed_block_range() -> None:
    with pytest.raises(ValidationError, match="block_start must not exceed"):
        document_chunk(block_start=3, block_end=2)


def test_document_chunk_rejects_empty_same_block_range() -> None:
    with pytest.raises(ValidationError, match="start offset must be less"):
        document_chunk(
            block_start=2,
            block_start_offset=8,
            block_end=2,
            block_end_offset=8,
        )


def test_document_chunk_requires_complete_paragraph_range() -> None:
    with pytest.raises(ValidationError, match="must both be set or both be null"):
        document_chunk(paragraph_end=None)


def test_document_chunk_rejects_text_hash_mismatch() -> None:
    with pytest.raises(ValidationError, match="content_sha256 must match"):
        document_chunk(content_sha256="f" * 64)


def test_document_chunk_requires_citation_text_in_embedding_text() -> None:
    with pytest.raises(ValidationError, match="must end with citation text"):
        document_chunk(embedding_text="只有标题，没有引用正文")


def chunking_config(**overrides: object) -> ChunkingConfig:
    values: dict[str, object] = {
        "schema_version": "1",
        "max_characters": 800,
        "overlap_characters": 120,
        "block_separator": "\n\n",
        "minimum_split_characters": 400,
        "include_section_path": True,
    }
    values.update(overrides)
    return ChunkingConfig.model_validate(values)


def test_chunking_config_accepts_baseline() -> None:
    config = chunking_config()

    assert config.max_characters == 800
    assert config.overlap_characters == 120
    assert config.block_separator == "\n\n"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("overlap_characters", 800, "must be less"),
        ("minimum_split_characters", 801, "must not exceed"),
        ("block_separator", "\n", "Input should be"),
    ],
)
def test_chunking_config_rejects_invalid_values(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        chunking_config(**{field: value})
