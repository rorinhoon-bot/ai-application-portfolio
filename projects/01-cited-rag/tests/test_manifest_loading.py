from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cited_rag.errors import (
    PathOutsideAllowedRootError,
    SourceManifestError,
)
from cited_rag.ingestion import load_source_manifest


def valid_manifest_data() -> dict[str, object]:
    return {
        "schema_version": "1",
        "sources": [
            {
                "schema_version": "1",
                "source_id": "py314-library-venv",
                "document_key": "library-venv",
                "python_version": "3.14",
                "documentation_release": "3.14.6",
                "source_url": (
                    "https://docs.python.org/zh-cn/3.14/library/venv.html"
                ),
                "relative_path": "html/3.14/library/venv.html",
                "retrieved_at": datetime(
                    2026,
                    7,
                    28,
                    10,
                    0,
                    tzinfo=timezone.utc,
                ).isoformat(),
                "expected_title": "venv — 创建虚拟环境",
                "license_name": (
                    "Python Software Foundation License Version 2"
                ),
                "license_url": (
                    "https://docs.python.org/zh-cn/3.14/license.html"
                ),
                "raw_sha256": "a" * 64,
                "media_type": "text/html",
                "language": "zh-CN",
            }
        ],
    }


def write_manifest(
    allowed_root: Path,
    content: bytes,
    *,
    relative_path: str = "manifest.json",
) -> str:
    path = allowed_root.joinpath(*relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return relative_path


def test_load_source_manifest_accepts_valid_utf8_json(tmp_path: Path) -> None:
    allowed_root = tmp_path / "sources"
    content = json.dumps(
        valid_manifest_data(),
        ensure_ascii=False,
    ).encode("utf-8")
    relative_path = write_manifest(allowed_root, content)

    manifest = load_source_manifest(
        allowed_root=allowed_root,
        relative_path=relative_path,
    )

    assert manifest.schema_version == "1"
    assert manifest.sources[0].source_id == "py314-library-venv"


@pytest.mark.parametrize(
    "relative_path",
    (
        "../manifest.json",
        "/absolute/manifest.json",
        "C:/manifest.json",
        r"nested\manifest.json",
        "nested//manifest.json",
    ),
)
def test_load_source_manifest_rejects_unsafe_path(
    tmp_path: Path,
    relative_path: str,
) -> None:
    allowed_root = tmp_path / "sources"
    allowed_root.mkdir()

    with pytest.raises(PathOutsideAllowedRootError):
        load_source_manifest(
            allowed_root=allowed_root,
            relative_path=relative_path,
        )


def test_load_source_manifest_rejects_wrong_extension(tmp_path: Path) -> None:
    allowed_root = tmp_path / "sources"
    write_manifest(allowed_root, b"{}", relative_path="manifest.txt")

    with pytest.raises(SourceManifestError, match="must use .json"):
        load_source_manifest(
            allowed_root=allowed_root,
            relative_path="manifest.txt",
        )


def test_load_source_manifest_rejects_invalid_utf8(tmp_path: Path) -> None:
    allowed_root = tmp_path / "sources"
    relative_path = write_manifest(allowed_root, b"\xff\xfe")

    with pytest.raises(SourceManifestError, match="not valid UTF-8"):
        load_source_manifest(
            allowed_root=allowed_root,
            relative_path=relative_path,
        )


def test_load_source_manifest_rejects_invalid_json(tmp_path: Path) -> None:
    allowed_root = tmp_path / "sources"
    relative_path = write_manifest(allowed_root, b"{not-json}")

    with pytest.raises(SourceManifestError, match="not valid JSON"):
        load_source_manifest(
            allowed_root=allowed_root,
            relative_path=relative_path,
        )


def test_load_source_manifest_hides_schema_details(tmp_path: Path) -> None:
    allowed_root = tmp_path / "sources"
    invalid_data = valid_manifest_data()
    invalid_data["secret_field"] = "must-not-leak"
    content = json.dumps(invalid_data).encode("utf-8")
    relative_path = write_manifest(allowed_root, content)

    with pytest.raises(
        SourceManifestError,
        match="manifest schema validation failed",
    ) as captured:
        load_source_manifest(
            allowed_root=allowed_root,
            relative_path=relative_path,
        )

    assert "must-not-leak" not in str(captured.value)
