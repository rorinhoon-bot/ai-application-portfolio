from __future__ import annotations

import json
from pathlib import Path

import pytest

from cited_rag.models import ChunkingConfig

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "chunking"
EXPECTED_FIXTURES = {
    "basic_merge_and_overlap.json",
    "deterministic_identity.json",
    "invalid_block_sequence.json",
    "long_code_split.json",
    "long_text_split.json",
    "single_long_code_line.json",
}


def load_fixture(name: str) -> dict[str, object]:
    return json.loads(
        (FIXTURE_ROOT / name).read_text(encoding="utf-8")
    )


def test_chunking_fixture_set_is_fixed() -> None:
    actual = {path.name for path in FIXTURE_ROOT.glob("*.json")}

    assert actual == EXPECTED_FIXTURES


@pytest.mark.parametrize("name", sorted(EXPECTED_FIXTURES))
def test_chunking_fixture_metadata_and_config_are_valid(name: str) -> None:
    fixture = load_fixture(name)

    assert fixture["fixture_marker"] == "synthetic chunking fixture"
    assert fixture["schema_version"] == "1"
    ChunkingConfig.model_validate(fixture["config"])
    assert fixture["blocks"]
    assert fixture["expected"]


@pytest.mark.parametrize(
    "name",
    sorted(
        EXPECTED_FIXTURES
        - {"deterministic_identity.json", "invalid_block_sequence.json"}
    ),
)
def test_expected_chunks_are_exact_reconstructable_ranges(name: str) -> None:
    fixture = load_fixture(name)
    config = ChunkingConfig.model_validate(fixture["config"])
    blocks = {
        block["block_order"]: block
        for block in fixture["blocks"]
    }
    chunks = fixture["expected"]["chunks"]

    assert [chunk["chunk_order"] for chunk in chunks] == list(
        range(1, len(chunks) + 1)
    )
    for chunk in chunks:
        start = chunk["block_start"]
        end = chunk["block_end"]
        assert start <= end
        assert start in blocks
        assert end in blocks

        included = [blocks[order] for order in range(start, end + 1)]
        assert all(
            block["section_anchor"] == chunk["section_anchor"]
            and block["section_path"] == chunk["section_path"]
            for block in included
        )

        first_text = included[0]["clean_text"]
        last_text = included[-1]["clean_text"]
        start_offset = chunk["block_start_offset"]
        end_offset = chunk["block_end_offset"]
        assert 0 <= start_offset < len(first_text)
        assert 1 <= end_offset <= len(last_text)
        if start == end:
            reconstructed = first_text[start_offset:end_offset]
        else:
            pieces = [first_text[start_offset:]]
            pieces.extend(
                block["clean_text"] for block in included[1:-1]
            )
            pieces.append(last_text[:end_offset])
            reconstructed = config.block_separator.join(pieces)

        assert reconstructed == chunk["text"]
        assert len(chunk["text"]) <= config.max_characters
        expected_prefix = " > ".join(chunk["section_path"])
        assert chunk["embedding_text"] == (
            f"{expected_prefix}\n\n{chunk['text']}"
        )

        paragraph_orders = [
            block["paragraph_order"]
            for block in included
            if block["paragraph_order"] is not None
        ]
        if paragraph_orders:
            assert chunk["paragraph_start"] == min(paragraph_orders)
            assert chunk["paragraph_end"] == max(paragraph_orders)
        else:
            assert chunk["paragraph_start"] is None
            assert chunk["paragraph_end"] is None


def test_basic_fixture_fixes_overlap_and_section_boundary() -> None:
    fixture = load_fixture("basic_merge_and_overlap.json")
    chunks = fixture["expected"]["chunks"]

    assert chunks[0]["block_end"] == 2
    assert chunks[1]["block_start"] == 2
    assert chunks[1]["text"].startswith("gamma delta.")
    assert chunks[2]["section_anchor"] == "section-b"
    assert "theta kappa." not in chunks[2]["text"]


def test_long_block_fixtures_cover_every_character_once() -> None:
    for name in (
        "long_code_split.json",
        "long_text_split.json",
        "single_long_code_line.json",
    ):
        fixture = load_fixture(name)
        original = fixture["blocks"][0]["clean_text"]
        chunks = fixture["expected"]["chunks"]

        assert "".join(chunk["text"] for chunk in chunks) == original
        assert chunks[0]["block_start_offset"] == 0
        assert chunks[-1]["block_end_offset"] == len(original)
        assert all(
            left["block_end_offset"] == right["block_start_offset"]
            for left, right in zip(chunks[:-1], chunks[1:], strict=True)
        )


def test_deterministic_fixture_requires_config_sensitive_identity() -> None:
    fixture = load_fixture("deterministic_identity.json")
    expected = fixture["expected"]

    assert expected["repeat_is_identical"] is True
    assert expected["changed_config"]["same_chunk_boundaries"] is True
    assert expected["changed_config"]["chunk_config_sha256_changes"] is True
    assert expected["changed_config"]["all_chunk_ids_change"] is True


def test_invalid_sequence_fixture_fixes_public_error() -> None:
    fixture = load_fixture("invalid_block_sequence.json")

    assert [block["block_order"] for block in fixture["blocks"]] == [1, 3]
    assert fixture["expected"] == {
        "error_code": "CHUNKING_ERROR",
        "reason_contains": "block_order must be consecutive",
    }
