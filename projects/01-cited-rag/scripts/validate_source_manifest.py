"""Run offline import validation against a local source manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.ingestion import (  # noqa: E402
    CorpusIngestor,
    SingleDocumentIngestor,
    load_source_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    manifest = load_source_manifest(
        allowed_root=args.source_root,
        relative_path=args.manifest,
    )
    document_ingestor = SingleDocumentIngestor()
    failures: list[dict[str, str]] = []
    for source in manifest.sources:
        try:
            document_ingestor.ingest(
                source,
                allowed_root=args.source_root,
            )
        except Exception as exc:  # validation report must list every source
            failures.append(
                {
                    "source_id": source.source_id,
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                }
            )

    if failures:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "failure_count": len(failures),
                    "failures": failures,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    corpus_ingestor = CorpusIngestor(
        document_ingestor=document_ingestor,
    )
    corpus = corpus_ingestor.ingest(
        manifest,
        allowed_root=args.source_root,
    )
    repeated = corpus_ingestor.ingest(
        manifest,
        allowed_root=args.source_root,
        active_manifest=manifest,
    )
    print(
        json.dumps(
            {
                "status": corpus.status,
                "repeat_status": repeated.status,
                "document_count": len(corpus.documents),
                "block_count": sum(
                    len(document.blocks) for document in corpus.documents
                ),
                "manifest_sha256": corpus.manifest_sha256,
                "corpus_id": str(corpus.corpus_id),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
