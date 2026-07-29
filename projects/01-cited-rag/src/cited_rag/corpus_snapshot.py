"""Deterministic packaging and safe restoration of approved HTML snapshots."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Annotated, Literal, Self
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cited_rag.errors import CorpusSnapshotError

FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
ARCHIVE_NAME = "corpus-snapshot.zip"


class SnapshotContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CorpusSnapshotFile(SnapshotContract):
    relative_path: Annotated[str, Field(min_length=1, max_length=512)]
    byte_count: Annotated[int, Field(gt=0)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if "\\" in value or ":" in value:
            raise ValueError("snapshot path must use safe POSIX syntax")
        path = PurePosixPath(value)
        parts = value.split("/")
        if (
            path.is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
            or path.as_posix() != value
            or path.suffix != ".html"
            or parts[0] not in {"html", "license"}
        ):
            raise ValueError("snapshot path is outside approved HTML roots")
        return value


class CorpusSnapshotReport(SnapshotContract):
    schema_version: Literal["1"]
    archive_name: Literal["corpus-snapshot.zip"]
    archive_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    archive_byte_count: Annotated[int, Field(gt=0)]
    file_count: Annotated[int, Field(gt=0)]
    uncompressed_byte_count: Annotated[int, Field(gt=0)]
    files: Annotated[
        tuple[CorpusSnapshotFile, ...],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("snapshot paths must be unique")
        if self.file_count != len(self.files):
            raise ValueError("file_count must match files")
        if self.uncompressed_byte_count != sum(
            item.byte_count for item in self.files
        ):
            raise ValueError("uncompressed_byte_count must match files")
        if {PurePosixPath(path).parts[0] for path in paths} != {
            "html",
            "license",
        }:
            raise ValueError("snapshot must contain corpus and license roots")
        return self


def package_corpus_snapshot(
    *,
    source_root: Path,
    acquisition_report_path: Path,
    archive_path: Path,
    snapshot_report_path: Path,
) -> CorpusSnapshotReport:
    """Verify approved bytes, then create one reproducible ZIP and report."""

    if archive_path.exists() or snapshot_report_path.exists():
        raise CorpusSnapshotError("refusing to overwrite snapshot artifacts")
    files = _load_acquisition_files(acquisition_report_path)
    verified: list[tuple[CorpusSnapshotFile, bytes]] = []
    resolved_root = source_root.resolve(strict=True)
    for item in files:
        path = _safe_source_path(resolved_root, item.relative_path)
        data = path.read_bytes()
        if (
            len(data) != item.byte_count
            or sha256(data).hexdigest() != item.sha256
        ):
            raise CorpusSnapshotError(
                f"source bytes changed: {item.relative_path}"
            )
        verified.append((item, data))

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_temporary = _temporary_path(archive_path.parent, ".zip.tmp")
    report_temporary = _temporary_path(
        snapshot_report_path.parent,
        ".json.tmp",
    )
    try:
        with ZipFile(
            archive_temporary,
            mode="w",
            compression=ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for item, data in verified:
                info = ZipInfo(item.relative_path, date_time=FIXED_ZIP_TIME)
                info.compress_type = ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data, compresslevel=9)

        archive_bytes = archive_temporary.read_bytes()
        report = CorpusSnapshotReport(
            schema_version="1",
            archive_name=ARCHIVE_NAME,
            archive_sha256=sha256(archive_bytes).hexdigest(),
            archive_byte_count=len(archive_bytes),
            file_count=len(files),
            uncompressed_byte_count=sum(
                item.byte_count for item in files
            ),
            files=files,
        )
        report_temporary.write_text(
            json.dumps(
                report.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(archive_temporary, archive_path)
        os.replace(report_temporary, snapshot_report_path)
        return report
    finally:
        archive_temporary.unlink(missing_ok=True)
        report_temporary.unlink(missing_ok=True)


def restore_corpus_snapshot(
    *,
    source_root: Path,
    archive_path: Path,
    snapshot_report_path: Path,
) -> CorpusSnapshotReport:
    """Validate the complete archive before restoring absent HTML roots."""

    try:
        report = CorpusSnapshotReport.model_validate_json(
            snapshot_report_path.read_bytes()
        )
    except Exception as error:
        raise CorpusSnapshotError("snapshot report is invalid") from error
    archive = archive_path.resolve(strict=True)
    if (
        archive.name != report.archive_name
        or not archive.is_file()
        or archive.stat().st_size != report.archive_byte_count
        or _sha256_file(archive) != report.archive_sha256
    ):
        raise CorpusSnapshotError("snapshot archive identity changed")

    expected = {item.relative_path: item for item in report.files}
    restored: dict[str, bytes] = {}
    try:
        with ZipFile(archive, mode="r") as zip_file:
            infos = zip_file.infolist()
            if (
                len(infos) != len(expected)
                or {info.filename for info in infos} != set(expected)
            ):
                raise CorpusSnapshotError(
                    "snapshot archive member list changed"
                )
            for info in infos:
                item = expected[info.filename]
                file_type = (info.external_attr >> 16) & 0o170000
                if (
                    info.is_dir()
                    or info.flag_bits & 0x1
                    or file_type not in {0, 0o100000}
                    or info.file_size != item.byte_count
                ):
                    raise CorpusSnapshotError(
                        f"unsafe snapshot member: {info.filename}"
                    )
                data = zip_file.read(info)
                if sha256(data).hexdigest() != item.sha256:
                    raise CorpusSnapshotError(
                        f"snapshot member hash changed: {info.filename}"
                    )
                restored[info.filename] = data
    except CorpusSnapshotError:
        raise
    except Exception as error:
        raise CorpusSnapshotError("snapshot archive is invalid") from error

    source_root.mkdir(parents=True, exist_ok=True)
    resolved_root = source_root.resolve(strict=True)
    targets = [resolved_root / "html", resolved_root / "license"]
    if any(target.exists() or target.is_symlink() for target in targets):
        raise CorpusSnapshotError(
            "refusing to overwrite restored corpus roots"
        )

    staging = Path(
        tempfile.mkdtemp(prefix=".corpus-restore-", dir=resolved_root)
    )
    created: list[Path] = []
    try:
        for relative_path, data in restored.items():
            output = _safe_source_path(
                staging,
                relative_path,
                require_exists=False,
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        for target in targets:
            staged = staging / target.name
            os.replace(staged, target)
            created.append(target)
        return report
    except Exception as error:
        for target in created:
            if target.parent == resolved_root and target.is_dir():
                shutil.rmtree(target)
        if isinstance(error, CorpusSnapshotError):
            raise
        raise CorpusSnapshotError("snapshot restore failed") from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _load_acquisition_files(path: Path) -> tuple[CorpusSnapshotFile, ...]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        records = value["records"]
        if value["record_count"] != len(records):
            raise ValueError("record count changed")
        files = tuple(
            CorpusSnapshotFile(
                relative_path=record["relative_path"],
                byte_count=record["byte_count"],
                sha256=record["raw_sha256"],
            )
            for record in records
        )
        CorpusSnapshotReport(
            schema_version="1",
            archive_name=ARCHIVE_NAME,
            archive_sha256="0" * 64,
            archive_byte_count=1,
            file_count=len(files),
            uncompressed_byte_count=sum(
                item.byte_count for item in files
            ),
            files=files,
        )
        return tuple(sorted(files, key=lambda item: item.relative_path))
    except Exception as error:
        raise CorpusSnapshotError(
            "acquisition report cannot define snapshot"
        ) from error


def _safe_source_path(
    root: Path,
    relative_path: str,
    *,
    require_exists: bool = True,
) -> Path:
    try:
        validated = CorpusSnapshotFile(
            relative_path=relative_path,
            byte_count=1,
            sha256="0" * 64,
        )
        resolved_root = root.resolve(strict=True)
        candidate = resolved_root.joinpath(
            *PurePosixPath(validated.relative_path).parts
        )
        resolved = candidate.resolve(strict=require_exists)
    except Exception as error:
        raise CorpusSnapshotError(
            f"unsafe snapshot path: {relative_path}"
        ) from error
    if not resolved.is_relative_to(resolved_root):
        raise CorpusSnapshotError(
            f"snapshot path escaped root: {relative_path}"
        )
    if require_exists and not resolved.is_file():
        raise CorpusSnapshotError(
            f"snapshot source is not a file: {relative_path}"
        )
    return resolved


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _temporary_path(parent: Path, suffix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(suffix=suffix, dir=parent)
    os.close(descriptor)
    return Path(name)
