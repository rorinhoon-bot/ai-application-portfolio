"""Fetch one approved, revision-pinned FastEmbed model snapshot."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "Qdrant/bge-small-zh-v1.5"
PUBLIC_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
REVISION = "46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59"
LICENSE = "mit"
OUTPUT_ROOT = PROJECT_ROOT / "data" / "models" / "fastembed"
REPORT_PATH = PROJECT_ROOT / "data" / "model-assets.json"
EXPECTED_FILES = {
    "config.json": 739,
    "model_optimized.onnx": 94_781_076,
    "special_tokens_map.json": 125,
    "tokenizer.json": 439_125,
    "tokenizer_config.json": 367,
}


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _assets_sha256(files: list[dict[str, object]]) -> str:
    canonical_json = json.dumps(
        files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()


def _card_license(card_data) -> str | None:
    if card_data is None:
        return None
    if hasattr(card_data, "get"):
        return card_data.get("license")
    return getattr(card_data, "license", None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--restore",
        action="store_true",
        help="restore pinned assets while preserving the tracked report",
    )
    arguments = parser.parse_args()
    existing_report = None
    if REPORT_PATH.exists() and not arguments.restore:
        raise FileExistsError(f"refusing to overwrite {REPORT_PATH.name}")
    if arguments.restore:
        if not REPORT_PATH.exists():
            raise FileNotFoundError("tracked model report is missing")
        existing_report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    api = HfApi()
    info = api.model_info(MODEL_ID, revision=REVISION, files_metadata=True)
    if info.id != MODEL_ID or info.sha != REVISION:
        raise ValueError("model repository or revision does not match approval")
    if _card_license(info.card_data) != LICENSE:
        raise ValueError("model license does not match approved MIT license")

    observed_files = {
        sibling.rfilename: sibling.size
        for sibling in info.siblings
        if sibling.rfilename in EXPECTED_FILES
    }
    if observed_files != EXPECTED_FILES:
        raise ValueError("approved model file list or sizes changed")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output_root = OUTPUT_ROOT.resolve(strict=True)
    snapshot_path = Path(
        snapshot_download(
            repo_id=MODEL_ID,
            revision=REVISION,
            repo_type="model",
            cache_dir=output_root,
            allow_patterns=sorted(EXPECTED_FILES),
        )
    ).resolve(strict=True)
    if not snapshot_path.is_relative_to(output_root):
        raise ValueError("downloaded snapshot escaped approved model root")

    files: list[dict[str, object]] = []
    for relative_path, expected_size in sorted(EXPECTED_FILES.items()):
        path = (snapshot_path / relative_path).resolve(strict=True)
        if not path.is_relative_to(output_root) or not path.is_file():
            raise ValueError(f"unsafe downloaded model file: {relative_path}")
        byte_count = path.stat().st_size
        if byte_count != expected_size:
            raise ValueError(f"downloaded file size changed: {relative_path}")
        files.append(
            {
                "relative_path": relative_path,
                "byte_count": byte_count,
                "sha256": _sha256_file(path),
            }
        )

    report = {
        "schema_version": "1",
        "provider": "fastembed",
        "public_model_name": PUBLIC_MODEL_NAME,
        "repository_id": MODEL_ID,
        "revision": REVISION,
        "license": LICENSE,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "cache_relative_path": "data/models/fastembed",
        "snapshot_relative_path": snapshot_path.relative_to(
            PROJECT_ROOT
        ).as_posix(),
        "file_count": len(files),
        "total_bytes": sum(file["byte_count"] for file in files),
        "files": files,
        "model_assets_sha256": _assets_sha256(files),
    }
    if existing_report is not None:
        stable_existing = {
            key: value
            for key, value in existing_report.items()
            if key != "retrieved_at"
        }
        stable_restored = {
            key: value
            for key, value in report.items()
            if key != "retrieved_at"
        }
        if stable_restored != stable_existing:
            raise ValueError(
                "restored model assets do not match tracked report"
            )
        print(
            json.dumps(
                {
                    "status": "restored",
                    "revision": REVISION,
                    "file_count": len(files),
                    "total_bytes": sum(
                        file["byte_count"] for file in files
                    ),
                    "model_assets_sha256": report[
                        "model_assets_sha256"
                    ],
                    "report_preserved": str(REPORT_PATH),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
