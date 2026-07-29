"""Safe single-document loading and metadata binding."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from cited_rag.adapters.html_parser import PythonDocsHtmlParser
from cited_rag.errors import (
    DocumentParseError,
    PathOutsideAllowedRootError,
    SourceHashMismatchError,
    SourceManifestError,
    UnsupportedDocumentTypeError,
)
from cited_rag.models import (
    ContentBlock,
    CorpusImportStatus,
    DocumentSnapshot,
    ImportedCorpus,
    ImportedDocument,
    ParsedContentBlock,
    ParsedDocument,
    SourceManifest,
    SourceManifestEntry,
)

PARSER_SCHEMA_VERSION = "parser-v1"
IDENTITY_NAMESPACE = uuid5(NAMESPACE_URL, "urn:cited-rag:document-identity:v1")

Clock = Callable[[], datetime]


class SingleDocumentIngestor:
    """Verify and bind one manifest source without writing external state."""

    def __init__(
        self,
        *,
        parser: PythonDocsHtmlParser | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._parser = parser or PythonDocsHtmlParser()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def ingest(
        self,
        source: SourceManifestEntry,
        *,
        allowed_root: Path,
    ) -> ImportedDocument:
        source_path = resolve_source_path(
            allowed_root=allowed_root,
            relative_path=source.relative_path,
        )
        raw_html = source_path.read_bytes()
        actual_hash = sha256(raw_html).hexdigest()
        if actual_hash != source.raw_sha256:
            raise SourceHashMismatchError(
                f"source bytes do not match manifest: {source.source_id}"
            )

        try:
            html = raw_html.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise DocumentParseError("HTML is not valid UTF-8") from error

        parsed = self._parser.parse(html)
        self._validate_parsed_source(source=source, parsed=parsed)
        return self._bind(source=source, parsed=parsed, raw_html_sha256=actual_hash)

    @staticmethod
    def _validate_parsed_source(
        *,
        source: SourceManifestEntry,
        parsed: ParsedDocument,
    ) -> None:
        if parsed.page_title != source.expected_title:
            raise SourceManifestError(
                f"page title does not match manifest: {source.source_id}"
            )
        if (
            parsed.html_canonical_url is not None
            and not canonical_url_matches_source(
                canonical_url=parsed.html_canonical_url,
                source_url=str(source.source_url),
                python_version=source.python_version,
            )
        ):
            raise SourceManifestError(
                f"canonical URL does not match manifest: {source.source_id}"
            )

    def _bind(
        self,
        *,
        source: SourceManifestEntry,
        parsed: ParsedDocument,
        raw_html_sha256: str,
    ) -> ImportedDocument:
        snapshot_id = make_snapshot_id(
            source_id=source.source_id,
            raw_html_sha256=raw_html_sha256,
        )
        snapshot = DocumentSnapshot(
            snapshot_id=snapshot_id,
            source_id=source.source_id,
            page_title=parsed.page_title,
            html_canonical_url=parsed.html_canonical_url,
            raw_html_sha256=raw_html_sha256,
            cleaned_content_sha256=make_cleaned_content_sha256(parsed),
            parser_schema_version=PARSER_SCHEMA_VERSION,
            imported_at=self._clock(),
            warnings=parsed.warnings,
        )
        blocks = tuple(
            _bind_block(
                parsed_block,
                snapshot_id=snapshot_id,
                parser_schema_version=PARSER_SCHEMA_VERSION,
            )
            for parsed_block in parsed.blocks
        )
        return ImportedDocument(source=source, snapshot=snapshot, blocks=blocks)


def canonical_url_matches_source(
    *,
    canonical_url: str,
    source_url: str,
    python_version: str,
) -> bool:
    """Accept the localized URL or Python's official language-neutral canonical."""

    if canonical_url == source_url:
        return True

    source = urlsplit(source_url)
    canonical = urlsplit(canonical_url)
    localized_prefix = f"/zh-cn/{python_version}/"
    if not source.path.startswith(localized_prefix):
        return False
    document_path = source.path.removeprefix(localized_prefix)
    return (
        canonical.scheme == "https"
        and canonical.hostname == "docs.python.org"
        and canonical.username is None
        and canonical.password is None
        and canonical.port in {None, 443}
        and canonical.path == f"/3/{document_path}"
        and not canonical.query
        and not canonical.fragment
    )


class CorpusIngestor:
    """Validate every manifest source before exposing an in-memory corpus."""

    def __init__(
        self,
        *,
        document_ingestor: SingleDocumentIngestor | None = None,
    ) -> None:
        self._document_ingestor = document_ingestor or SingleDocumentIngestor()

    def ingest(
        self,
        manifest: SourceManifest,
        *,
        allowed_root: Path,
        active_manifest: SourceManifest | None = None,
    ) -> ImportedCorpus:
        if active_manifest is not None:
            _validate_source_identity_history(
                manifest=manifest,
                active_manifest=active_manifest,
            )
        ordered_sources = tuple(
            sorted(manifest.sources, key=lambda source: source.source_id)
        )
        documents = tuple(
            self._document_ingestor.ingest(source, allowed_root=allowed_root)
            for source in ordered_sources
        )
        manifest_sha256 = make_manifest_sha256(manifest)
        corpus_id = make_corpus_id(
            manifest_sha256=manifest_sha256,
            parser_schema_version=PARSER_SCHEMA_VERSION,
        )
        active_corpus_id = (
            make_corpus_id(
                manifest_sha256=make_manifest_sha256(active_manifest),
                parser_schema_version=PARSER_SCHEMA_VERSION,
            )
            if active_manifest is not None
            else None
        )
        status = (
            CorpusImportStatus.UNCHANGED
            if active_corpus_id == corpus_id
            else CorpusImportStatus.READY
        )
        return ImportedCorpus(
            corpus_id=corpus_id,
            manifest_sha256=manifest_sha256,
            parser_schema_version=PARSER_SCHEMA_VERSION,
            status=status,
            manifest=manifest,
            documents=documents,
        )


def _validate_source_identity_history(
    *,
    manifest: SourceManifest,
    active_manifest: SourceManifest,
) -> None:
    active_hashes = {
        source.source_id: source.raw_sha256
        for source in active_manifest.sources
    }
    for source in manifest.sources:
        active_hash = active_hashes.get(source.source_id)
        if active_hash is not None and active_hash != source.raw_sha256:
            raise SourceManifestError(
                f"source_id content conflict: {source.source_id}"
            )


def resolve_source_path(*, allowed_root: Path, relative_path: str) -> Path:
    """Resolve one already lexically validated path inside an allowed root."""

    return resolve_allowed_file_path(
        allowed_root=allowed_root,
        relative_path=relative_path,
        expected_suffix=".html",
        file_label="source",
    )


def load_source_manifest(
    *,
    allowed_root: Path,
    relative_path: str,
) -> SourceManifest:
    """Load one UTF-8 JSON manifest without exposing its raw contents."""

    manifest_path = resolve_allowed_file_path(
        allowed_root=allowed_root,
        relative_path=relative_path,
        expected_suffix=".json",
        file_label="manifest",
    )
    raw_manifest = manifest_path.read_bytes()
    try:
        manifest_text = raw_manifest.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise SourceManifestError("manifest is not valid UTF-8") from error
    try:
        manifest_data = json.loads(manifest_text)
    except json.JSONDecodeError as error:
        raise SourceManifestError("manifest is not valid JSON") from error
    try:
        return SourceManifest.model_validate(manifest_data)
    except ValidationError as error:
        raise SourceManifestError("manifest schema validation failed") from error


def resolve_allowed_file_path(
    *,
    allowed_root: Path,
    relative_path: str,
    expected_suffix: str,
    file_label: str,
) -> Path:
    """Resolve a normalized relative file beneath one trusted root."""

    _validate_relative_file_path(
        relative_path=relative_path,
        expected_suffix=expected_suffix,
        file_label=file_label,
    )
    try:
        resolved_root = allowed_root.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise SourceManifestError("allowed data root not found") from error
    if not resolved_root.is_dir():
        raise SourceManifestError("allowed data root is not a directory")

    relative_parts = PurePosixPath(relative_path).parts
    candidate = resolved_root.joinpath(*relative_parts)
    try:
        resolved_source = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError) as error:
        raise SourceManifestError(
            f"{file_label} file not found: {relative_path}"
        ) from error

    if not resolved_source.is_relative_to(resolved_root):
        raise PathOutsideAllowedRootError(
            f"{file_label} path escapes allowed data root"
        )
    if not resolved_source.is_file():
        raise SourceManifestError(
            f"{file_label} path is not a file: {relative_path}"
        )
    if resolved_source.suffix != expected_suffix:
        if file_label == "source":
            raise UnsupportedDocumentTypeError(
                f"source file must use {expected_suffix}"
            )
        raise SourceManifestError(
            f"{file_label} file must use {expected_suffix}"
        )
    return resolved_source


def _validate_relative_file_path(
    *,
    relative_path: str,
    expected_suffix: str,
    file_label: str,
) -> None:
    if not relative_path or relative_path != relative_path.strip():
        raise PathOutsideAllowedRootError(
            f"{file_label} path must be a non-empty normalized relative path"
        )
    if "\\" in relative_path or ":" in relative_path:
        raise PathOutsideAllowedRootError(
            f"{file_label} path must use safe POSIX relative syntax"
        )
    path = PurePosixPath(relative_path)
    if path.is_absolute():
        raise PathOutsideAllowedRootError(
            f"{file_label} path must be relative"
        )
    if any(part in {"", ".", ".."} for part in relative_path.split("/")):
        raise PathOutsideAllowedRootError(
            f"{file_label} path contains an unsafe segment"
        )
    if path.as_posix() != relative_path:
        raise PathOutsideAllowedRootError(
            f"{file_label} path is not normalized"
        )
    if path.suffix != expected_suffix:
        if file_label == "source":
            raise UnsupportedDocumentTypeError(
                f"source file must use {expected_suffix}"
            )
        raise SourceManifestError(
            f"{file_label} file must use {expected_suffix}"
        )


def make_snapshot_id(*, source_id: str, raw_html_sha256: str) -> UUID:
    identity = f"snapshot|{source_id}|{raw_html_sha256}"
    return uuid5(IDENTITY_NAMESPACE, identity)


def make_manifest_sha256(manifest: SourceManifest) -> str:
    ordered_sources = sorted(
        (
            source.model_dump(mode="json")
            for source in manifest.sources
        ),
        key=lambda source: source["source_id"],
    )
    canonical_manifest = {
        "schema_version": manifest.schema_version,
        "sources": ordered_sources,
    }
    canonical_json = json.dumps(
        canonical_manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()


def make_corpus_id(
    *,
    manifest_sha256: str,
    parser_schema_version: str,
) -> UUID:
    identity = f"corpus|{manifest_sha256}|{parser_schema_version}"
    return uuid5(IDENTITY_NAMESPACE, identity)


def make_block_id(
    block: ParsedContentBlock,
    *,
    snapshot_id: UUID,
    parser_schema_version: str,
) -> UUID:
    clean_text_hash = sha256(block.clean_text.encode("utf-8")).hexdigest()
    identity = "|".join(
        (
            "block",
            str(snapshot_id),
            parser_schema_version,
            str(block.block_order),
            block.block_type.value,
            block.section_anchor,
            block.block_anchor or "",
            clean_text_hash,
        )
    )
    return uuid5(IDENTITY_NAMESPACE, identity)


def make_cleaned_content_sha256(parsed: ParsedDocument) -> str:
    content = {
        "page_title": parsed.page_title,
        "blocks": [
            {
                "block_order": block.block_order,
                "paragraph_order": block.paragraph_order,
                "block_type": block.block_type.value,
                "clean_text": block.clean_text,
                "section_path": list(block.section_path),
                "section_anchor": block.section_anchor,
                "block_anchor": block.block_anchor,
                "list_level": block.list_level,
            }
            for block in parsed.blocks
        ],
    }
    canonical_json = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()


def _bind_block(
    parsed: ParsedContentBlock,
    *,
    snapshot_id: UUID,
    parser_schema_version: str,
) -> ContentBlock:
    return ContentBlock(
        block_id=make_block_id(
            parsed,
            snapshot_id=snapshot_id,
            parser_schema_version=parser_schema_version,
        ),
        snapshot_id=snapshot_id,
        block_order=parsed.block_order,
        paragraph_order=parsed.paragraph_order,
        block_type=parsed.block_type,
        raw_text=parsed.raw_text,
        clean_text=parsed.clean_text,
        section_path=parsed.section_path,
        section_anchor=parsed.section_anchor,
        block_anchor=parsed.block_anchor,
        list_level=parsed.list_level,
    )
