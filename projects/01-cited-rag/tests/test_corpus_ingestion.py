from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from cited_rag.errors import SourceHashMismatchError, SourceManifestError
from cited_rag.ingestion import (
    CorpusIngestor,
    SingleDocumentIngestor,
    make_manifest_sha256,
)
from cited_rag.models import (
    CorpusImportStatus,
    SourceManifest,
    SourceManifestEntry,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "html"
FIXED_IMPORT_TIME = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def prepare_versioned_source(
    allowed_root: Path,
    *,
    python_version: str,
    fixture_name: str,
) -> tuple[str, bytes]:
    relative_path = f"html/{python_version}/library/venv.html"
    source_path = allowed_root.joinpath(*relative_path.split("/"))
    source_path.parent.mkdir(parents=True, exist_ok=True)
    raw_html = (FIXTURE_ROOT / f"{fixture_name}.html").read_bytes()
    source_path.write_bytes(raw_html)
    return relative_path, raw_html


def manifest_entry(
    *,
    python_version: str,
    relative_path: str,
    raw_html: bytes,
    **overrides: object,
) -> SourceManifestEntry:
    compact_version = python_version.replace(".", "")
    values: dict[str, object] = {
        "schema_version": "1",
        "source_id": f"py{compact_version}-library-venv",
        "document_key": "library-venv",
        "python_version": python_version,
        "documentation_release": (
            "3.14.6" if python_version == "3.14" else "3.13.14"
        ),
        "source_url": (
            f"https://docs.python.org/zh-cn/{python_version}/library/venv.html"
        ),
        "relative_path": relative_path,
        "retrieved_at": datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc),
        "expected_title": "venv — 创建虚拟环境",
        "license_name": "Python Software Foundation License Version 2",
        "license_url": (
            f"https://docs.python.org/zh-cn/{python_version}/license.html"
        ),
        "raw_sha256": sha256(raw_html).hexdigest(),
        "media_type": "text/html",
        "language": "zh-CN",
    }
    values.update(overrides)
    return SourceManifestEntry.model_validate(values)


def prepare_manifest(
    tmp_path: Path,
    *,
    reverse: bool = False,
) -> tuple[Path, SourceManifest]:
    allowed_root = tmp_path / "sources"
    path_314, html_314 = prepare_versioned_source(
        allowed_root,
        python_version="3.14",
        fixture_name="valid_sphinx_page",
    )
    path_313, html_313 = prepare_versioned_source(
        allowed_root,
        python_version="3.13",
        fixture_name="valid_sphinx_page_313",
    )
    entries = [
        manifest_entry(
            python_version="3.14",
            relative_path=path_314,
            raw_html=html_314,
        ),
        manifest_entry(
            python_version="3.13",
            relative_path=path_313,
            raw_html=html_313,
        ),
    ]
    if reverse:
        entries.reverse()
    return allowed_root, SourceManifest(schema_version="1", sources=tuple(entries))


def corpus_ingestor() -> CorpusIngestor:
    document_ingestor = SingleDocumentIngestor(clock=lambda: FIXED_IMPORT_TIME)
    return CorpusIngestor(document_ingestor=document_ingestor)


def test_corpus_ingest_validates_and_sorts_all_documents(tmp_path: Path) -> None:
    allowed_root, manifest = prepare_manifest(tmp_path, reverse=True)

    corpus = corpus_ingestor().ingest(manifest, allowed_root=allowed_root)

    assert corpus.status is CorpusImportStatus.READY
    assert [document.source.source_id for document in corpus.documents] == [
        "py313-library-venv",
        "py314-library-venv",
    ]
    assert len(corpus.documents[0].blocks) == 2
    assert len(corpus.documents[1].blocks) == 11


def test_manifest_hash_and_corpus_id_ignore_source_order(tmp_path: Path) -> None:
    first_root, first_manifest = prepare_manifest(tmp_path / "first")
    second_root, second_manifest = prepare_manifest(
        tmp_path / "second",
        reverse=True,
    )

    first = corpus_ingestor().ingest(first_manifest, allowed_root=first_root)
    second = corpus_ingestor().ingest(second_manifest, allowed_root=second_root)

    assert make_manifest_sha256(first_manifest) == make_manifest_sha256(
        second_manifest
    )
    assert first.corpus_id == second.corpus_id


def test_repeat_ingest_revalidates_then_returns_unchanged(tmp_path: Path) -> None:
    allowed_root, manifest = prepare_manifest(tmp_path)
    first = corpus_ingestor().ingest(manifest, allowed_root=allowed_root)

    second = corpus_ingestor().ingest(
        manifest,
        allowed_root=allowed_root,
        active_manifest=manifest,
    )

    assert second.status is CorpusImportStatus.UNCHANGED
    assert second.corpus_id == first.corpus_id
    assert [document.snapshot.snapshot_id for document in second.documents] == [
        document.snapshot.snapshot_id for document in first.documents
    ]


def test_repeat_ingest_does_not_skip_changed_file_validation(
    tmp_path: Path,
) -> None:
    allowed_root, manifest = prepare_manifest(tmp_path)
    first = corpus_ingestor().ingest(manifest, allowed_root=allowed_root)
    changed_path = allowed_root / "html" / "3.14" / "library" / "venv.html"
    changed_path.write_text("<html>changed</html>", encoding="utf-8")

    with pytest.raises(SourceHashMismatchError):
        corpus_ingestor().ingest(
            manifest,
            allowed_root=allowed_root,
            active_manifest=manifest,
        )


def test_repeat_ingest_rejects_same_source_id_with_new_hash(
    tmp_path: Path,
) -> None:
    allowed_root, active_manifest = prepare_manifest(tmp_path)
    new_source = active_manifest.sources[0].model_copy(
        update={"raw_sha256": "f" * 64}
    )
    new_manifest = SourceManifest(
        schema_version="1",
        sources=(new_source, active_manifest.sources[1]),
    )

    with pytest.raises(
        SourceManifestError,
        match="source_id content conflict",
    ):
        corpus_ingestor().ingest(
            new_manifest,
            allowed_root=allowed_root,
            active_manifest=active_manifest,
        )


def test_new_source_id_can_replace_active_document_snapshot(
    tmp_path: Path,
) -> None:
    allowed_root, active_manifest = prepare_manifest(tmp_path)
    old_source_314 = next(
        source
        for source in active_manifest.sources
        if source.python_version == "3.14"
    )
    source_path = allowed_root.joinpath(*old_source_314.relative_path.split("/"))
    updated_html = source_path.read_text(encoding="utf-8").replace(
        "创建   环境。",
        "创建   更新后的环境。",
    )
    updated_relative_path = "html/3.14/library/venv-snapshot-2.html"
    updated_path = allowed_root.joinpath(*updated_relative_path.split("/"))
    updated_path.write_text(updated_html, encoding="utf-8")
    updated_raw_html = updated_path.read_bytes()
    replacement = old_source_314.model_copy(
        update={
            "source_id": "py314-library-venv-snapshot-2",
            "relative_path": updated_relative_path,
            "raw_sha256": sha256(updated_raw_html).hexdigest(),
        }
    )
    source_313 = next(
        source
        for source in active_manifest.sources
        if source.python_version == "3.13"
    )
    new_manifest = SourceManifest(
        schema_version="1",
        sources=(source_313, replacement),
    )

    corpus = corpus_ingestor().ingest(
        new_manifest,
        allowed_root=allowed_root,
        active_manifest=active_manifest,
    )

    assert corpus.status is CorpusImportStatus.READY
    assert corpus.manifest.sources[1].source_id == replacement.source_id


def test_batch_failure_returns_no_partial_corpus(tmp_path: Path) -> None:
    allowed_root, manifest = prepare_manifest(tmp_path)
    bad_source = manifest.sources[1].model_copy(update={"raw_sha256": "f" * 64})
    bad_manifest = SourceManifest(
        schema_version="1",
        sources=(manifest.sources[0], bad_source),
    )
    result = None

    with pytest.raises(SourceHashMismatchError):
        result = corpus_ingestor().ingest(
            bad_manifest,
            allowed_root=allowed_root,
        )

    assert result is None
