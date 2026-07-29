"""Offline verification for one pinned FastEmbed model snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath

from cited_rag.errors import EmbeddingError
from cited_rag.models import EmbeddingConfig

EXPECTED_REPOSITORY_ID = "Qdrant/bge-small-zh-v1.5"
EXPECTED_PUBLIC_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
EXPECTED_REVISION = "46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59"
EXPECTED_MODEL_ASSETS_SHA256 = (
    "dea3d1b18367c7734c34cdcdc01d4cc7"
    "8ccf8f591fceb7e74d6e272e8f8e4133"
)
EXPECTED_FILES = (
    "config.json",
    "model_optimized.onnx",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)


@dataclass(frozen=True, slots=True)
class VerifiedModelAssets:
    """Verified paths and identity for local-only model loading."""

    snapshot_path: Path
    config: EmbeddingConfig
    total_bytes: int


def load_verified_model_assets(
    *,
    project_root: Path,
    report_path: Path,
) -> VerifiedModelAssets:
    """Re-hash every approved asset and return a pinned runtime config."""

    root = project_root.resolve(strict=True)
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EmbeddingError("model asset report is invalid") from error
    if (
        report.get("schema_version") != "1"
        or report.get("provider") != "fastembed"
        or report.get("repository_id") != EXPECTED_REPOSITORY_ID
        or report.get("public_model_name") != EXPECTED_PUBLIC_MODEL_NAME
        or report.get("revision") != EXPECTED_REVISION
        or report.get("license") != "mit"
        or report.get("model_assets_sha256")
        != EXPECTED_MODEL_ASSETS_SHA256
    ):
        raise EmbeddingError("model asset identity does not match approval")

    cache_relative_path = _validate_relative_directory(
        report.get("cache_relative_path"),
        field_name="cache_relative_path",
    )
    snapshot_relative_path = _validate_relative_directory(
        report.get("snapshot_relative_path"),
        field_name="snapshot_relative_path",
    )
    try:
        model_root = root.joinpath(
            *PurePosixPath(cache_relative_path).parts
        ).resolve(strict=True)
        snapshot_path = root.joinpath(
            *PurePosixPath(snapshot_relative_path).parts
        ).resolve(strict=True)
        model_root.relative_to(root)
        snapshot_path.relative_to(model_root)
    except (OSError, ValueError) as error:
        raise EmbeddingError(
            "model asset path is unavailable or outside project root"
        ) from error
    if not model_root.is_dir() or not snapshot_path.is_dir():
        raise EmbeddingError("model asset path is not a directory")

    records = report.get("files")
    if not isinstance(records, list) or len(records) != len(EXPECTED_FILES):
        raise EmbeddingError("model asset file list is invalid")
    canonical_files: list[dict[str, object]] = []
    for expected_name, record in zip(EXPECTED_FILES, records, strict=True):
        if not isinstance(record, dict):
            raise EmbeddingError("model asset record is invalid")
        relative_path = record.get("relative_path")
        if relative_path != expected_name:
            raise EmbeddingError("model asset file order or name changed")
        path = (snapshot_path / expected_name).resolve(strict=True)
        try:
            path.relative_to(model_root)
        except ValueError as error:
            raise EmbeddingError(
                "model asset file escaped approved root"
            ) from error
        if not path.is_file():
            raise EmbeddingError("model asset is not a regular file")
        byte_count = path.stat().st_size
        actual_sha256 = _sha256_file(path)
        if (
            record.get("byte_count") != byte_count
            or record.get("sha256") != actual_sha256
        ):
            raise EmbeddingError(f"model asset changed: {expected_name}")
        canonical_files.append(
            {
                "relative_path": expected_name,
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
    assets_sha256 = sha256(canonical_json.encode("utf-8")).hexdigest()
    if assets_sha256 != EXPECTED_MODEL_ASSETS_SHA256:
        raise EmbeddingError("model asset manifest hash changed")
    total_bytes = sum(
        int(record["byte_count"]) for record in canonical_files
    )
    if report.get("total_bytes") != total_bytes:
        raise EmbeddingError("model asset total byte count changed")

    config = EmbeddingConfig(
        schema_version="1",
        provider="fastembed",
        model_name=EXPECTED_PUBLIC_MODEL_NAME,
        resolved_model_source=EXPECTED_REPOSITORY_ID,
        model_revision=EXPECTED_REVISION,
        model_assets_sha256=assets_sha256,
        model_license="mit",
        model_cache_relative_path="data/models/fastembed",
        dimension=512,
        max_input_tokens=512,
        batch_size=64,
        distance="cosine",
        normalize=True,
        query_instruction=None,
        passage_instruction=None,
    )
    return VerifiedModelAssets(
        snapshot_path=snapshot_path,
        config=config,
        total_bytes=total_bytes,
    )


def _validate_relative_directory(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\\" in value
        or ":" in value
    ):
        raise EmbeddingError(f"{field_name} is not a safe relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or path.as_posix() != value
    ):
        raise EmbeddingError(f"{field_name} is not a safe relative path")
    return value


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
