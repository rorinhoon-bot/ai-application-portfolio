"""Create, download, restore, and validate one Qdrant collection snapshot."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sys
from urllib.parse import quote
from uuid import uuid4

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.chunking import (  # noqa: E402
    BASELINE_CHUNKING_CONFIG,
    DocumentChunker,
)
from cited_rag.indexing import load_active_index  # noqa: E402
from cited_rag.ingestion import (  # noqa: E402
    CorpusIngestor,
    load_source_manifest,
)
from cited_rag.qdrant_connection import (  # noqa: E402
    QdrantAdminSettings,
    make_admin_client_factory,
)
from cited_rag.qdrant_index import _validate_collection  # noqa: E402

INDEX_ROOT = PROJECT_ROOT / "data" / "server-indexes"
SOURCE_ROOT = PROJECT_ROOT / "data" / "sources"
ADMIN_ENV = PROJECT_ROOT / ".env.qdrant-admin"
BACKUP_ROOT = PROJECT_ROOT / "data" / "backups" / "qdrant"
REPORT_PATH = PROJECT_ROOT / "data" / "qdrant-recovery-report.json"
MAXIMUM_SNAPSHOT_BYTES = 1024 * 1024 * 1024


def main(*, preserve_existing_report: bool = False) -> int:
    report_already_exists = _validate_report_target(REPORT_PATH)
    if report_already_exists and not preserve_existing_report:
        raise FileExistsError("Qdrant recovery report already exists")
    pointer, manifest = load_active_index(index_root=INDEX_ROOT)
    recovery_name = f"cited-rag-recovery-{uuid4().hex}"
    if recovery_name == manifest.collection_name:
        raise RuntimeError("recovery collection must differ from active")

    chunks = _load_chunks()
    if len(chunks) != manifest.point_count:
        raise RuntimeError("restored corpus no longer matches index manifest")
    settings = QdrantAdminSettings(_env_file=ADMIN_ENV)
    client = make_admin_client_factory(settings)(INDEX_ROOT / "unused")
    backup_path: Path | None = None
    manifest_backup_path: Path | None = None
    recovery_deleted = False
    try:
        active_before = _validate_collection(
            client=client,
            manifest=manifest,
            chunks=chunks,
        )
        snapshot = client.create_snapshot(
            collection_name=manifest.collection_name,
            wait=True,
        )
        if snapshot is None or not snapshot.name:
            raise RuntimeError("Qdrant did not return a snapshot description")
        snapshot_name = _safe_snapshot_name(snapshot.name)
        BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
        backup_root = BACKUP_ROOT.resolve(strict=True)
        if not backup_root.is_relative_to(PROJECT_ROOT.resolve(strict=True)):
            raise RuntimeError("snapshot backup root escaped project root")
        backup_path = backup_root / snapshot_name
        if backup_path.exists() or backup_path.is_symlink():
            raise FileExistsError("snapshot backup target already exists")

        downloaded_bytes, downloaded_sha256 = _download_snapshot(
            base_url=str(settings.qdrant_url).removesuffix("/"),
            api_key=settings.qdrant_admin_api_key.get_secret_value(),
            collection_name=manifest.collection_name,
            snapshot_name=snapshot_name,
            destination=backup_path,
            timeout_seconds=settings.qdrant_timeout_seconds,
        )
        if snapshot.size is not None and downloaded_bytes != snapshot.size:
            raise RuntimeError("downloaded snapshot size changed")
        if snapshot.checksum and downloaded_sha256 != snapshot.checksum:
            raise RuntimeError("downloaded snapshot checksum changed")

        manifest_source = (
            INDEX_ROOT / pointer.manifest_relative_path
        ).resolve(strict=True)
        if not manifest_source.is_relative_to(INDEX_ROOT.resolve(strict=True)):
            raise RuntimeError("active manifest escaped Server index root")
        manifest_backup_path = backup_root / f"{snapshot_name}.manifest.json"
        if manifest_backup_path.exists() or manifest_backup_path.is_symlink():
            raise FileExistsError("manifest backup target already exists")
        with manifest_backup_path.open("xb") as file:
            file.write(manifest_source.read_bytes())
            file.flush()
            os.fsync(file.fileno())
        manifest_backup_sha256 = _sha256_file(manifest_backup_path)

        with backup_path.open("rb") as snapshot_file:
            recovery_response = (
                client.http.snapshots_api.recover_from_uploaded_snapshot(
                    collection_name=recovery_name,
                    wait=True,
                    checksum=downloaded_sha256,
                    snapshot=snapshot_file,
                )
            )
        if recovery_response.result is not True:
            raise RuntimeError("uploaded snapshot recovery did not complete")

        recovery_manifest = manifest.model_copy(
            update={"collection_name": recovery_name}
        )
        recovered = _validate_collection(
            client=client,
            manifest=recovery_manifest,
            chunks=chunks,
        )
        if asdict(recovered) != asdict(active_before):
            raise RuntimeError("recovered collection differs from active")

        if not client.delete_collection(recovery_name):
            raise RuntimeError("temporary recovery collection was not deleted")
        recovery_deleted = True
        if client.collection_exists(recovery_name):
            raise RuntimeError("temporary recovery collection still exists")

        active_after = _validate_collection(
            client=client,
            manifest=manifest,
            chunks=chunks,
        )
        if asdict(active_after) != asdict(active_before):
            raise RuntimeError("active collection changed during recovery test")

        report = {
            "schema_version": "1",
            "status": "passed",
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "active_collection": manifest.collection_name,
            "active_index_id": str(manifest.index_id),
            "active_build_id": str(manifest.build_id),
            "snapshot": {
                "name": snapshot_name,
                "server_reported_bytes": snapshot.size,
                "downloaded_bytes": downloaded_bytes,
                "sha256": downloaded_sha256,
                "qdrant_checksum_matched": bool(snapshot.checksum),
                "host_backup_relative_path": str(
                    backup_path.relative_to(PROJECT_ROOT)
                ).replace("\\", "/"),
                "manifest_backup_relative_path": str(
                    manifest_backup_path.relative_to(PROJECT_ROOT)
                ).replace("\\", "/"),
                "manifest_backup_sha256": manifest_backup_sha256,
            },
            "recovery": {
                "temporary_collection": recovery_name,
                "upload_only": True,
                "validation": asdict(recovered),
                "temporary_collection_deleted": recovery_deleted,
            },
            "active_collection_validation_after_cleanup": asdict(active_after),
            "secrets_recorded": False,
        }
        if not report_already_exists:
            with REPORT_PATH.open("x", encoding="utf-8", newline="\n") as file:
                json.dump(report, file, ensure_ascii=False, indent=2)
                file.write("\n")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "snapshot_name": snapshot_name,
                    "snapshot_bytes": downloaded_bytes,
                    "snapshot_sha256": downloaded_sha256,
                    "recovered_point_count": recovered.point_count,
                    "temporary_collection_deleted": recovery_deleted,
                    "active_collection_unchanged": True,
                    (
                        "report_preserved"
                        if report_already_exists
                        else "report"
                    ): str(REPORT_PATH),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        try:
            if not recovery_deleted and client.collection_exists(recovery_name):
                if not client.delete_collection(recovery_name):
                    raise RuntimeError(
                        "failed to clean temporary recovery collection"
                    )
        finally:
            client.close()
    return 0


def _load_chunks():
    source_manifest = load_source_manifest(
        allowed_root=SOURCE_ROOT,
        relative_path="manifest.json",
    )
    corpus = CorpusIngestor().ingest(
        source_manifest,
        allowed_root=SOURCE_ROOT,
    )
    return tuple(
        chunk
        for document in corpus.documents
        for chunk in DocumentChunker().chunk(
            document,
            config=BASELINE_CHUNKING_CONFIG,
        )
    )


def _safe_snapshot_name(value: str) -> str:
    if (
        not value
        or Path(value).name != value
        or "/" in value
        or "\\" in value
    ):
        raise RuntimeError("Qdrant returned an unsafe snapshot name")
    return value


def _download_snapshot(
    *,
    base_url: str,
    api_key: str,
    collection_name: str,
    snapshot_name: str,
    destination: Path,
    timeout_seconds: int,
) -> tuple[int, str]:
    collection_path = quote(collection_name, safe="")
    snapshot_path = quote(snapshot_name, safe="")
    digest = sha256()
    byte_count = 0
    try:
        with (
            httpx.Client(
                base_url=base_url,
                headers={"api-key": api_key},
                timeout=httpx.Timeout(timeout_seconds),
                trust_env=False,
            ) as http_client,
            http_client.stream(
                "GET",
                f"/collections/{collection_path}/snapshots/{snapshot_path}",
            ) as response,
        ):
            if response.status_code != 200:
                raise RuntimeError(
                    f"snapshot download returned HTTP {response.status_code}"
                )
            with destination.open("xb") as file:
                for block in response.iter_bytes():
                    byte_count += len(block)
                    if byte_count > MAXIMUM_SNAPSHOT_BYTES:
                        raise RuntimeError("snapshot exceeded maximum backup size")
                    digest.update(block)
                    file.write(block)
                file.flush()
                os.fsync(file.fileno())
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return byte_count, digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_report_target(path: Path) -> bool:
    if path.is_symlink():
        raise RuntimeError("recovery report must not be a symbolic link")
    if path.exists() and not path.is_file():
        raise RuntimeError("recovery report must be a regular file")
    return path.exists()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate Qdrant snapshot download and upload recovery."
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="preserve an existing tracked historical recovery report",
    )
    arguments = parser.parse_args()
    raise SystemExit(
        main(preserve_existing_report=arguments.restore)
    )
