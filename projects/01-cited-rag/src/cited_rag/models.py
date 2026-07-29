"""Validated data contracts for document ingestion."""

from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

Identifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitCommitHex = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
PythonVersion = Literal["3.13", "3.14"]
DocumentationRelease = Annotated[
    str,
    Field(pattern=r"^3\.(?:13|14)\.[0-9]+$"),
]


class ContractModel(BaseModel):
    """Common strict behavior for stored ingestion contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_trimmed_non_empty(value: str, *, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    if value != value.strip():
        raise ValueError(f"{field_name} must not have surrounding whitespace")
    return value


def _validate_safe_relative_html_path(value: str) -> str:
    if not value:
        raise ValueError("relative_path must not be empty")
    if value != value.strip():
        raise ValueError("relative_path must not have surrounding whitespace")
    if "\\" in value:
        raise ValueError("relative_path must use '/' separators")
    if ":" in value:
        raise ValueError("relative_path must not contain a drive or URI scheme")

    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError("relative_path must be relative")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("relative_path must not contain empty, '.' or '..' segments")
    if path.as_posix() != value:
        raise ValueError("relative_path must be normalized POSIX syntax")
    if path.suffix != ".html":
        raise ValueError("relative_path must point to a .html file")
    return value


def _validate_safe_relative_json_path(value: str) -> str:
    if not value:
        raise ValueError("manifest_relative_path must not be empty")
    if value != value.strip():
        raise ValueError(
            "manifest_relative_path must not have surrounding whitespace"
        )
    if "\\" in value:
        raise ValueError("manifest_relative_path must use '/' separators")
    if ":" in value:
        raise ValueError(
            "manifest_relative_path must not contain a drive or URI scheme"
        )

    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError("manifest_relative_path must be relative")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(
            "manifest_relative_path must not contain empty, '.' or '..' segments"
        )
    if path.as_posix() != value:
        raise ValueError(
            "manifest_relative_path must be normalized POSIX syntax"
        )
    if path.suffix != ".json":
        raise ValueError("manifest_relative_path must point to a .json file")
    return value


def _validate_python_docs_url(
    value: HttpUrl,
    *,
    python_version: PythonVersion | None = None,
    field_name: str,
) -> HttpUrl:
    if value.scheme != "https":
        raise ValueError(f"{field_name} must use HTTPS")
    if value.host != "docs.python.org":
        raise ValueError(f"{field_name} must use docs.python.org")
    if value.username or value.password or value.port not in {None, 443}:
        raise ValueError(
            f"{field_name} must not contain credentials or a non-default port"
        )
    if value.query or value.fragment:
        raise ValueError(f"{field_name} must not contain a query or fragment")
    if not value.path.endswith(".html"):
        raise ValueError(f"{field_name} must point to an HTML page")
    if python_version and f"/zh-cn/{python_version}/" not in value.path:
        raise ValueError(
            f"{field_name} path must match Python {python_version} simplified Chinese docs"
        )
    return value


class SourceManifestEntry(ContractModel):
    """One approved, versioned source document."""

    schema_version: Literal["1"]
    source_id: Identifier
    document_key: Identifier
    python_version: PythonVersion
    documentation_release: DocumentationRelease
    source_url: HttpUrl
    relative_path: Annotated[str, Field(max_length=512)]
    retrieved_at: AwareDatetime
    expected_title: Annotated[str, Field(max_length=300)]
    license_name: Annotated[str, Field(max_length=200)]
    license_url: HttpUrl
    raw_sha256: Sha256Hex
    media_type: Literal["text/html"]
    language: Literal["zh-CN"]

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return _validate_safe_relative_html_path(value)

    @field_validator("expected_title", "license_name")
    @classmethod
    def validate_required_text(cls, value: str, info) -> str:
        return _require_trimmed_non_empty(value, field_name=info.field_name)

    @field_validator("license_url")
    @classmethod
    def validate_license_url(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("license_url must use HTTPS")
        return value

    @model_validator(mode="after")
    def validate_source_url(self) -> Self:
        if not self.documentation_release.startswith(f"{self.python_version}."):
            raise ValueError(
                "documentation_release must belong to python_version series"
            )
        _validate_python_docs_url(
            self.source_url,
            python_version=self.python_version,
            field_name="source_url",
        )
        return self


class SourceManifest(ContractModel):
    """Atomic set of active source snapshots."""

    schema_version: Literal["1"]
    sources: Annotated[tuple[SourceManifestEntry, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_unique_active_sources(self) -> Self:
        source_ids: set[str] = set()
        active_documents: set[tuple[str, PythonVersion]] = set()
        source_urls: set[str] = set()

        for source in self.sources:
            if source.source_id in source_ids:
                raise ValueError(f"duplicate source_id: {source.source_id}")
            source_ids.add(source.source_id)

            active_key = (source.document_key, source.python_version)
            if active_key in active_documents:
                raise ValueError(
                    "duplicate active document version: "
                    f"{source.document_key} {source.python_version}"
                )
            active_documents.add(active_key)

            normalized_url = str(source.source_url)
            if normalized_url in source_urls:
                raise ValueError(f"duplicate source_url: {normalized_url}")
            source_urls.add(normalized_url)

        return self


class DocumentSnapshot(ContractModel):
    """Verified metadata for one unchanged HTML snapshot."""

    snapshot_id: UUID
    source_id: Identifier
    page_title: Annotated[str, Field(max_length=300)]
    html_canonical_url: HttpUrl | None = None
    raw_html_sha256: Sha256Hex
    cleaned_content_sha256: Sha256Hex
    parser_schema_version: Identifier
    imported_at: AwareDatetime
    warnings: tuple[str, ...] = ()

    @field_validator("page_title")
    @classmethod
    def validate_page_title(cls, value: str) -> str:
        return _require_trimmed_non_empty(value, field_name="page_title")

    @field_validator("html_canonical_url")
    @classmethod
    def validate_canonical_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is None:
            return value
        return _validate_python_docs_url(
            value,
            field_name="html_canonical_url",
        )

    @field_validator("warnings")
    @classmethod
    def validate_warnings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _require_trimmed_non_empty(value, field_name="warning")
        if len(values) != len(set(values)):
            raise ValueError("warnings must not contain duplicates")
        return values


class ContentBlockType(StrEnum):
    """Supported semantic block types after HTML cleaning."""

    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CODE = "code"
    DEFINITION_TERM = "definition_term"
    ADMONITION = "admonition"
    TABLE_ROW = "table_row"
    BLOCKQUOTE = "blockquote"
    IMAGE_ALT = "image_alt"


class ParsedContentBlock(ContractModel):
    """Content block before persistent IDs are assigned."""

    block_order: Annotated[int, Field(ge=1)]
    paragraph_order: Annotated[int, Field(ge=1)] | None = None
    block_type: ContentBlockType
    raw_text: str
    clean_text: str
    section_path: Annotated[tuple[str, ...], Field(min_length=1)]
    section_anchor: str
    block_anchor: str | None = None
    list_level: Annotated[int, Field(ge=1)] | None = None


class ParsedDocument(ContractModel):
    """Deterministic parser output before source metadata is bound."""

    page_title: Annotated[str, Field(min_length=1, max_length=300)]
    html_canonical_url: Annotated[str, Field(min_length=1, max_length=2_048)] | None
    blocks: Annotated[tuple[ParsedContentBlock, ...], Field(min_length=1)]
    warnings: tuple[str, ...] = ()


class ContentBlock(ContractModel):
    """One retained semantic block in document order."""

    block_id: UUID
    snapshot_id: UUID
    block_order: Annotated[int, Field(ge=1)]
    paragraph_order: Annotated[int, Field(ge=1)] | None = None
    block_type: ContentBlockType
    raw_text: str
    clean_text: str
    section_path: Annotated[tuple[str, ...], Field(min_length=1)]
    section_anchor: str
    block_anchor: str | None = None
    list_level: Annotated[int, Field(ge=1)] | None = None

    @field_validator("raw_text", "clean_text")
    @classmethod
    def validate_block_text(cls, value: str, info) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return value

    @field_validator("section_path")
    @classmethod
    def validate_section_path(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _require_trimmed_non_empty(value, field_name="section_path item")
        return values

    @field_validator("section_anchor", "block_anchor")
    @classmethod
    def validate_anchor(cls, value: str | None, info) -> str | None:
        if value is None:
            return value
        return _require_trimmed_non_empty(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_type_specific_fields(self) -> Self:
        if self.block_type is ContentBlockType.PARAGRAPH:
            if self.paragraph_order is None:
                raise ValueError("paragraph blocks require paragraph_order")
        elif self.paragraph_order is not None:
            raise ValueError("paragraph_order is only valid for paragraph blocks")

        if self.block_type is ContentBlockType.LIST_ITEM:
            if self.list_level is None:
                raise ValueError("list_item blocks require list_level")
        elif self.list_level is not None:
            raise ValueError("list_level is only valid for list_item blocks")

        if self.block_type is ContentBlockType.CODE:
            if self.clean_text != self.raw_text:
                raise ValueError("code block clean_text must equal raw_text")
        elif self.clean_text != self.clean_text.strip():
            raise ValueError("non-code clean_text must not have surrounding whitespace")

        return self


class ImportedDocument(ContractModel):
    """One fully verified source snapshot and its bound content blocks."""

    source: SourceManifestEntry
    snapshot: DocumentSnapshot
    blocks: Annotated[tuple[ContentBlock, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_source_binding(self) -> Self:
        if self.snapshot.source_id != self.source.source_id:
            raise ValueError("snapshot source_id must match source manifest entry")
        for block in self.blocks:
            if block.snapshot_id != self.snapshot.snapshot_id:
                raise ValueError("every block must belong to the document snapshot")
        return self


class CorpusImportStatus(StrEnum):
    """Outcome of fully validating a corpus manifest."""

    READY = "ready"
    UNCHANGED = "unchanged"


class ImportedCorpus(ContractModel):
    """Fully validated in-memory corpus before any index write."""

    corpus_id: UUID
    manifest_sha256: Sha256Hex
    parser_schema_version: Identifier
    status: CorpusImportStatus
    manifest: SourceManifest
    documents: Annotated[tuple[ImportedDocument, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_document_set(self) -> Self:
        manifest_ids = sorted(source.source_id for source in self.manifest.sources)
        document_ids = [document.source.source_id for document in self.documents]
        if document_ids != sorted(document_ids):
            raise ValueError("imported documents must be sorted by source_id")
        if document_ids != manifest_ids:
            raise ValueError("imported documents must exactly match manifest sources")
        return self


class ChunkingConfig(ContractModel):
    """Deterministic character-based chunking configuration."""

    schema_version: Literal["1"]
    max_characters: Annotated[int, Field(ge=1)]
    overlap_characters: Annotated[int, Field(ge=0)]
    block_separator: Literal["\n\n"]
    minimum_split_characters: Annotated[int, Field(ge=1)]
    include_section_path: bool

    @model_validator(mode="after")
    def validate_character_limits(self) -> Self:
        if self.overlap_characters >= self.max_characters:
            raise ValueError(
                "overlap_characters must be less than max_characters"
            )
        if self.minimum_split_characters > self.max_characters:
            raise ValueError(
                "minimum_split_characters must not exceed max_characters"
            )
        return self


class DocumentChunk(ContractModel):
    """One citation and embedding unit."""

    chunk_id: UUID
    snapshot_id: UUID
    source_id: Identifier
    document_key: Identifier
    python_version: PythonVersion
    documentation_release: DocumentationRelease
    chunking_schema_version: Identifier
    chunk_config_sha256: Sha256Hex
    chunk_order: Annotated[int, Field(ge=1)]
    block_start: Annotated[int, Field(ge=1)]
    block_start_offset: Annotated[int, Field(ge=0)]
    block_end: Annotated[int, Field(ge=1)]
    block_end_offset: Annotated[int, Field(ge=1)]
    paragraph_start: Annotated[int, Field(ge=1)] | None = None
    paragraph_end: Annotated[int, Field(ge=1)] | None = None
    text: str
    embedding_text: str
    section_path: Annotated[tuple[str, ...], Field(min_length=1)]
    section_anchor: str
    source_url: HttpUrl
    relative_path: Annotated[str, Field(max_length=512)]
    content_sha256: Sha256Hex

    @field_validator("text", "embedding_text")
    @classmethod
    def validate_chunk_text(cls, value: str, info) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return value

    @field_validator("section_path")
    @classmethod
    def validate_section_path(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            _require_trimmed_non_empty(value, field_name="section_path item")
        return values

    @field_validator("section_anchor")
    @classmethod
    def validate_section_anchor(cls, value: str) -> str:
        return _require_trimmed_non_empty(value, field_name="section_anchor")

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        return _validate_safe_relative_html_path(value)

    @model_validator(mode="after")
    def validate_chunk_consistency(self) -> Self:
        if not self.documentation_release.startswith(f"{self.python_version}."):
            raise ValueError(
                "documentation_release must belong to python_version series"
            )
        _validate_python_docs_url(
            self.source_url,
            python_version=self.python_version,
            field_name="source_url",
        )
        if self.block_start > self.block_end:
            raise ValueError("block_start must not exceed block_end")
        if (
            self.block_start == self.block_end
            and self.block_start_offset >= self.block_end_offset
        ):
            raise ValueError(
                "same-block chunk start offset must be less than end offset"
            )

        paragraph_bounds = (self.paragraph_start, self.paragraph_end)
        if (paragraph_bounds[0] is None) != (paragraph_bounds[1] is None):
            raise ValueError(
                "paragraph_start and paragraph_end must both be set or both be null"
            )
        if (
            paragraph_bounds[0] is not None
            and paragraph_bounds[1] is not None
            and paragraph_bounds[0] > paragraph_bounds[1]
        ):
            raise ValueError("paragraph_start must not exceed paragraph_end")

        expected_hash = sha256(self.text.encode("utf-8")).hexdigest()
        if self.content_sha256 != expected_hash:
            raise ValueError("content_sha256 must match UTF-8 text")
        if not self.embedding_text.endswith(self.text):
            raise ValueError("embedding_text must end with citation text")
        return self


class EmbeddingConfig(ContractModel):
    """Pinned local dense-embedding configuration."""

    schema_version: Literal["1"]
    provider: Literal["fastembed"]
    model_name: Literal["BAAI/bge-small-zh-v1.5"]
    resolved_model_source: Literal["Qdrant/bge-small-zh-v1.5"]
    model_revision: GitCommitHex
    model_assets_sha256: Sha256Hex
    model_license: Literal["mit"]
    model_cache_relative_path: Literal["data/models/fastembed"]
    dimension: Literal[512]
    max_input_tokens: Literal[512]
    batch_size: Annotated[int, Field(ge=1, le=256)]
    distance: Literal["cosine"]
    normalize: Literal[True]
    query_instruction: None = None
    passage_instruction: None = None


class IndexSpecification(ContractModel):
    """Deterministic inputs that define one logical vector index."""

    schema_version: Literal["1"]
    corpus_id: UUID
    source_manifest_sha256: Sha256Hex
    parser_schema_version: Identifier
    chunking_schema_version: Identifier
    chunk_config_sha256: Sha256Hex
    chunk_count: Annotated[int, Field(ge=1)]
    embedding_config_sha256: Sha256Hex
    embedding_dimension: Annotated[int, Field(ge=1)]
    distance: Literal["cosine"]
    payload_schema_version: Literal["payload-v1"]


class IndexManifest(ContractModel):
    """One fully validated physical Qdrant index build."""

    schema_version: Literal["1"]
    index_id: UUID
    index_fingerprint: Sha256Hex
    build_id: UUID
    collection_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
            pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        ),
    ]
    built_at: AwareDatetime
    status: Literal["ready"]
    specification: IndexSpecification
    point_count: Annotated[int, Field(ge=1)]
    qdrant_client_version: Annotated[str, Field(min_length=1, max_length=50)]

    @field_validator("qdrant_client_version")
    @classmethod
    def validate_qdrant_client_version(cls, value: str) -> str:
        return _require_trimmed_non_empty(
            value,
            field_name="qdrant_client_version",
        )

    @model_validator(mode="after")
    def validate_point_count(self) -> Self:
        if self.point_count != self.specification.chunk_count:
            raise ValueError(
                "point_count must equal specification chunk_count"
            )
        return self


class ActiveIndexPointer(ContractModel):
    """Small atomically replaced pointer to the active physical index."""

    schema_version: Literal["1"]
    index_id: UUID
    build_id: UUID
    collection_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
            pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        ),
    ]
    manifest_relative_path: Annotated[str, Field(max_length=512)]
    index_fingerprint: Sha256Hex

    @field_validator("manifest_relative_path")
    @classmethod
    def validate_manifest_relative_path(cls, value: str) -> str:
        return _validate_safe_relative_json_path(value)


class ChunkPayload(ContractModel):
    """Traceable Qdrant payload-v1 without model-generated metadata."""

    payload_schema_version: Literal["payload-v1"]
    chunk_id: UUID
    snapshot_id: UUID
    source_id: Identifier
    document_key: Identifier
    python_version: PythonVersion
    documentation_release: DocumentationRelease
    chunk_order: Annotated[int, Field(ge=1)]
    block_start: Annotated[int, Field(ge=1)]
    block_start_offset: Annotated[int, Field(ge=0)]
    block_end: Annotated[int, Field(ge=1)]
    block_end_offset: Annotated[int, Field(ge=1)]
    paragraph_start: Annotated[int, Field(ge=1)] | None = None
    paragraph_end: Annotated[int, Field(ge=1)] | None = None
    text: str
    section_path: Annotated[tuple[str, ...], Field(min_length=1)]
    section_anchor: str
    source_url: HttpUrl
    relative_path: Annotated[str, Field(max_length=512)]
    content_sha256: Sha256Hex
    chunking_schema_version: Identifier
    chunk_config_sha256: Sha256Hex

    @field_validator("text")
    @classmethod
    def validate_payload_text(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("text must not be empty")
        return value

    @field_validator("section_anchor")
    @classmethod
    def validate_payload_section_anchor(cls, value: str) -> str:
        return _require_trimmed_non_empty(
            value,
            field_name="section_anchor",
        )

    @field_validator("section_path")
    @classmethod
    def validate_payload_section_path(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        for value in values:
            _require_trimmed_non_empty(value, field_name="section_path item")
        return values

    @field_validator("relative_path")
    @classmethod
    def validate_payload_relative_path(cls, value: str) -> str:
        return _validate_safe_relative_html_path(value)

    @model_validator(mode="after")
    def validate_payload_consistency(self) -> Self:
        if not self.documentation_release.startswith(f"{self.python_version}."):
            raise ValueError(
                "documentation_release must belong to python_version series"
            )
        _validate_python_docs_url(
            self.source_url,
            python_version=self.python_version,
            field_name="source_url",
        )
        if self.block_start > self.block_end:
            raise ValueError("block_start must not exceed block_end")
        if (
            self.block_start == self.block_end
            and self.block_start_offset >= self.block_end_offset
        ):
            raise ValueError(
                "same-block chunk start offset must be less than end offset"
            )
        if (self.paragraph_start is None) != (self.paragraph_end is None):
            raise ValueError(
                "paragraph_start and paragraph_end must both be set or both be null"
            )
        if (
            self.paragraph_start is not None
            and self.paragraph_end is not None
            and self.paragraph_start > self.paragraph_end
        ):
            raise ValueError("paragraph_start must not exceed paragraph_end")
        if sha256(self.text.encode("utf-8")).hexdigest() != self.content_sha256:
            raise ValueError("content_sha256 must match UTF-8 text")
        return self


class RetrievalQuery(ContractModel):
    """One validated dense-retrieval request."""

    schema_version: Literal["1"] = "1"
    question: Annotated[str, Field(min_length=1, max_length=500)]
    python_version: PythonVersion | None = None
    top_k: Literal[5] = 5

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        return _require_trimmed_non_empty(value, field_name="question")


class RetrievalConfig(ContractModel):
    """Fixed query-time ranking behavior, separate from index identity."""

    schema_version: Literal["1"]
    mode: Literal["dense", "dense-plus-identifiers"]
    top_k: Literal[5]
    remove_filtered_version_terms: bool
    identifier_result_limit: Annotated[int, Field(ge=0, le=2)]

    @model_validator(mode="after")
    def validate_mode_fields(self) -> Self:
        if self.mode == "dense":
            if self.remove_filtered_version_terms:
                raise ValueError(
                    "dense baseline must preserve the original question"
                )
            if self.identifier_result_limit != 0:
                raise ValueError(
                    "dense baseline must not reserve identifier results"
                )
        elif (
            not self.remove_filtered_version_terms
            or self.identifier_result_limit == 0
        ):
            raise ValueError(
                "dense-plus-identifiers requires normalization and a result lane"
            )
        return self


class RetrievedChunk(ContractModel):
    """One ranked, traceable result from the active index."""

    rank: Annotated[int, Field(ge=1, le=5)]
    score: Annotated[float, Field(ge=-1.000001, le=1.000001)]
    payload: ChunkPayload
    citation_url: HttpUrl
    retrieval_reason: Literal["dense", "identifier"]

    @model_validator(mode="after")
    def validate_citation_url(self) -> Self:
        expected = f"{self.payload.source_url}#{self.payload.section_anchor}"
        if str(self.citation_url) != expected:
            raise ValueError(
                "citation_url must use payload source_url and section_anchor"
            )
        return self


class RetrievalResult(ContractModel):
    """Ordered results tied to one immutable active-index build."""

    schema_version: Literal["1"] = "1"
    query: RetrievalQuery
    retrieval_config: RetrievalConfig
    index_id: UUID
    build_id: UUID
    collection_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=120,
            pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        ),
    ]
    results: Annotated[tuple[RetrievedChunk, ...], Field(max_length=5)]

    @model_validator(mode="after")
    def validate_result_set(self) -> Self:
        if self.query.top_k != self.retrieval_config.top_k:
            raise ValueError(
                "query top_k must match retrieval configuration"
            )
        if len(self.results) > self.retrieval_config.top_k:
            raise ValueError("retrieval result count exceeds configured top_k")
        ranks = [result.rank for result in self.results]
        if ranks != list(range(1, len(self.results) + 1)):
            raise ValueError("retrieval result ranks must be contiguous")
        chunk_ids = [result.payload.chunk_id for result in self.results]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("retrieval results must not repeat chunk_id")
        if self.query.python_version is not None and any(
            result.payload.python_version != self.query.python_version
            for result in self.results
        ):
            raise ValueError(
                "retrieval result does not match python_version filter"
            )
        return self


class ModelAnswer(ContractModel):
    """Untrusted structured answer selected by the generation model."""

    schema_version: Literal["1"] = "1"
    status: Literal["answered", "refused", "conflict"]
    answer: Annotated[str, Field(max_length=4000)] = ""
    citation_ids: Annotated[
        tuple[UUID, ...],
        Field(max_length=5),
    ] = ()

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, value: str) -> str:
        if value and value != value.strip():
            raise ValueError("answer must not have surrounding whitespace")
        return value

    @model_validator(mode="after")
    def validate_status_and_citations(self) -> Self:
        if len(self.citation_ids) != len(set(self.citation_ids)):
            raise ValueError("citation_ids must be unique")
        if self.status == "refused" and self.citation_ids:
            raise ValueError("refused output must not contain citation_ids")
        if self.status != "refused" and not self.answer:
            raise ValueError(
                "answered or conflict output must contain answer text"
            )
        if self.status == "answered" and not self.citation_ids:
            raise ValueError("answered output must contain citation_ids")
        if self.status == "conflict" and len(self.citation_ids) < 2:
            raise ValueError(
                "conflict output must contain at least two citation_ids"
            )
        return self


class AnswerCitation(ContractModel):
    """Program-bound citation copied from one retrieved Chunk payload."""

    rank: Annotated[int, Field(ge=1, le=5)]
    chunk_id: UUID
    python_version: PythonVersion
    documentation_release: DocumentationRelease
    section_path: Annotated[tuple[str, ...], Field(min_length=1)]
    citation_url: HttpUrl
    excerpt: Annotated[str, Field(min_length=1, max_length=520)]


class AnswerResult(ContractModel):
    """Validated public answer without model-generated source metadata."""

    schema_version: Literal["1"] = "1"
    question: Annotated[str, Field(min_length=1, max_length=500)]
    status: Literal["answered", "refused", "conflict"]
    answer: Annotated[str, Field(min_length=1, max_length=4000)]
    citations: Annotated[tuple[AnswerCitation, ...], Field(max_length=5)]
    index_id: UUID
    build_id: UUID
    prompt_tokens: Annotated[int, Field(ge=0)] | None = None
    completion_tokens: Annotated[int, Field(ge=0)] | None = None
    total_tokens: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def validate_public_answer(self) -> Self:
        _require_trimmed_non_empty(self.question, field_name="question")
        _require_trimmed_non_empty(self.answer, field_name="answer")
        chunk_ids = [citation.chunk_id for citation in self.citations]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("answer citations must be unique")
        if self.status == "refused" and self.citations:
            raise ValueError("refused answer must not contain citations")
        if self.status == "answered" and not self.citations:
            raise ValueError("answered result must contain citations")
        if self.status == "conflict" and len(self.citations) < 2:
            raise ValueError(
                "conflict result must contain at least two citations"
            )
        return self


class AnswerEvaluationCase(ContractModel):
    """One locked end-to-end answer or refusal expectation."""

    case_id: Identifier
    question: Annotated[str, Field(min_length=1, max_length=500)]
    python_version: PythonVersion
    expected_status: Literal["answered", "refused"]

    @field_validator("question")
    @classmethod
    def validate_evaluation_question(cls, value: str) -> str:
        return _require_trimmed_non_empty(value, field_name="question")


class AnswerEvaluationSet(ContractModel):
    """Independent set that must remain fixed during one model baseline."""

    schema_version: Literal["1"]
    evaluation_set_id: Identifier
    index_fingerprint: Sha256Hex
    minimum_class_target: Annotated[float, Field(gt=0, le=1)]
    cases: Annotated[tuple[AnswerEvaluationCase, ...], Field(min_length=10)]

    @model_validator(mode="after")
    def validate_evaluation_cases(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("answer evaluation case_id values must be unique")
        answered = sum(
            case.expected_status == "answered" for case in self.cases
        )
        refused = sum(
            case.expected_status == "refused" for case in self.cases
        )
        if answered < 5 or refused < 5:
            raise ValueError(
                "answer evaluation requires at least five cases per class"
            )
        return self


class AnswerEvaluationCaseResult(ContractModel):
    """Observed validated answer or one stable failure."""

    case_id: Identifier
    expected_status: Literal["answered", "refused"]
    observed_status: Literal["answered", "refused", "conflict"] | None
    correct: bool
    answer: AnswerResult | None
    error_code: str | None
    error_reason: str | None
    prompt_tokens: Annotated[int, Field(ge=0)] | None = None
    completion_tokens: Annotated[int, Field(ge=0)] | None = None
    total_tokens: Annotated[int, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def validate_case_result(self) -> Self:
        has_answer = self.answer is not None
        has_error = self.error_code is not None or self.error_reason is not None
        if has_answer == has_error:
            raise ValueError(
                "case result must contain exactly one answer or error"
            )
        if has_error and (
            self.error_code is None or self.error_reason is None
        ):
            raise ValueError("error_code and error_reason must both be set")
        expected_observed = self.answer.status if self.answer else None
        if self.observed_status != expected_observed:
            raise ValueError("observed_status must match answer status")
        if self.correct != (
            self.observed_status == self.expected_status
        ):
            raise ValueError("correct must match expected and observed status")
        usage = (
            self.prompt_tokens,
            self.completion_tokens,
            self.total_tokens,
        )
        if any(value is None for value in usage) and any(
            value is not None for value in usage
        ):
            raise ValueError("case token usage must be complete or absent")
        if (
            self.total_tokens is not None
            and self.total_tokens
            != (self.prompt_tokens or 0) + (self.completion_tokens or 0)
        ):
            raise ValueError("case total_tokens must match token parts")
        if (
            self.answer is not None
            and self.total_tokens is not None
            and usage
            != (
                self.answer.prompt_tokens,
                self.answer.completion_tokens,
                self.answer.total_tokens,
            )
        ):
            raise ValueError("case token usage must match answer usage")
        return self


class AnswerEvaluationReport(ContractModel):
    """End-to-end MiMo baseline with class metrics and token evidence."""

    schema_version: Literal["1"]
    evaluation_set_id: Identifier
    evaluation_set_sha256: Sha256Hex
    generated_at: AwareDatetime
    index_id: UUID
    build_id: UUID
    model_provider: Literal["mimo"]
    model_name: Literal["mimo-v2.5"]
    api_call_count: Annotated[int, Field(ge=0)]
    usage_response_count: Annotated[int, Field(ge=0)]
    usage_complete: bool
    automatic_retries: Literal[0]
    authorized_cny_limit: Literal[5]
    prompt_tokens: Annotated[int, Field(ge=0)]
    completion_tokens: Annotated[int, Field(ge=0)]
    total_tokens: Annotated[int, Field(ge=0)]
    answerable_recall: Annotated[float, Field(ge=0, le=1)]
    refusal_accuracy: Annotated[float, Field(ge=0, le=1)]
    citation_binding_validity: Annotated[float, Field(ge=0, le=1)]
    minimum_class_target: Annotated[float, Field(gt=0, le=1)]
    target_met: bool
    cases: Annotated[
        tuple[AnswerEvaluationCaseResult, ...],
        Field(min_length=10),
    ]

    @model_validator(mode="after")
    def validate_answer_metrics(self) -> Self:
        answer_cases = [
            case
            for case in self.cases
            if case.expected_status == "answered"
        ]
        refusal_cases = [
            case
            for case in self.cases
            if case.expected_status == "refused"
        ]
        observed_answer_recall = (
            sum(case.correct for case in answer_cases) / len(answer_cases)
        )
        observed_refusal_accuracy = (
            sum(case.correct for case in refusal_cases) / len(refusal_cases)
        )
        returned_answers = [
            case.answer
            for case in self.cases
            if case.answer is not None
            and case.answer.status in {"answered", "conflict"}
        ]
        valid_citations = sum(
            bool(answer.citations) for answer in returned_answers
        )
        observed_binding_validity = (
            valid_citations / len(returned_answers)
            if returned_answers
            else 1.0
        )
        if (
            abs(self.answerable_recall - observed_answer_recall) > 1e-12
            or abs(
                self.refusal_accuracy - observed_refusal_accuracy
            ) > 1e-12
            or abs(
                self.citation_binding_validity
                - observed_binding_validity
            )
            > 1e-12
        ):
            raise ValueError("answer evaluation metrics must match cases")
        expected_target = (
            self.answerable_recall >= self.minimum_class_target
            and self.refusal_accuracy >= self.minimum_class_target
            and self.citation_binding_validity == 1.0
        )
        if self.target_met != expected_target:
            raise ValueError("target_met must match answer metrics")
        if self.total_tokens != (
            self.prompt_tokens + self.completion_tokens
        ):
            raise ValueError("total_tokens must match prompt plus completion")
        observed_usage_count = sum(
            (
                case.total_tokens
                if case.total_tokens is not None
                else (
                    case.answer.total_tokens
                    if case.answer is not None
                    else None
                )
            )
            is not None
            for case in self.cases
        )
        if self.usage_response_count != observed_usage_count:
            raise ValueError("usage_response_count must match cases")
        if self.usage_complete != (
            self.usage_response_count == self.api_call_count
        ):
            raise ValueError("usage_complete must match API and usage counts")
        return self


class RetrievalEvaluationCase(ContractModel):
    """One manually reviewable retrieval question and accepted evidence."""

    case_id: Identifier
    question: Annotated[str, Field(min_length=1, max_length=500)]
    python_version: PythonVersion | None = None
    relevant_chunk_ids: Annotated[tuple[UUID, ...], Field(min_length=1)]
    rationale: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("question", "rationale")
    @classmethod
    def validate_evaluation_text(cls, value: str, info) -> str:
        return _require_trimmed_non_empty(value, field_name=info.field_name)

    @field_validator("relevant_chunk_ids")
    @classmethod
    def validate_relevant_chunk_ids(
        cls,
        values: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        if len(values) != len(set(values)):
            raise ValueError("relevant_chunk_ids must not contain duplicates")
        return values


class RetrievalEvaluationSet(ContractModel):
    """Fixed Recall@5 set bound to one logical index fingerprint."""

    schema_version: Literal["1"]
    evaluation_set_id: Identifier
    index_fingerprint: Sha256Hex
    top_k: Literal[5]
    authoring_method: Literal["manual-from-verified-corpus"]
    cases: Annotated[
        tuple[RetrievalEvaluationCase, ...],
        Field(min_length=10),
    ]

    @model_validator(mode="after")
    def validate_unique_cases(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation cases must have unique case_id")
        return self


class RetrievalEvaluationObservation(ContractModel):
    """Small ranked record retained in an evaluation report."""

    rank: Annotated[int, Field(ge=1, le=5)]
    score: Annotated[float, Field(ge=-1.000001, le=1.000001)]
    chunk_id: UUID
    source_id: Identifier
    python_version: PythonVersion
    section_anchor: Annotated[str, Field(min_length=1, max_length=500)]
    retrieval_reason: Literal["dense", "identifier"]

    @field_validator("section_anchor")
    @classmethod
    def validate_observation_anchor(cls, value: str) -> str:
        return _require_trimmed_non_empty(
            value,
            field_name="section_anchor",
        )


class RetrievalEvaluationCaseResult(ContractModel):
    """Recall@5 outcome for one fixed question."""

    case_id: Identifier
    question: Annotated[str, Field(min_length=1, max_length=500)]
    python_version: PythonVersion | None = None
    relevant_chunk_ids: Annotated[tuple[UUID, ...], Field(min_length=1)]
    retrieved: Annotated[
        tuple[RetrievalEvaluationObservation, ...],
        Field(max_length=5),
    ]
    hit: bool
    first_relevant_rank: Annotated[int, Field(ge=1, le=5)] | None = None
    error_code: Annotated[
        str,
        Field(pattern=r"^[A-Z][A-Z0-9_]+$"),
    ] | None = None
    error_reason: Annotated[str, Field(min_length=1, max_length=500)] | None = None

    @model_validator(mode="after")
    def validate_case_outcome(self) -> Self:
        if (self.error_code is None) != (self.error_reason is None):
            raise ValueError(
                "error_code and error_reason must both be set or both be null"
            )
        if self.error_code is not None:
            if self.retrieved or self.hit or self.first_relevant_rank is not None:
                raise ValueError(
                    "failed evaluation case must not contain retrieval results"
                )
            return self

        ranks = [item.rank for item in self.retrieved]
        if ranks != list(range(1, len(self.retrieved) + 1)):
            raise ValueError("evaluation result ranks must be contiguous")
        relevant = set(self.relevant_chunk_ids)
        observed_rank = next(
            (
                item.rank
                for item in self.retrieved
                if item.chunk_id in relevant
            ),
            None,
        )
        if self.first_relevant_rank != observed_rank:
            raise ValueError(
                "first_relevant_rank must match retrieved evidence"
            )
        if self.hit != (observed_rank is not None):
            raise ValueError("hit must match retrieved evidence")
        return self


class RetrievalEvaluationReport(ContractModel):
    """Auditable aggregate result for one fixed Recall@5 run."""

    schema_version: Literal["1"]
    evaluation_set_id: Identifier
    evaluation_set_sha256: Sha256Hex
    generated_at: AwareDatetime
    index_id: UUID
    build_id: UUID
    index_fingerprint: Sha256Hex
    top_k: Literal[5]
    retrieval_config: RetrievalConfig
    case_count: Annotated[int, Field(ge=1)]
    hit_count: Annotated[int, Field(ge=0)]
    recall_at_5: Annotated[float, Field(ge=0, le=1)]
    target_recall_at_5: Literal[0.8]
    target_met: bool
    cases: Annotated[
        tuple[RetrievalEvaluationCaseResult, ...],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def validate_aggregate(self) -> Self:
        if self.top_k != self.retrieval_config.top_k:
            raise ValueError(
                "report top_k must match retrieval configuration"
            )
        if self.case_count != len(self.cases):
            raise ValueError("case_count must equal cases length")
        observed_hits = sum(case.hit for case in self.cases)
        if self.hit_count != observed_hits:
            raise ValueError("hit_count must equal case hit total")
        expected_recall = self.hit_count / self.case_count
        if abs(self.recall_at_5 - expected_recall) > 1e-12:
            raise ValueError("recall_at_5 must equal hit_count / case_count")
        if self.target_met != (
            self.recall_at_5 >= self.target_recall_at_5
        ):
            raise ValueError("target_met must match recall threshold")
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("report cases must have unique case_id")
        return self


class EvidenceCalibrationCase(ContractModel):
    """One independently authored score-calibration question."""

    case_id: Identifier
    question: Annotated[str, Field(min_length=1, max_length=500)]
    python_version: PythonVersion | None = None
    expected_decision: Literal["answer", "refuse"]
    case_kind: Literal[
        "answerable",
        "missing-corpus",
        "third-party",
        "other-language",
        "nonsense",
        "prompt-injection",
    ]
    expected_source_ids: tuple[Identifier, ...]
    rationale: Annotated[str, Field(min_length=1, max_length=500)]

    @field_validator("question", "rationale")
    @classmethod
    def validate_calibration_text(cls, value: str, info) -> str:
        return _require_trimmed_non_empty(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_expected_evidence(self) -> Self:
        if len(self.expected_source_ids) != len(set(self.expected_source_ids)):
            raise ValueError("expected_source_ids must not contain duplicates")
        if self.expected_decision == "answer":
            if self.case_kind != "answerable":
                raise ValueError(
                    "answer decision requires answerable case_kind"
                )
            if not self.expected_source_ids:
                raise ValueError(
                    "answer decision requires expected_source_ids"
                )
        elif self.case_kind == "answerable" or self.expected_source_ids:
            raise ValueError(
                "refuse decision must not claim expected corpus evidence"
            )
        return self


class EvidenceCalibrationSet(ContractModel):
    """Independent binary set used only to select a score threshold."""

    schema_version: Literal["1"]
    calibration_set_id: Identifier
    index_fingerprint: Sha256Hex
    retrieval_config: RetrievalConfig
    authoring_method: Literal["manual-from-corpus-boundary"]
    cases: Annotated[
        tuple[EvidenceCalibrationCase, ...],
        Field(min_length=20),
    ]

    @model_validator(mode="after")
    def validate_calibration_balance(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("calibration cases must have unique case_id")
        answer_count = sum(
            case.expected_decision == "answer" for case in self.cases
        )
        refusal_count = len(self.cases) - answer_count
        if answer_count < 10 or refusal_count < 10:
            raise ValueError(
                "calibration set requires at least 10 cases per decision"
            )
        return self


class EvidenceScoreObservation(ContractModel):
    """One retrieval score observation before selecting a threshold."""

    case_id: Identifier
    expected_decision: Literal["answer", "refuse"]
    case_kind: str
    max_score: Annotated[float, Field(ge=-1.000001, le=1.000001)] | None
    max_score_rank: Annotated[int, Field(ge=1, le=5)] | None
    max_score_chunk_id: UUID | None
    max_score_source_id: Identifier | None
    max_score_retrieval_reason: Literal["dense", "identifier"] | None
    result_count: Annotated[int, Field(ge=0, le=5)]
    error_code: Annotated[
        str,
        Field(pattern=r"^[A-Z][A-Z0-9_]+$"),
    ] | None = None

    @model_validator(mode="after")
    def validate_score_binding(self) -> Self:
        score_fields = (
            self.max_score,
            self.max_score_rank,
            self.max_score_chunk_id,
            self.max_score_source_id,
            self.max_score_retrieval_reason,
        )
        if any(value is None for value in score_fields) != all(
            value is None for value in score_fields
        ):
            raise ValueError("max score fields must be all set or all null")
        if self.error_code is not None and (
            self.result_count != 0 or self.max_score is not None
        ):
            raise ValueError(
                "failed score observation must not contain results"
            )
        if self.error_code is None and (
            (self.result_count == 0) != (self.max_score is None)
        ):
            raise ValueError(
                "max score presence must match result_count"
            )
        return self


class EvidenceThresholdCaseResult(ContractModel):
    """One calibrated binary evidence decision."""

    observation: EvidenceScoreObservation
    predicted_decision: Literal["answer", "refuse"]
    correct: bool

    @model_validator(mode="after")
    def validate_threshold_outcome(self) -> Self:
        if self.correct != (
            self.predicted_decision
            == self.observation.expected_decision
        ):
            raise ValueError(
                "correct must compare predicted and expected decisions"
            )
        return self


class EvidenceThresholdCalibrationReport(ContractModel):
    """Selected threshold and class-specific calibration evidence."""

    schema_version: Literal["1"]
    calibration_set_id: Identifier
    calibration_set_sha256: Sha256Hex
    generated_at: AwareDatetime
    index_id: UUID
    build_id: UUID
    index_fingerprint: Sha256Hex
    retrieval_config: RetrievalConfig
    score_definition: Literal["maximum-cosine-among-returned-results"]
    decision_rule: Literal["answer-if-score-gte-threshold"]
    selected_threshold: Annotated[
        float,
        Field(ge=-1.000001, le=1.000001),
    ]
    answerable_count: Annotated[int, Field(ge=1)]
    refusal_count: Annotated[int, Field(ge=1)]
    answerable_recall: Annotated[float, Field(ge=0, le=1)]
    refusal_accuracy: Annotated[float, Field(ge=0, le=1)]
    balanced_accuracy: Annotated[float, Field(ge=0, le=1)]
    minimum_class_target: Literal[0.8]
    target_met: bool
    cases: Annotated[
        tuple[EvidenceThresholdCaseResult, ...],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def validate_threshold_metrics(self) -> Self:
        answer_cases = [
            case
            for case in self.cases
            if case.observation.expected_decision == "answer"
        ]
        refusal_cases = [
            case
            for case in self.cases
            if case.observation.expected_decision == "refuse"
        ]
        if (
            self.answerable_count != len(answer_cases)
            or self.refusal_count != len(refusal_cases)
        ):
            raise ValueError("class counts must match cases")
        observed_answer_recall = (
            sum(case.correct for case in answer_cases) / len(answer_cases)
        )
        observed_refusal_accuracy = (
            sum(case.correct for case in refusal_cases) / len(refusal_cases)
        )
        observed_balanced = (
            observed_answer_recall + observed_refusal_accuracy
        ) / 2
        if (
            abs(self.answerable_recall - observed_answer_recall) > 1e-12
            or abs(self.refusal_accuracy - observed_refusal_accuracy) > 1e-12
            or abs(self.balanced_accuracy - observed_balanced) > 1e-12
        ):
            raise ValueError("calibration metrics must match case outcomes")
        if self.target_met != (
            self.answerable_recall >= self.minimum_class_target
            and self.refusal_accuracy >= self.minimum_class_target
        ):
            raise ValueError("target_met must match both class targets")
        return self


class EvidencePolicy(ContractModel):
    """Pinned score policy selected from an independent calibration set."""

    schema_version: Literal["1"]
    policy_id: Identifier
    index_id: UUID
    retrieval_config: RetrievalConfig
    calibration_set_id: Identifier
    calibration_set_sha256: Sha256Hex
    score_definition: Literal["maximum-cosine-among-returned-results"]
    threshold: Annotated[
        float,
        Field(ge=-1.000001, le=1.000001),
    ]


class EvidenceAssessment(ContractModel):
    """Evidence sufficiency result bound to the exact retrieved chunks."""

    schema_version: Literal["1"] = "1"
    policy: EvidencePolicy
    retrieval: RetrievalResult
    decision: Literal["sufficient", "insufficient"]
    reason: Literal[
        "score-at-or-above-threshold",
        "score-below-threshold",
        "no-results",
    ]
    max_score: Annotated[float, Field(ge=-1.000001, le=1.000001)] | None
    max_score_rank: Annotated[int, Field(ge=1, le=5)] | None
    max_score_chunk_id: UUID | None

    @model_validator(mode="after")
    def validate_evidence_decision(self) -> Self:
        if self.policy.index_id != self.retrieval.index_id:
            raise ValueError("evidence policy does not match retrieval index")
        if self.policy.retrieval_config != self.retrieval.retrieval_config:
            raise ValueError(
                "evidence policy does not match retrieval configuration"
            )
        maximum = max(
            self.retrieval.results,
            key=lambda item: (item.score, -item.rank),
            default=None,
        )
        expected_score = maximum.score if maximum else None
        expected_rank = maximum.rank if maximum else None
        expected_chunk = maximum.payload.chunk_id if maximum else None
        if (
            self.max_score != expected_score
            or self.max_score_rank != expected_rank
            or self.max_score_chunk_id != expected_chunk
        ):
            raise ValueError(
                "max score fields must match retrieved results"
            )
        if maximum is None:
            expected_decision = "insufficient"
            expected_reason = "no-results"
        elif maximum.score >= self.policy.threshold:
            expected_decision = "sufficient"
            expected_reason = "score-at-or-above-threshold"
        else:
            expected_decision = "insufficient"
            expected_reason = "score-below-threshold"
        if (
            self.decision != expected_decision
            or self.reason != expected_reason
        ):
            raise ValueError(
                "evidence decision must match calibrated score rule"
            )
        return self


class EvidenceEvaluationSet(ContractModel):
    """Held-out binary set that must not be used to tune the policy."""

    schema_version: Literal["1"]
    evaluation_set_id: Identifier
    index_fingerprint: Sha256Hex
    policy_id: Identifier
    authoring_method: Literal["held-out-manual-corpus-boundary"]
    cases: Annotated[
        tuple[EvidenceCalibrationCase, ...],
        Field(min_length=10),
    ]

    @model_validator(mode="after")
    def validate_evaluation_balance(self) -> Self:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evidence evaluation cases must be unique")
        answer_count = sum(
            case.expected_decision == "answer" for case in self.cases
        )
        refusal_count = len(self.cases) - answer_count
        if answer_count < 5 or refusal_count < 5:
            raise ValueError(
                "evidence evaluation requires at least 5 cases per decision"
            )
        return self


class EvidencePolicyEvaluationReport(ContractModel):
    """Held-out evidence-gate metrics for one pinned policy."""

    schema_version: Literal["1"]
    evaluation_set_id: Identifier
    evaluation_set_sha256: Sha256Hex
    generated_at: AwareDatetime
    policy: EvidencePolicy
    index_fingerprint: Sha256Hex
    answerable_count: Annotated[int, Field(ge=1)]
    refusal_count: Annotated[int, Field(ge=1)]
    answerable_recall: Annotated[float, Field(ge=0, le=1)]
    refusal_accuracy: Annotated[float, Field(ge=0, le=1)]
    balanced_accuracy: Annotated[float, Field(ge=0, le=1)]
    minimum_class_target: Literal[0.8]
    target_met: bool
    cases: Annotated[
        tuple[EvidenceThresholdCaseResult, ...],
        Field(min_length=1),
    ]

    @model_validator(mode="after")
    def validate_evaluation_metrics(self) -> Self:
        answer_cases = [
            case
            for case in self.cases
            if case.observation.expected_decision == "answer"
        ]
        refusal_cases = [
            case
            for case in self.cases
            if case.observation.expected_decision == "refuse"
        ]
        if (
            self.answerable_count != len(answer_cases)
            or self.refusal_count != len(refusal_cases)
        ):
            raise ValueError("evaluation class counts must match cases")
        answer_recall = (
            sum(case.correct for case in answer_cases) / len(answer_cases)
        )
        refusal_accuracy = (
            sum(case.correct for case in refusal_cases) / len(refusal_cases)
        )
        balanced = (answer_recall + refusal_accuracy) / 2
        if (
            abs(self.answerable_recall - answer_recall) > 1e-12
            or abs(self.refusal_accuracy - refusal_accuracy) > 1e-12
            or abs(self.balanced_accuracy - balanced) > 1e-12
        ):
            raise ValueError("evidence evaluation metrics are invalid")
        if self.target_met != (
            answer_recall >= self.minimum_class_target
            and refusal_accuracy >= self.minimum_class_target
        ):
            raise ValueError("evaluation target_met is invalid")
        return self
