"""Build one verified inactive Hybrid candidate on loopback Qdrant Server."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ["HF_HUB_OFFLINE"] = "1"

from cited_rag.chunking import BASELINE_CHUNKING_CONFIG, DocumentChunker  # noqa: E402
from cited_rag.hybrid_index import QdrantHybridCandidateBuilder  # noqa: E402
from cited_rag.indexing import load_active_index  # noqa: E402
from cited_rag.ingestion import CorpusIngestor, load_source_manifest  # noqa: E402
from cited_rag.qdrant_connection import (  # noqa: E402
    QdrantAdminSettings,
    make_admin_client_factory,
)

SOURCE_ROOT = PROJECT_ROOT / "data" / "sources"
INDEX_ROOT = PROJECT_ROOT / "data" / "server-indexes"
REPORT = PROJECT_ROOT / "data" / "hybrid-index-build-report.json"
ADMIN_ENV = PROJECT_ROOT / ".env.qdrant-admin"
DISK_LIMIT_BYTES = 1_073_741_824
QDRANT_CONTAINER = "cited-rag-qdrant-qdrant-1"


def main() -> int:
    if REPORT.exists():
        raise FileExistsError("hybrid build report already exists")
    pointer_path = INDEX_ROOT / "active-index.json"
    pointer_before = pointer_path.read_bytes()
    pointer_sha256_before = sha256(pointer_before).hexdigest()
    _, source_manifest = load_active_index(index_root=INDEX_ROOT)
    if source_manifest.specification.schema_version != "1":
        raise RuntimeError("hybrid build requires the fixed dense source index")

    free_before = shutil.disk_usage(PROJECT_ROOT.anchor).free
    started_at = datetime.now(timezone.utc)
    started = perf_counter()
    settings = QdrantAdminSettings(_env_file=ADMIN_ENV)
    client_factory = make_admin_client_factory(settings)
    manifest = load_source_manifest(
        allowed_root=SOURCE_ROOT,
        relative_path="manifest.json",
    )
    corpus = CorpusIngestor().ingest(manifest, allowed_root=SOURCE_ROOT)
    chunks = tuple(
        chunk
        for document in corpus.documents
        for chunk in DocumentChunker().chunk(document, config=BASELINE_CHUNKING_CONFIG)
    )
    result = QdrantHybridCandidateBuilder(
        clock=lambda: datetime.now(timezone.utc),
        build_id_factory=uuid4,
        qdrant_client_version=version("qdrant-client"),
        client_factory=client_factory,
    ).build(chunks=chunks, index_root=INDEX_ROOT)

    pointer_after = pointer_path.read_bytes()
    if pointer_after != pointer_before:
        raise RuntimeError("hybrid candidate build changed the active pointer")
    free_after = shutil.disk_usage(PROJECT_ROOT.anchor).free
    disk_delta = max(0, free_before - free_after)
    if disk_delta > DISK_LIMIT_BYTES:
        _delete_unactivated_candidate(
            client_factory=client_factory,
            collection_name=result.manifest.collection_name,
        )
        manifest_path = INDEX_ROOT / "manifests" / f"{result.manifest.build_id}.json"
        manifest_path.unlink(missing_ok=True)
        raise RuntimeError("V2-C2 exceeded the approved 1 GiB H-drive limit")

    collection_storage_bytes = _collection_storage_bytes(result.manifest.collection_name)
    completed_at = datetime.now(timezone.utc)
    report = {
        "schema_version": "1",
        "slice": "V2-C2-hybrid-candidate-build",
        "status": "ready-inactive",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": round(perf_counter() - started, 3),
        "source_manifest": source_manifest.model_dump(mode="json", exclude_none=True),
        "candidate_manifest": result.manifest.model_dump(mode="json", exclude_none=True),
        "validation": asdict(result.validation),
        "copied_dense_count": result.copied_dense_count,
        "sparse_vector_count": result.sparse_vector_count,
        "vocabulary_relative_path": result.vocabulary_path.relative_to(INDEX_ROOT).as_posix(),
        "active_pointer_sha256_before": pointer_sha256_before,
        "active_pointer_sha256_after": sha256(pointer_after).hexdigest(),
        "active_pointer_changed": False,
        "collection_storage_bytes": collection_storage_bytes,
        "h_drive_free_bytes_before": free_before,
        "h_drive_free_bytes_after": free_after,
        "h_drive_incremental_bytes": disk_delta,
        "h_drive_limit_bytes": DISK_LIMIT_BYTES,
        "external_api_calls": 0,
        "model_downloads": 0,
        "python_packages_installed": 0,
    }
    with REPORT.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    print(json.dumps({
        "status": report["status"],
        "candidate_collection": result.manifest.collection_name,
        "candidate_index_id": str(result.manifest.index_id),
        "candidate_build_id": str(result.manifest.build_id),
        "point_count": result.validation.point_count,
        "sparse_nonzero_count": result.validation.sparse_nonzero_count,
        "active_pointer_changed": False,
        "h_drive_incremental_bytes": disk_delta,
        "report": str(REPORT),
    }, ensure_ascii=False, indent=2))
    return 0


def _collection_storage_bytes(collection_name: str) -> int:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            QDRANT_CONTAINER,
            "du",
            "-sb",
            f"/qdrant/storage/collections/{collection_name}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return int(completed.stdout.split()[0])


def _delete_unactivated_candidate(*, client_factory, collection_name: str) -> None:
    _, active_manifest = load_active_index(index_root=INDEX_ROOT)
    if collection_name == active_manifest.collection_name:
        raise RuntimeError("refusing to delete the active collection")
    client = client_factory(INDEX_ROOT / "qdrant")
    try:
        client.delete_collection(collection_name)
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
