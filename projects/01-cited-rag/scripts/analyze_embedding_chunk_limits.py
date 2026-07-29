"""Compare character Chunk limits with the pinned no-truncation tokenizer."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastembed.common.preprocessor_utils import load_tokenizer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from audit_embedding_tokens import _load_verified_model  # noqa: E402
from cited_rag.chunking import (  # noqa: E402
    DocumentChunker,
    make_chunk_config_sha256,
)
from cited_rag.ingestion import CorpusIngestor, load_source_manifest  # noqa: E402
from cited_rag.models import ChunkingConfig  # noqa: E402

CANDIDATE_CONFIGS = (
    ("current", 800, 120, 400),
    ("near-limit", 600, 120, 400),
    ("first-zero-over-limit", 500, 120, 400),
    ("proportional-520", 520, 80, 260),
    ("proportional-500", 500, 80, 250),
    ("proportional-480", 480, 80, 240),
)
MAX_INPUT_TOKENS = 512


def _nearest_rank(values: list[int], percentile: float) -> int:
    index = max(0, min(len(values) - 1, int(len(values) * percentile) - 1))
    return values[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--model-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(f"refusing to overwrite {args.report}")

    snapshot_path, model_report = _load_verified_model(args.model_report)
    tokenizer, _ = load_tokenizer(snapshot_path)
    tokenizer.no_truncation()
    tokenizer.no_padding()
    manifest = load_source_manifest(
        allowed_root=args.source_root,
        relative_path=args.manifest,
    )
    corpus = CorpusIngestor().ingest(
        manifest,
        allowed_root=args.source_root,
    )
    chunker = DocumentChunker()

    candidates: list[dict[str, object]] = []
    for (
        name,
        max_characters,
        overlap_characters,
        minimum_split_characters,
    ) in CANDIDATE_CONFIGS:
        config = ChunkingConfig(
            schema_version="1",
            max_characters=max_characters,
            overlap_characters=overlap_characters,
            block_separator="\n\n",
            minimum_split_characters=minimum_split_characters,
            include_section_path=True,
        )
        chunks = []
        overlap_chunk_count = 0
        for document in corpus.documents:
            document_chunks = chunker.chunk(document, config=config)
            chunks.extend(document_chunks)
            for previous, current in zip(
                document_chunks[:-1],
                document_chunks[1:],
                strict=True,
            ):
                if (
                    current.block_start,
                    current.block_start_offset,
                ) < (
                    previous.block_end,
                    previous.block_end_offset,
                ):
                    overlap_chunk_count += 1
        token_counts = sorted(
            len(
                tokenizer.encode(
                    chunk.embedding_text,
                    add_special_tokens=True,
                ).ids
            )
            for chunk in chunks
        )
        candidates.append(
            {
                "name": name,
                "max_characters": max_characters,
                "overlap_characters": config.overlap_characters,
                "minimum_split_characters": (
                    config.minimum_split_characters
                ),
                "chunk_config_sha256": make_chunk_config_sha256(config),
                "chunk_count": len(chunks),
                "overlap_chunk_count": overlap_chunk_count,
                "token_median": _nearest_rank(token_counts, 0.50),
                "token_p90": _nearest_rank(token_counts, 0.90),
                "token_p95": _nearest_rank(token_counts, 0.95),
                "token_p99": _nearest_rank(token_counts, 0.99),
                "token_maximum": token_counts[-1],
                "over_limit_count": sum(
                    count > MAX_INPUT_TOKENS for count in token_counts
                ),
            }
        )

    report = {
        "schema_version": "1",
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "repository_id": model_report["repository_id"],
            "revision": model_report["revision"],
            "model_assets_sha256": model_report["model_assets_sha256"],
            "max_input_tokens": MAX_INPUT_TOKENS,
        },
        "corpus": {
            "corpus_id": str(corpus.corpus_id),
            "manifest_sha256": corpus.manifest_sha256,
        },
        "candidates": candidates,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(candidates, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
