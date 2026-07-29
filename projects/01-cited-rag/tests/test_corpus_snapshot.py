from hashlib import sha256
import json
from pathlib import Path

import pytest

from cited_rag.corpus_snapshot import (
    package_corpus_snapshot,
    restore_corpus_snapshot,
)
from cited_rag.errors import CorpusSnapshotError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_source(root: Path) -> Path:
    source = root / "sources"
    values = {
        "html/3.14.6/tutorial/a.html": b"<html>A</html>",
        "license/python-license.html": b"<html>License</html>",
    }
    records = []
    for relative_path, data in values.items():
        path = source.joinpath(*relative_path.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        records.append(
            {
                "relative_path": relative_path,
                "byte_count": len(data),
                "raw_sha256": sha256(data).hexdigest(),
            }
        )
    (source / "acquisition-report.json").write_text(
        json.dumps(
            {
                "record_count": len(records),
                "records": records,
            }
        ),
        encoding="utf-8",
    )
    return source


def package(root: Path):
    source = make_source(root)
    archive = root / "corpus-snapshot.zip"
    report = root / "corpus-snapshot.json"
    result = package_corpus_snapshot(
        source_root=source,
        acquisition_report_path=source / "acquisition-report.json",
        archive_path=archive,
        snapshot_report_path=report,
    )
    return source, archive, report, result


def test_package_is_deterministic_and_restore_preserves_bytes(
    tmp_path: Path,
) -> None:
    source_a, archive_a, report_a, result_a = package(tmp_path / "a")
    _, archive_b, _, result_b = package(tmp_path / "b")

    assert archive_a.read_bytes() == archive_b.read_bytes()
    assert result_a.archive_sha256 == result_b.archive_sha256

    restored_root = tmp_path / "restored" / "sources"
    restored = restore_corpus_snapshot(
        source_root=restored_root,
        archive_path=archive_a,
        snapshot_report_path=report_a,
    )

    assert restored == result_a
    assert (
        restored_root / "html" / "3.14.6" / "tutorial" / "a.html"
    ).read_bytes() == b"<html>A</html>"
    assert (
        restored_root / "license" / "python-license.html"
    ).read_bytes() == b"<html>License</html>"
    assert (source_a / "html").is_dir()


def test_package_rejects_changed_source_bytes(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    (
        source / "html" / "3.14.6" / "tutorial" / "a.html"
    ).write_bytes(b"changed")

    with pytest.raises(
        CorpusSnapshotError,
        match="CORPUS_SNAPSHOT_ERROR",
    ):
        package_corpus_snapshot(
            source_root=source,
            acquisition_report_path=source / "acquisition-report.json",
            archive_path=tmp_path / "snapshot.zip",
            snapshot_report_path=tmp_path / "snapshot.json",
        )


def test_restore_rejects_archive_tampering(tmp_path: Path) -> None:
    _, archive, report, _ = package(tmp_path / "package")
    archive.write_bytes(archive.read_bytes() + b"tampered")

    with pytest.raises(
        CorpusSnapshotError,
        match="CORPUS_SNAPSHOT_ERROR",
    ):
        restore_corpus_snapshot(
            source_root=tmp_path / "restored",
            archive_path=archive,
            snapshot_report_path=report,
        )


def test_acquisition_report_rejects_path_traversal(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sources"
    source.mkdir()
    (source / "acquisition-report.json").write_text(
        json.dumps(
            {
                "record_count": 2,
                "records": [
                    {
                        "relative_path": "../escape.html",
                        "byte_count": 1,
                        "raw_sha256": "0" * 64,
                    },
                    {
                        "relative_path": "license/license.html",
                        "byte_count": 1,
                        "raw_sha256": "0" * 64,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        CorpusSnapshotError,
        match="CORPUS_SNAPSHOT_ERROR",
    ):
        package_corpus_snapshot(
            source_root=source,
            acquisition_report_path=source / "acquisition-report.json",
            archive_path=tmp_path / "snapshot.zip",
            snapshot_report_path=tmp_path / "snapshot.json",
        )


def test_tracked_snapshot_restores_all_approved_files(
    tmp_path: Path,
) -> None:
    report = restore_corpus_snapshot(
        source_root=tmp_path / "sources",
        archive_path=PROJECT_ROOT / "data" / "corpus-snapshot.zip",
        snapshot_report_path=(
            PROJECT_ROOT / "data" / "corpus-snapshot.json"
        ),
    )

    assert report.file_count == 26
    assert report.uncompressed_byte_count == 3_581_318
    assert report.archive_sha256 == (
        "c1d3fb0a04968f8810fe71efede103c0"
        "4d28bb2499ac53e690f5bbbc27d1c2a0"
    )
