"""Build and atomically activate the approved local BGE/Qdrant index."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Defense in depth: the approved build must never fetch missing model files.
os.environ["HF_HUB_OFFLINE"] = "1"

from cited_rag.adapters.fastembed_local import (  # noqa: E402
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.chunking import (  # noqa: E402
    BASELINE_CHUNKING_CONFIG,
    DocumentChunker,
)
from cited_rag.embedding import EmbeddingService  # noqa: E402
from cited_rag.indexing import (  # noqa: E402
    make_index_id,
    make_index_specification,
)
from cited_rag.ingestion import (  # noqa: E402
    CorpusIngestor,
    load_source_manifest,
)
from cited_rag.model_assets import load_verified_model_assets  # noqa: E402
from cited_rag.qdrant_index import (  # noqa: E402
    QdrantIndexBuilder,
    verify_active_index,
)

SOURCE_ROOT = PROJECT_ROOT / "data" / "sources"
SOURCE_MANIFEST = "manifest.json"
MODEL_REPORT = PROJECT_ROOT / "data" / "model-assets.json"
INDEX_ROOT = PROJECT_ROOT / "data" / "indexes"
BUILD_REPORT = PROJECT_ROOT / "data" / "index-build-report.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--restore",
        action="store_true",
        help="rebuild local index while preserving tracked build evidence",
    )
    arguments = parser.parse_args()
    started_at = datetime.now(timezone.utc)
    started = perf_counter()

    assets = load_verified_model_assets(
        project_root=PROJECT_ROOT,
        report_path=MODEL_REPORT,
    )
    manifest = load_source_manifest(
        allowed_root=SOURCE_ROOT,
        relative_path=SOURCE_MANIFEST,
    )
    corpus = CorpusIngestor().ingest(
        manifest,
        allowed_root=SOURCE_ROOT,
    )
    chunks = tuple(
        chunk
        for document in corpus.documents
        for chunk in DocumentChunker().chunk(
            document,
            config=BASELINE_CHUNKING_CONFIG,
        )
    )
    specification = make_index_specification(
        corpus=corpus,
        chunks=chunks,
        embedding_config=assets.config,
    )
    existing = verify_active_index(
        chunks=chunks,
        specification=specification,
        index_root=INDEX_ROOT,
    )
    if existing is not None:
        print(
            json.dumps(
                {
                    "status": existing.status,
                    "index_id": str(existing.manifest.index_id),
                    "build_id": str(existing.manifest.build_id),
                    "collection_name": existing.manifest.collection_name,
                    "chunk_count": len(chunks),
                    "embedded_count": existing.embedded_count,
                    "validation": asdict(existing.validation),
                    "report_preserved": str(BUILD_REPORT),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    reference_report = None
    if BUILD_REPORT.exists() and not arguments.restore:
        raise FileExistsError(
            "build report exists but no matching active index was found"
        )
    if arguments.restore:
        if not BUILD_REPORT.exists():
            raise FileNotFoundError("tracked index build report is missing")
        reference_report = json.loads(
            BUILD_REPORT.read_text(encoding="utf-8")
        )
        if (
            reference_report["index_manifest"]["index_id"]
            != str(make_index_id(specification))
            or reference_report["index_manifest"]["specification"]
            != specification.model_dump(mode="json")
        ):
            raise ValueError(
                "current corpus and model do not match tracked index report"
            )

    provider = FastEmbedLocalProvider(
        model_dir=assets.snapshot_path,
        config=assets.config,
    )
    token_counter = FastEmbedNoTruncationTokenCounter(
        model_dir=assets.snapshot_path
    )
    embedding_service = EmbeddingService.from_config(
        provider=provider,
        token_counter=token_counter,
        config=assets.config,
    )
    result = QdrantIndexBuilder(
        embedding_service=embedding_service,
        clock=lambda: datetime.now(timezone.utc),
        build_id_factory=uuid4,
        qdrant_client_version=version("qdrant-client"),
    ).build(
        chunks=chunks,
        specification=specification,
        index_root=INDEX_ROOT,
    )
    completed_at = datetime.now(timezone.utc)
    report = {
        "schema_version": "1",
        "status": result.status,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round(perf_counter() - started, 3),
        "network_mode": "offline",
        "model": assets.config.model_dump(mode="json"),
        "corpus": {
            "corpus_id": str(corpus.corpus_id),
            "source_manifest_sha256": corpus.manifest_sha256,
            "document_count": len(corpus.documents),
        },
        "chunking": {
            **BASELINE_CHUNKING_CONFIG.model_dump(mode="json"),
            "chunk_count": len(chunks),
            "chunk_config_sha256": specification.chunk_config_sha256,
        },
        "index_manifest": result.manifest.model_dump(mode="json"),
        "validation": asdict(result.validation),
        "embedded_count": result.embedded_count,
    }
    if reference_report is None:
        BUILD_REPORT.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "status": result.status,
                "duration_seconds": report["duration_seconds"],
                "index_id": str(result.manifest.index_id),
                "build_id": str(result.manifest.build_id),
                "collection_name": result.manifest.collection_name,
                "chunk_count": len(chunks),
                "embedded_count": result.embedded_count,
                "validation": report["validation"],
                (
                    "report_preserved"
                    if reference_report is not None
                    else "report"
                ): str(BUILD_REPORT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
