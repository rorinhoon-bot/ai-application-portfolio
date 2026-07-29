"""Describe real ContentBlock sizes before fixing chunk rules."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.chunking import (  # noqa: E402
    BASELINE_CHUNKING_CONFIG,
    DocumentChunker,
    split_block,
)
from cited_rag.errors import ChunkingError  # noqa: E402
from cited_rag.ingestion import CorpusIngestor, load_source_manifest  # noqa: E402


def _nearest_rank(values: list[int], percentile: float) -> int:
    index = max(0, min(len(values) - 1, int(len(values) * percentile) - 1))
    return values[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    manifest = load_source_manifest(
        allowed_root=args.source_root,
        relative_path=args.manifest,
    )
    corpus = CorpusIngestor().ingest(
        manifest,
        allowed_root=args.source_root,
    )

    block_rows: list[dict[str, object]] = []
    section_lengths: Counter[tuple[str, str]] = Counter()
    baseline_config = BASELINE_CHUNKING_CONFIG
    segment_lengths: list[int] = []
    split_block_types: Counter[str] = Counter()
    chunk_lengths: list[int] = []
    chunk_ids: set[str] = set()
    overlap_chunk_count = 0
    per_document_chunks: dict[str, int] = {}
    chunker = DocumentChunker()
    for document in corpus.documents:
        for block in document.blocks:
            length = len(block.clean_text)
            block_rows.append(
                {
                    "source_id": document.source.source_id,
                    "block_order": block.block_order,
                    "block_type": block.block_type,
                    "section_anchor": block.section_anchor,
                    "length": length,
                    "line_count": block.clean_text.count("\n") + 1,
                    "sentence_boundary_count": sum(
                        block.clean_text.count(mark)
                        for mark in "。！？.!?；;"
                    ),
                    "whitespace_count": sum(
                        character.isspace()
                        for character in block.clean_text
                    ),
                }
            )
            section_key = (
                document.source.source_id,
                block.section_anchor,
            )
            if section_lengths[section_key]:
                section_lengths[section_key] += 2
            section_lengths[section_key] += length
            try:
                segments = split_block(block, config=baseline_config)
            except ChunkingError as error:
                raise ChunkingError(
                    f"{document.source.source_id} block "
                    f"{block.block_order}: {error.reason}"
                ) from error
            segment_lengths.extend(len(segment.text) for segment in segments)
            if len(segments) > 1:
                split_block_types[str(block.block_type)] += 1
        chunks = chunker.chunk(document, config=baseline_config)
        per_document_chunks[document.source.source_id] = len(chunks)
        chunk_lengths.extend(len(chunk.text) for chunk in chunks)
        for previous, current in zip(chunks[:-1], chunks[1:], strict=True):
            previous_end = (
                previous.block_end,
                previous.block_end_offset,
            )
            current_start = (
                current.block_start,
                current.block_start_offset,
            )
            if current_start < previous_end:
                overlap_chunk_count += 1
        for chunk in chunks:
            chunk_id = str(chunk.chunk_id)
            if chunk_id in chunk_ids:
                raise ChunkingError(f"duplicate chunk_id: {chunk_id}")
            chunk_ids.add(chunk_id)

    lengths = sorted(row["length"] for row in block_rows)
    section_values = sorted(section_lengths.values())
    over_limit = sorted(
        (
            row
            for row in block_rows
            if row["length"] > baseline_config.max_characters
        ),
        key=lambda row: row["length"],
        reverse=True,
    )
    type_counts = Counter(str(row["block_type"]) for row in block_rows)
    over_limit_types = Counter(
        str(row["block_type"]) for row in over_limit
    )
    result = {
        "document_count": len(corpus.documents),
        "block_count": len(block_rows),
        "section_count": len(section_lengths),
        "total_clean_characters": sum(lengths),
        "block_length": {
            "median": _nearest_rank(lengths, 0.50),
            "p90": _nearest_rank(lengths, 0.90),
            "p95": _nearest_rank(lengths, 0.95),
            "p99": _nearest_rank(lengths, 0.99),
            "maximum": lengths[-1],
        },
        "section_length": {
            "median": _nearest_rank(section_values, 0.50),
            "p90": _nearest_rank(section_values, 0.90),
            "p95": _nearest_rank(section_values, 0.95),
            "p99": _nearest_rank(section_values, 0.99),
            "maximum": section_values[-1],
            "over_chunk_limit": sum(
                value > baseline_config.max_characters
                for value in section_values
            ),
        },
        "block_type_counts": dict(sorted(type_counts.items())),
        "blocks_over_chunk_limit": {
            "count": len(over_limit),
            "by_type": dict(sorted(over_limit_types.items())),
            "largest_20": over_limit[:20],
        },
        "baseline_segmentation": {
            "segment_count": len(segment_lengths),
            "split_block_count": sum(split_block_types.values()),
            "split_blocks_by_type": dict(sorted(split_block_types.items())),
            "maximum_segment_length": max(segment_lengths),
        },
        "baseline_chunking": {
            "chunk_count": len(chunk_lengths),
            "overlap_chunk_count": overlap_chunk_count,
            "length_median": _nearest_rank(sorted(chunk_lengths), 0.50),
            "length_p90": _nearest_rank(sorted(chunk_lengths), 0.90),
            "length_p95": _nearest_rank(sorted(chunk_lengths), 0.95),
            "length_p99": _nearest_rank(sorted(chunk_lengths), 0.99),
            "maximum_length": max(chunk_lengths),
            "per_document": dict(sorted(per_document_chunks.items())),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
