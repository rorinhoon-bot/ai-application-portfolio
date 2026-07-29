from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from cited_rag.errors import (
    DocumentParseError,
    PathOutsideAllowedRootError,
    SourceHashMismatchError,
    SourceManifestError,
)
from cited_rag.ingestion import (
    PARSER_SCHEMA_VERSION,
    SingleDocumentIngestor,
)
from cited_rag.models import SourceManifestEntry

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "html"
FIXED_IMPORT_TIME = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def prepare_source_file(
    tmp_path: Path,
    *,
    fixture_name: str = "valid_sphinx_page",
) -> tuple[Path, str, bytes]:
    allowed_root = tmp_path / "sources"
    source_path = allowed_root / "html" / "3.14" / "library" / "venv.html"
    source_path.parent.mkdir(parents=True)
    raw_html = (FIXTURE_ROOT / f"{fixture_name}.html").read_bytes()
    source_path.write_bytes(raw_html)
    return allowed_root, "html/3.14/library/venv.html", raw_html


def source_entry(
    *,
    relative_path: str,
    raw_html: bytes,
    **overrides: object,
) -> SourceManifestEntry:
    values: dict[str, object] = {
        "schema_version": "1",
        "source_id": "py314-library-venv",
        "document_key": "library-venv",
        "python_version": "3.14",
        "documentation_release": "3.14.6",
        "source_url": "https://docs.python.org/zh-cn/3.14/library/venv.html",
        "relative_path": relative_path,
        "retrieved_at": datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc),
        "expected_title": "venv — 创建虚拟环境",
        "license_name": "Python Software Foundation License Version 2",
        "license_url": "https://docs.python.org/zh-cn/3.14/license.html",
        "raw_sha256": sha256(raw_html).hexdigest(),
        "media_type": "text/html",
        "language": "zh-CN",
    }
    values.update(overrides)
    return SourceManifestEntry.model_validate(values)


def ingestor() -> SingleDocumentIngestor:
    return SingleDocumentIngestor(clock=lambda: FIXED_IMPORT_TIME)


def test_ingest_binds_verified_snapshot_and_blocks(tmp_path: Path) -> None:
    allowed_root, relative_path, raw_html = prepare_source_file(tmp_path)
    source = source_entry(relative_path=relative_path, raw_html=raw_html)

    imported = ingestor().ingest(source, allowed_root=allowed_root)

    assert imported.source == source
    assert imported.snapshot.source_id == source.source_id
    assert imported.snapshot.raw_html_sha256 == source.raw_sha256
    assert imported.snapshot.parser_schema_version == PARSER_SCHEMA_VERSION
    assert imported.snapshot.imported_at == FIXED_IMPORT_TIME
    assert len(imported.blocks) == 11
    assert [block.block_order for block in imported.blocks] == list(range(1, 12))
    assert all(
        block.snapshot_id == imported.snapshot.snapshot_id
        for block in imported.blocks
    )


def test_ingest_ids_are_stable_when_import_time_changes(tmp_path: Path) -> None:
    allowed_root, relative_path, raw_html = prepare_source_file(tmp_path)
    source = source_entry(relative_path=relative_path, raw_html=raw_html)
    first = SingleDocumentIngestor(
        clock=lambda: datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    ).ingest(source, allowed_root=allowed_root)
    second = SingleDocumentIngestor(
        clock=lambda: datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
    ).ingest(source, allowed_root=allowed_root)

    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id
    assert [block.block_id for block in first.blocks] == [
        block.block_id for block in second.blocks
    ]
    assert first.snapshot.imported_at != second.snapshot.imported_at


def test_ingest_rejects_hash_mismatch(tmp_path: Path) -> None:
    allowed_root, relative_path, raw_html = prepare_source_file(tmp_path)
    source = source_entry(
        relative_path=relative_path,
        raw_html=raw_html,
        raw_sha256="f" * 64,
    )

    with pytest.raises(SourceHashMismatchError) as captured:
        ingestor().ingest(source, allowed_root=allowed_root)

    assert captured.value.code == "SOURCE_HASH_MISMATCH"
    assert str(allowed_root) not in str(captured.value)


def test_ingest_rejects_title_mismatch(tmp_path: Path) -> None:
    allowed_root, relative_path, raw_html = prepare_source_file(tmp_path)
    source = source_entry(
        relative_path=relative_path,
        raw_html=raw_html,
        expected_title="错误标题",
    )

    with pytest.raises(SourceManifestError, match="page title does not match"):
        ingestor().ingest(source, allowed_root=allowed_root)


def test_ingest_rejects_canonical_url_mismatch(tmp_path: Path) -> None:
    allowed_root, relative_path, raw_html = prepare_source_file(tmp_path)
    source = source_entry(
        relative_path=relative_path,
        raw_html=raw_html,
        source_url=(
            "https://docs.python.org/zh-cn/3.14/library/venv-copy.html"
        ),
    )

    with pytest.raises(SourceManifestError, match="canonical URL does not match"):
        ingestor().ingest(source, allowed_root=allowed_root)


def test_ingest_accepts_official_language_neutral_canonical(
    tmp_path: Path,
) -> None:
    allowed_root, relative_path, raw_html = prepare_source_file(tmp_path)
    localized = b"https://docs.python.org/zh-cn/3.14/library/venv.html"
    language_neutral = b"https://docs.python.org/3/library/venv.html"
    raw_html = raw_html.replace(localized, language_neutral)
    source_path = allowed_root.joinpath(*relative_path.split("/"))
    source_path.write_bytes(raw_html)
    source = source_entry(relative_path=relative_path, raw_html=raw_html)

    imported = ingestor().ingest(source, allowed_root=allowed_root)

    assert str(imported.snapshot.html_canonical_url) == language_neutral.decode()


def test_ingest_rejects_invalid_utf8(tmp_path: Path) -> None:
    allowed_root = tmp_path / "sources"
    source_path = allowed_root / "html" / "3.14" / "broken.html"
    source_path.parent.mkdir(parents=True)
    raw_html = b"\xff\xfe\x00"
    source_path.write_bytes(raw_html)
    source = source_entry(
        relative_path="html/3.14/broken.html",
        raw_html=raw_html,
    )

    with pytest.raises(DocumentParseError, match="HTML is not valid UTF-8"):
        ingestor().ingest(source, allowed_root=allowed_root)


def test_ingest_rejects_missing_source_file(tmp_path: Path) -> None:
    allowed_root = tmp_path / "sources"
    allowed_root.mkdir()
    source = source_entry(
        relative_path="html/3.14/library/missing.html",
        raw_html=b"missing",
    )

    with pytest.raises(SourceManifestError, match="source file not found"):
        ingestor().ingest(source, allowed_root=allowed_root)


def test_ingest_rejects_resolved_path_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allowed_root = tmp_path / "sources"
    outside_root = tmp_path / "outside"
    outside_file = outside_root / "venv.html"
    outside_root.mkdir()
    outside_file.write_text("<html></html>", encoding="utf-8")

    link_parent = allowed_root / "html" / "3.14" / "library"
    link_parent.mkdir(parents=True)
    link_path = link_parent / "venv.html"
    try:
        os.symlink(outside_file, link_path)
    except (OSError, NotImplementedError):
        link_path.write_text("<html></html>", encoding="utf-8")
        original_resolve = Path.resolve

        def resolve_with_simulated_escape(
            path: Path,
            strict: bool = False,
        ) -> Path:
            if path == link_path:
                return original_resolve(outside_file, strict=strict)
            return original_resolve(path, strict=strict)

        monkeypatch.setattr(Path, "resolve", resolve_with_simulated_escape)

    raw_html = outside_file.read_bytes()
    source = source_entry(
        relative_path="html/3.14/library/venv.html",
        raw_html=raw_html,
    )

    with pytest.raises(PathOutsideAllowedRootError) as captured:
        ingestor().ingest(source, allowed_root=allowed_root)

    assert captured.value.code == "PATH_OUTSIDE_ALLOWED_ROOT"


def test_ingest_same_bytes_under_new_source_gets_new_snapshot_id(
    tmp_path: Path,
) -> None:
    allowed_root, relative_path, raw_html = prepare_source_file(tmp_path)
    first_source = source_entry(relative_path=relative_path, raw_html=raw_html)

    second_relative_path = "html/3.14/library/venv-copy.html"
    second_path = allowed_root.joinpath(*Path(second_relative_path).parts)
    second_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        allowed_root.joinpath(*Path(relative_path).parts),
        second_path,
    )
    second_source = source_entry(
        relative_path=second_relative_path,
        raw_html=raw_html,
        source_id="py314-library-venv-copy",
    )

    first = ingestor().ingest(first_source, allowed_root=allowed_root)
    second = ingestor().ingest(second_source, allowed_root=allowed_root)

    assert first.snapshot.snapshot_id != second.snapshot.snapshot_id
