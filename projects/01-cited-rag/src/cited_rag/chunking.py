"""Deterministic section-aware chunk construction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

from cited_rag.errors import ChunkingError
from cited_rag.models import (
    ChunkingConfig,
    ContentBlock,
    ContentBlockType,
    DocumentChunk,
    ImportedDocument,
)

CHUNKING_SCHEMA_VERSION = "chunker-v1"
IDENTITY_NAMESPACE = uuid5(NAMESPACE_URL, "urn:cited-rag:document-identity:v1")
BASELINE_CHUNKING_CONFIG = ChunkingConfig(
    schema_version="1",
    max_characters=520,
    overlap_characters=80,
    block_separator="\n\n",
    minimum_split_characters=260,
    include_section_path=True,
)


@dataclass(frozen=True, slots=True)
class BlockSegment:
    """One exact half-open slice of a ContentBlock."""

    block: ContentBlock
    start_offset: int
    end_offset: int
    text: str
    was_split: bool

    def __post_init__(self) -> None:
        if not 0 <= self.start_offset < self.end_offset <= len(
            self.block.clean_text
        ):
            raise ChunkingError("block segment offsets are invalid")
        if self.text != self.block.clean_text[
            self.start_offset : self.end_offset
        ]:
            raise ChunkingError("block segment text does not match offsets")


def split_block(
    block: ContentBlock,
    *,
    config: ChunkingConfig,
) -> tuple[BlockSegment, ...]:
    """Split one block without changing or losing characters."""

    text = block.clean_text
    if len(text) <= config.max_characters:
        return (
            BlockSegment(
                block=block,
                start_offset=0,
                end_offset=len(text),
                text=text,
                was_split=False,
            ),
        )

    if block.block_type is ContentBlockType.CODE:
        boundaries = _code_boundaries(
            text=text,
            max_characters=config.max_characters,
        )
    else:
        boundaries = _text_boundaries(
            text=text,
            max_characters=config.max_characters,
            minimum_split_characters=config.minimum_split_characters,
        )
    segments = tuple(
        BlockSegment(
            block=block,
            start_offset=start,
            end_offset=end,
            text=text[start:end],
            was_split=True,
        )
        for start, end in boundaries
    )
    _validate_complete_coverage(
        text=text,
        segments=segments,
        max_characters=config.max_characters,
    )
    return segments


class DocumentChunker:
    """Build stable citation chunks from one verified document."""

    def chunk(
        self,
        document: ImportedDocument,
        *,
        config: ChunkingConfig,
    ) -> tuple[DocumentChunk, ...]:
        _validate_block_sequence(document)
        config_sha256 = make_chunk_config_sha256(config)
        segments = tuple(
            segment
            for block in document.blocks
            for segment in split_block(block, config=config)
        )
        segment_groups = _pack_segments(segments=segments, config=config)
        chunks = tuple(
            _bind_chunk(
                document=document,
                segments=group,
                chunk_order=chunk_order,
                config=config,
                config_sha256=config_sha256,
            )
            for chunk_order, group in enumerate(segment_groups, start=1)
        )
        if not chunks:
            raise ChunkingError(
                f"{document.source.source_id}: chunking produced no chunks"
            )
        return chunks


def make_chunk_config_sha256(config: ChunkingConfig) -> str:
    canonical_json = json.dumps(
        config.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()


def make_chunk_id(
    *,
    snapshot_id: UUID,
    config_sha256: str,
    chunk_order: int,
    block_start: int,
    block_start_offset: int,
    block_end: int,
    block_end_offset: int,
    content_sha256: str,
) -> UUID:
    identity = (
        f"chunk|{snapshot_id}|{CHUNKING_SCHEMA_VERSION}|{config_sha256}|"
        f"{chunk_order}|{block_start}:{block_start_offset}|"
        f"{block_end}:{block_end_offset}|{content_sha256}"
    )
    return uuid5(IDENTITY_NAMESPACE, identity)


def _validate_block_sequence(document: ImportedDocument) -> None:
    expected_orders = list(range(1, len(document.blocks) + 1))
    actual_orders = [block.block_order for block in document.blocks]
    if actual_orders != expected_orders:
        raise ChunkingError(
            f"{document.source.source_id}: block_order must be consecutive"
        )


def _pack_segments(
    *,
    segments: tuple[BlockSegment, ...],
    config: ChunkingConfig,
) -> tuple[tuple[BlockSegment, ...], ...]:
    groups: list[tuple[BlockSegment, ...]] = []
    current: list[BlockSegment] = []

    for segment in segments:
        if not current:
            current = [segment]
            continue

        same_section = _section_key(current[0]) == _section_key(segment)
        if same_section and _serialized_length(
            (*current, segment),
            config=config,
        ) <= config.max_characters:
            current.append(segment)
            continue

        groups.append(tuple(current))
        overlap = (
            _select_overlap_suffix(
                previous=current,
                next_segment=segment,
                config=config,
            )
            if same_section
            else []
        )
        current = [*overlap, segment]
        if _serialized_length(current, config=config) > config.max_characters:
            current = [segment]

    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _select_overlap_suffix(
    *,
    previous: list[BlockSegment],
    next_segment: BlockSegment,
    config: ChunkingConfig,
) -> list[BlockSegment]:
    if config.overlap_characters == 0:
        return []

    selected: list[BlockSegment] = []
    for candidate in reversed(previous):
        if candidate.was_split:
            break
        proposed = [candidate, *selected]
        if _serialized_length(proposed, config=config) > (
            config.overlap_characters
        ):
            break
        if _serialized_length(
            (*proposed, next_segment),
            config=config,
        ) > config.max_characters:
            break
        selected = proposed
    return selected


def _section_key(segment: BlockSegment) -> tuple[str, tuple[str, ...]]:
    return (
        segment.block.section_anchor,
        segment.block.section_path,
    )


def _separator_between(
    left: BlockSegment,
    right: BlockSegment,
    *,
    config: ChunkingConfig,
) -> str:
    if (
        left.block.block_order == right.block.block_order
        and left.end_offset == right.start_offset
    ):
        return ""
    return config.block_separator


def _serialize_segments(
    segments: tuple[BlockSegment, ...] | list[BlockSegment],
    *,
    config: ChunkingConfig,
) -> str:
    if not segments:
        return ""
    parts = [segments[0].text]
    for left, right in zip(segments[:-1], segments[1:], strict=True):
        parts.append(_separator_between(left, right, config=config))
        parts.append(right.text)
    return "".join(parts)


def _serialized_length(
    segments: tuple[BlockSegment, ...] | list[BlockSegment],
    *,
    config: ChunkingConfig,
) -> int:
    return len(_serialize_segments(segments, config=config))


def _bind_chunk(
    *,
    document: ImportedDocument,
    segments: tuple[BlockSegment, ...],
    chunk_order: int,
    config: ChunkingConfig,
    config_sha256: str,
) -> DocumentChunk:
    if not segments:
        raise ChunkingError("cannot bind an empty chunk")
    section_key = _section_key(segments[0])
    if any(_section_key(segment) != section_key for segment in segments):
        raise ChunkingError(
            f"{document.source.source_id}: chunk crosses a section boundary"
        )

    text = _serialize_segments(segments, config=config)
    if not text or len(text) > config.max_characters:
        raise ChunkingError(
            f"{document.source.source_id}: chunk length is invalid"
        )
    first = segments[0]
    last = segments[-1]
    paragraphs = [
        segment.block.paragraph_order
        for segment in segments
        if segment.block.paragraph_order is not None
    ]
    paragraph_start = min(paragraphs) if paragraphs else None
    paragraph_end = max(paragraphs) if paragraphs else None
    content_sha256 = sha256(text.encode("utf-8")).hexdigest()
    section_path = first.block.section_path
    embedding_text = (
        f"{' > '.join(section_path)}\n\n{text}"
        if config.include_section_path
        else text
    )
    chunk_id = make_chunk_id(
        snapshot_id=document.snapshot.snapshot_id,
        config_sha256=config_sha256,
        chunk_order=chunk_order,
        block_start=first.block.block_order,
        block_start_offset=first.start_offset,
        block_end=last.block.block_order,
        block_end_offset=last.end_offset,
        content_sha256=content_sha256,
    )
    return DocumentChunk(
        chunk_id=chunk_id,
        snapshot_id=document.snapshot.snapshot_id,
        source_id=document.source.source_id,
        document_key=document.source.document_key,
        python_version=document.source.python_version,
        documentation_release=document.source.documentation_release,
        chunking_schema_version=CHUNKING_SCHEMA_VERSION,
        chunk_config_sha256=config_sha256,
        chunk_order=chunk_order,
        block_start=first.block.block_order,
        block_start_offset=first.start_offset,
        block_end=last.block.block_order,
        block_end_offset=last.end_offset,
        paragraph_start=paragraph_start,
        paragraph_end=paragraph_end,
        text=text,
        embedding_text=embedding_text,
        section_path=section_path,
        section_anchor=first.block.section_anchor,
        source_url=document.source.source_url,
        relative_path=document.source.relative_path,
        content_sha256=content_sha256,
    )


def _code_boundaries(
    *,
    text: str,
    max_characters: int,
) -> tuple[tuple[int, int], ...]:
    boundaries: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        upper = min(start + max_characters, len(text))
        if upper == len(text):
            end = upper
        else:
            newline = text.rfind("\n", start + 1, upper)
            end = newline + 1 if newline >= start else upper
        boundaries.append((start, end))
        start = end
    return tuple(boundaries)


def _text_boundaries(
    *,
    text: str,
    max_characters: int,
    minimum_split_characters: int,
) -> tuple[tuple[int, int], ...]:
    boundaries: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        upper = min(start + max_characters, len(text))
        if upper == len(text):
            end = upper
        else:
            lower = min(start + minimum_split_characters, upper)
            end = (
                _last_newline_boundary(
                    text=text,
                    lower=lower,
                    upper=upper,
                )
                or _last_sentence_boundary(
                    text=text,
                    lower=lower,
                    upper=upper,
                )
                or _last_whitespace_boundary(
                    text=text,
                    lower=lower,
                    upper=upper,
                )
                or upper
            )
        boundaries.append((start, end))
        start = end
    return tuple(boundaries)


def _last_newline_boundary(
    *,
    text: str,
    lower: int,
    upper: int,
) -> int | None:
    newline = text.rfind("\n", lower - 1, upper)
    return newline + 1 if newline >= 0 else None


def _last_sentence_boundary(
    *,
    text: str,
    lower: int,
    upper: int,
) -> int | None:
    candidates: list[int] = []
    for index in range(lower - 1, upper):
        character = text[index]
        boundary = index + 1
        if character in "。！？；":
            candidates.append(_include_following_whitespace(text, boundary, upper))
        elif character in ".!?;":
            if boundary == len(text) or text[boundary].isspace():
                candidates.append(
                    _include_following_whitespace(text, boundary, upper)
                )
    return max(candidates, default=None)


def _include_following_whitespace(
    text: str,
    boundary: int,
    upper: int,
) -> int:
    while boundary < upper and text[boundary].isspace():
        boundary += 1
    return boundary


def _last_whitespace_boundary(
    *,
    text: str,
    lower: int,
    upper: int,
) -> int | None:
    for index in range(upper - 1, lower - 2, -1):
        if text[index].isspace():
            return index + 1
    return None


def _validate_complete_coverage(
    *,
    text: str,
    segments: tuple[BlockSegment, ...],
    max_characters: int,
) -> None:
    if not segments:
        raise ChunkingError("block splitting produced no segments")
    if segments[0].start_offset != 0:
        raise ChunkingError("block segment coverage does not start at zero")
    if segments[-1].end_offset != len(text):
        raise ChunkingError("block segment coverage does not reach text end")
    for index, segment in enumerate(segments):
        if len(segment.text) > max_characters:
            raise ChunkingError("block segment exceeds max_characters")
        if (
            index
            and segments[index - 1].end_offset != segment.start_offset
        ):
            raise ChunkingError("block segment coverage contains a gap")
    if "".join(segment.text for segment in segments) != text:
        raise ChunkingError("block segment text does not reconstruct source")
