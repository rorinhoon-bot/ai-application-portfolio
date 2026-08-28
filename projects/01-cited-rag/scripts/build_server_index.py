"""Build and atomically activate the approved loopback Qdrant index."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from uuid import uuid4
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Fixed local model assets only. Missing files must fail, never download.
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
from cited_rag.indexing import make_index_specification  # noqa: E402
from cited_rag.ingestion import (  # noqa: E402
    CorpusIngestor,
    load_source_manifest,
)
from cited_rag.model_assets import load_verified_model_assets  # noqa: E402
from cited_rag.qdrant_connection import (  # noqa: E402
    QdrantAdminSettings,
    make_admin_client_factory,
)
from cited_rag.qdrant_index import (  # noqa: E402
    QdrantIndexBuilder,
    verify_active_index,
)

SOURCE_ROOT = PROJECT_ROOT / "data" / "sources"
SOURCE_MANIFEST = "manifest.json"
MODEL_REPORT = PROJECT_ROOT / "data" / "model-assets.json"
INDEX_ROOT = PROJECT_ROOT / "data" / "server-indexes"
BUILD_REPORT = PROJECT_ROOT / "data" / "server-index-build-report.json"
ADMIN_ENV = PROJECT_ROOT / ".env.qdrant-admin"


def main(*, preserve_existing_report: bool = False) -> int:
    report_already_exists = _validate_report_target(BUILD_REPORT)
    started_at = datetime.now(timezone.utc)
    started = perf_counter()
    settings = QdrantAdminSettings(_env_file=ADMIN_ENV)
    client_factory = make_admin_client_factory(settings)

    info_client = client_factory(INDEX_ROOT / "unused")
    try:
        server_info = info_client.info()
    finally:
        info_client.close()

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
        client_factory=client_factory,
    )
    if existing is not None:
        print(
            json.dumps(
                {
                    "status": existing.status,
                    "server_version": server_info.version,
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
    if report_already_exists and not preserve_existing_report:
        raise FileExistsError(
            "server build report exists but active index does not match"
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
        client_factory=client_factory,
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
        "model_network_mode": "offline",
        "qdrant_transport": "loopback-http",
        "qdrant_server_version": server_info.version,
        "qdrant_client_version": version("qdrant-client"),
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
    if not report_already_exists:
        with BUILD_REPORT.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
    print(
        json.dumps(
            {
                "status": result.status,
                "duration_seconds": report["duration_seconds"],
                "server_version": server_info.version,
                "index_id": str(result.manifest.index_id),
                "build_id": str(result.manifest.build_id),
                "collection_name": result.manifest.collection_name,
                "chunk_count": len(chunks),
                "embedded_count": result.embedded_count,
                "validation": report["validation"],
                (
                    "report_preserved"
                    if report_already_exists
                    else "report"
                ): str(BUILD_REPORT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _validate_report_target(path: Path) -> bool:
    if path.is_symlink():
        raise RuntimeError("server build report must not be a symbolic link")
    if path.exists() and not path.is_file():
        raise RuntimeError("server build report must be a regular file")
    return path.exists()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build and activate the fixed Qdrant Server index."
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="preserve an existing tracked historical build report",
    )
    arguments = parser.parse_args()
    raise SystemExit(
        main(preserve_existing_report=arguments.restore)
    )
