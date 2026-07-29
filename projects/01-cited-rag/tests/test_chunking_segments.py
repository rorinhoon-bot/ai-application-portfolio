from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from cited_rag.chunking import split_block
from cited_rag.models import (
    ChunkingConfig,
    ContentBlock,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "chunking"
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000001")


def load_fixture(name: str) -> dict[str, object]:
    return json.loads(
        (FIXTURE_ROOT / name).read_text(encoding="utf-8")
    )


def make_block(data: dict[str, object]) -> ContentBlock:
    clean_text = data["clean_text"]
    return ContentBlock.model_validate(
        {
            "block_id": UUID(
                f"00000000-0000-0000-0000-{data['block_order']:012d}"
            ),
            "snapshot_id": SNAPSHOT_ID,
            "block_order": data["block_order"],
            "paragraph_order": data["paragraph_order"],
            "block_type": data["block_type"],
            "raw_text": clean_text,
            "clean_text": clean_text,
            "section_path": data["section_path"],
            "section_anchor": data["section_anchor"],
            "block_anchor": None,
            "list_level": data.get("list_level"),
        }
    )


@pytest.mark.parametrize(
    "name",
    [
        "long_text_split.json",
        "long_code_split.json",
        "single_long_code_line.json",
    ],
)
def test_split_block_matches_fixed_ranges(name: str) -> None:
    fixture = load_fixture(name)
    config = ChunkingConfig.model_validate(fixture["config"])
    block = make_block(fixture["blocks"][0])

    segments = split_block(block, config=config)
    expected = fixture["expected"]["chunks"]

    assert [
        {
            "block_start_offset": segment.start_offset,
            "block_end_offset": segment.end_offset,
            "text": segment.text,
        }
        for segment in segments
    ] == [
        {
            "block_start_offset": chunk["block_start_offset"],
            "block_end_offset": chunk["block_end_offset"],
            "text": chunk["text"],
        }
        for chunk in expected
    ]
    assert all(segment.was_split for segment in segments)


def test_short_block_remains_one_unsplit_segment() -> None:
    fixture = load_fixture("basic_merge_and_overlap.json")
    config = ChunkingConfig.model_validate(fixture["config"])
    block = make_block(fixture["blocks"][0])

    segments = split_block(block, config=config)

    assert len(segments) == 1
    assert segments[0].start_offset == 0
    assert segments[0].end_offset == len(block.clean_text)
    assert segments[0].text == block.clean_text
    assert segments[0].was_split is False


def test_ascii_period_requires_following_whitespace() -> None:
    block = make_block(
        {
            "block_order": 1,
            "paragraph_order": 1,
            "block_type": "paragraph",
            "clean_text": "module.name keeps going. next sentence.",
            "section_path": ["Page", "Text"],
            "section_anchor": "text",
        }
    )
    config = ChunkingConfig(
        schema_version="1",
        max_characters=25,
        overlap_characters=0,
        block_separator="\n\n",
        minimum_split_characters=10,
        include_section_path=True,
    )

    segments = split_block(block, config=config)

    assert segments[0].text == "module.name keeps going. "
    assert "".join(segment.text for segment in segments) == block.clean_text


def test_text_without_safe_boundary_uses_hard_limit() -> None:
    block = make_block(
        {
            "block_order": 1,
            "paragraph_order": 1,
            "block_type": "paragraph",
            "clean_text": "abcdefghijklmnop",
            "section_path": ["Page", "Text"],
            "section_anchor": "text",
        }
    )
    config = ChunkingConfig(
        schema_version="1",
        max_characters=8,
        overlap_characters=0,
        block_separator="\n\n",
        minimum_split_characters=4,
        include_section_path=True,
    )

    segments = split_block(block, config=config)

    assert [segment.text for segment in segments] == [
        "abcdefgh",
        "ijklmnop",
    ]


def test_code_newline_just_outside_limit_does_not_create_oversized_segment() -> None:
    block = make_block(
        {
            "block_order": 1,
            "paragraph_order": None,
            "block_type": "code",
            "clean_text": "12345678\nnext\n",
            "section_path": ["Page", "Code"],
            "section_anchor": "code",
        }
    )
    config = ChunkingConfig(
        schema_version="1",
        max_characters=8,
        overlap_characters=0,
        block_separator="\n\n",
        minimum_split_characters=4,
        include_section_path=True,
    )

    segments = split_block(block, config=config)

    assert [segment.text for segment in segments] == [
        "12345678",
        "\nnext\n",
    ]
    assert all(len(segment.text) <= 8 for segment in segments)
