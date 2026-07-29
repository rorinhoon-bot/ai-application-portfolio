"""Audit every real Chunk with the pinned tokenizer and no truncation."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from fastembed.common.preprocessor_utils import load_tokenizer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.chunking import (  # noqa: E402
    BASELINE_CHUNKING_CONFIG,
    DocumentChunker,
    make_chunk_config_sha256,
)
from cited_rag.ingestion import CorpusIngestor, load_source_manifest  # noqa: E402

EXPECTED_MODEL_ID = "Qdrant/bge-small-zh-v1.5"
EXPECTED_REVISION = "46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59"
MAX_INPUT_TOKENS = 512


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _nearest_rank(values: list[int], percentile: float) -> int:
    index = max(0, min(len(values) - 1, int(len(values) * percentile) - 1))
    return values[index]


def _load_verified_model(report_path: Path) -> tuple[Path, dict[str, object]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if (
        report.get("repository_id") != EXPECTED_MODEL_ID
        or report.get("revision") != EXPECTED_REVISION
        or report.get("license") != "mit"
    ):
        raise ValueError("model asset report does not match approved identity")
    snapshot_path = (
        PROJECT_ROOT / report["snapshot_relative_path"]
    ).resolve(strict=True)
    model_root = (
        PROJECT_ROOT / report["cache_relative_path"]
    ).resolve(strict=True)
    if not snapshot_path.is_relative_to(model_root):
        raise ValueError("model snapshot escaped approved cache root")

    files = report.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("model asset report has no files")
    canonical_files: list[dict[str, object]] = []
    for record in files:
        relative_path = record["relative_path"]
        if (
            not isinstance(relative_path, str)
            or "/" in relative_path
            or "\\" in relative_path
            or relative_path in {"", ".", ".."}
        ):
            raise ValueError("model asset report contains an unsafe path")
        path = (snapshot_path / relative_path).resolve(strict=True)
        if not path.is_relative_to(model_root) or not path.is_file():
            raise ValueError(f"model asset is unavailable: {relative_path}")
        byte_count = path.stat().st_size
        actual_sha256 = _sha256_file(path)
        if (
            byte_count != record["byte_count"]
            or actual_sha256 != record["sha256"]
        ):
            raise ValueError(f"model asset changed: {relative_path}")
        canonical_files.append(
            {
                "relative_path": relative_path,
                "byte_count": byte_count,
                "sha256": actual_sha256,
            }
        )
    canonical_json = json.dumps(
        canonical_files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    actual_assets_sha256 = sha256(canonical_json.encode("utf-8")).hexdigest()
    if actual_assets_sha256 != report["model_assets_sha256"]:
        raise ValueError("model asset manifest hash changed")
    return snapshot_path, report


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
    configured_truncation = tokenizer.truncation
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
    config = BASELINE_CHUNKING_CONFIG
    chunker = DocumentChunker()
    chunks = tuple(
        chunk
        for document in corpus.documents
        for chunk in chunker.chunk(document, config=config)
    )

    token_rows: list[dict[str, object]] = []
    per_source_over_limit: Counter[str] = Counter()
    for chunk in chunks:
        token_count = len(
            tokenizer.encode(
                chunk.embedding_text,
                add_special_tokens=True,
            ).ids
        )
        row = {
            "chunk_id": str(chunk.chunk_id),
            "source_id": chunk.source_id,
            "document_key": chunk.document_key,
            "python_version": chunk.python_version,
            "chunk_order": chunk.chunk_order,
            "character_count": len(chunk.embedding_text),
            "token_count": token_count,
        }
        token_rows.append(row)
        if token_count > MAX_INPUT_TOKENS:
            per_source_over_limit[chunk.source_id] += 1

    token_counts = sorted(row["token_count"] for row in token_rows)
    over_limit = sorted(
        (
            row
            for row in token_rows
            if row["token_count"] > MAX_INPUT_TOKENS
        ),
        key=lambda row: (-row["token_count"], row["chunk_id"]),
    )
    report = {
        "schema_version": "1",
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not over_limit else "failed",
        "model": {
            "repository_id": model_report["repository_id"],
            "revision": model_report["revision"],
            "model_assets_sha256": model_report["model_assets_sha256"],
            "configured_truncation": configured_truncation,
            "audit_truncation": None,
            "audit_padding": None,
            "max_input_tokens": MAX_INPUT_TOKENS,
        },
        "corpus": {
            "corpus_id": str(corpus.corpus_id),
            "manifest_sha256": corpus.manifest_sha256,
            "document_count": len(corpus.documents),
        },
        "chunking": {
            "schema_version": "chunker-v1",
            "chunk_config_sha256": make_chunk_config_sha256(config),
            "chunk_count": len(chunks),
        },
        "token_count": {
            "median": _nearest_rank(token_counts, 0.50),
            "p90": _nearest_rank(token_counts, 0.90),
            "p95": _nearest_rank(token_counts, 0.95),
            "p99": _nearest_rank(token_counts, 0.99),
            "maximum": token_counts[-1],
            "over_limit_count": len(over_limit),
            "per_source_over_limit": dict(
                sorted(per_source_over_limit.items())
            ),
        },
        "over_limit": over_limit,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "model_revision": report["model"]["revision"],
                "model_assets_sha256": report["model"][
                    "model_assets_sha256"
                ],
                "corpus_id": report["corpus"]["corpus_id"],
                "chunk_count": report["chunking"]["chunk_count"],
                "token_count": report["token_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not over_limit else 2


if __name__ == "__main__":
    raise SystemExit(main())
