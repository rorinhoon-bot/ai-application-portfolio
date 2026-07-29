from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from cited_rag.chunking import (
    BASELINE_CHUNKING_CONFIG,
    CHUNKING_SCHEMA_VERSION,
    DocumentChunker,
    make_chunk_config_sha256,
)
from cited_rag.errors import ChunkingError
from cited_rag.models import (
    ChunkingConfig,
    ContentBlock,
    DocumentSnapshot,
    ImportedDocument,
    SourceManifestEntry,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "chunking"
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000001")


def test_production_chunking_baseline_is_tokenizer_safe_candidate() -> None:
    assert BASELINE_CHUNKING_CONFIG == ChunkingConfig(
        schema_version="1",
        max_characters=520,
        overlap_characters=80,
        block_separator="\n\n",
        minimum_split_characters=260,
        include_section_path=True,
    )
    assert (
        make_chunk_config_sha256(BASELINE_CHUNKING_CONFIG)
        == "ff8d07e2916a175093ce9c06920013dda95e6ce61036ece84ac34e614c9b28b4"
    )


def load_fixture(name: str) -> dict[str, object]:
    return json.loads(
        (FIXTURE_ROOT / name).read_text(encoding="utf-8")
    )


def make_document(fixture: dict[str, object]) -> ImportedDocument:
    blocks = tuple(
        ContentBlock.model_validate(
            {
                "block_id": UUID(
                    f"00000000-0000-0000-0000-"
                    f"{block['block_order']:012d}"
                ),
                "snapshot_id": SNAPSHOT_ID,
                "block_order": block["block_order"],
                "paragraph_order": block["paragraph_order"],
                "block_type": block["block_type"],
                "raw_text": block["clean_text"],
                "clean_text": block["clean_text"],
                "section_path": block["section_path"],
                "section_anchor": block["section_anchor"],
                "block_anchor": None,
                "list_level": block.get("list_level"),
            }
        )
        for block in fixture["blocks"]
    )
    source = SourceManifestEntry(
        schema_version="1",
        source_id="py3146-chunk-fixture",
        document_key="chunk-fixture",
        python_version="3.14",
        documentation_release="3.14.6",
        source_url=(
            "https://docs.python.org/zh-cn/3.14/tutorial/index.html"
        ),
        relative_path="html/3.14.6/tutorial/index.html",
        retrieved_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
        expected_title="Page",
        license_name="Python Software Foundation License Version 2",
        license_url="https://docs.python.org/zh-cn/3.14/license.html",
        raw_sha256="a" * 64,
        media_type="text/html",
        language="zh-CN",
    )
    snapshot = DocumentSnapshot(
        snapshot_id=SNAPSHOT_ID,
        source_id=source.source_id,
        page_title="Page",
        html_canonical_url=source.source_url,
        raw_html_sha256=source.raw_sha256,
        cleaned_content_sha256="b" * 64,
        parser_schema_version="parser-v1",
        imported_at=datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc),
    )
    return ImportedDocument(
        source=source,
        snapshot=snapshot,
        blocks=blocks,
    )


def selected_fields(chunk) -> dict[str, object]:
    data = chunk.model_dump(mode="json")
    keys = {
        "chunk_order",
        "block_start",
        "block_start_offset",
        "block_end",
        "block_end_offset",
        "paragraph_start",
        "paragraph_end",
        "section_path",
        "section_anchor",
        "text",
        "embedding_text",
    }
    return {key: data[key] for key in keys}


@pytest.mark.parametrize(
    "name",
    [
        "basic_merge_and_overlap.json",
        "long_text_split.json",
        "long_code_split.json",
        "single_long_code_line.json",
    ],
)
def test_document_chunker_matches_fixed_expected_chunks(name: str) -> None:
    fixture = load_fixture(name)
    document = make_document(fixture)
    config = ChunkingConfig.model_validate(fixture["config"])

    chunks = DocumentChunker().chunk(document, config=config)

    assert [selected_fields(chunk) for chunk in chunks] == fixture[
        "expected"
    ]["chunks"]
    assert all(
        chunk.chunking_schema_version == CHUNKING_SCHEMA_VERSION
        for chunk in chunks
    )
    assert all(len(chunk.text) <= config.max_characters for chunk in chunks)
    assert all(chunk.chunk_id.version == 5 for chunk in chunks)


def test_chunk_config_hash_uses_fixed_canonical_json() -> None:
    fixture = load_fixture("basic_merge_and_overlap.json")
    config = ChunkingConfig.model_validate(fixture["config"])
    canonical_json = (
        '{"block_separator":"\\n\\n","include_section_path":true,'
        '"max_characters":30,"minimum_split_characters":15,'
        '"overlap_characters":12,"schema_version":"1"}'
    )

    assert make_chunk_config_sha256(config) == sha256(
        canonical_json.encode("utf-8")
    ).hexdigest()


def test_chunk_identity_is_repeatable_and_config_sensitive() -> None:
    fixture = load_fixture("deterministic_identity.json")
    document = make_document(fixture)
    config = ChunkingConfig.model_validate(fixture["config"])
    changed_config = config.model_copy(
        update={
            "max_characters": fixture["expected"]["changed_config"][
                "max_characters"
            ],
        }
    )

    first = DocumentChunker().chunk(document, config=config)
    repeated = DocumentChunker().chunk(document, config=config)
    changed = DocumentChunker().chunk(document, config=changed_config)

    assert first == repeated
    assert [
        (
            chunk.block_start,
            chunk.block_start_offset,
            chunk.block_end,
            chunk.block_end_offset,
        )
        for chunk in first
    ] == [
        (
            chunk.block_start,
            chunk.block_start_offset,
            chunk.block_end,
            chunk.block_end_offset,
        )
        for chunk in changed
    ]
    assert first[0].chunk_config_sha256 != changed[0].chunk_config_sha256
    assert [chunk.chunk_id for chunk in first] != [
        chunk.chunk_id for chunk in changed
    ]


def test_document_chunk_content_hash_matches_citation_text() -> None:
    fixture = load_fixture("basic_merge_and_overlap.json")
    chunks = DocumentChunker().chunk(
        make_document(fixture),
        config=ChunkingConfig.model_validate(fixture["config"]),
    )

    assert all(
        chunk.content_sha256
        == sha256(chunk.text.encode("utf-8")).hexdigest()
        for chunk in chunks
    )


def test_document_chunker_rejects_nonconsecutive_block_order() -> None:
    fixture = load_fixture("invalid_block_sequence.json")
    document = make_document(fixture)
    config = ChunkingConfig.model_validate(fixture["config"])

    with pytest.raises(ChunkingError) as error:
        DocumentChunker().chunk(document, config=config)

    assert error.value.code == fixture["expected"]["error_code"]
    assert fixture["expected"]["reason_contains"] in error.value.reason
