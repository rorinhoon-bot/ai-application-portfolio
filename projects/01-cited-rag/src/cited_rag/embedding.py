"""Provider-independent embedding validation without model loading."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import fsum, isfinite, sqrt
from numbers import Integral
from struct import Struct
from typing import Protocol
from uuid import UUID

from cited_rag.errors import (
    EmbeddingError,
    EmbeddingInputTooLongError,
    VectorDimensionMismatchError,
    VectorValueInvalidError,
)
from cited_rag.models import DocumentChunk, EmbeddingConfig

_FLOAT32 = Struct("!f")


class EmbeddingProvider(Protocol):
    """Minimal ordered dense-vector provider."""

    def embed_passages(
        self,
        texts: Sequence[str],
        *,
        batch_size: int,
    ) -> Iterable[Sequence[float]]:
        """Return one vector per text in input order."""

    def embed_query(self, text: str) -> Sequence[float]:
        """Return one vector for a query."""


class TokenCounter(Protocol):
    """Counts tokens without truncating the input."""

    def count_tokens(self, text: str) -> int:
        """Return the full token count, including special tokens."""


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """One positional binding between a trusted Chunk ID and vector."""

    chunk_id: UUID
    vector: tuple[float, ...]


class EmbeddingService:
    """Preflight, batch and validate embedding output."""

    def __init__(
        self,
        *,
        provider: EmbeddingProvider,
        token_counter: TokenCounter,
        dimension: int,
        max_input_tokens: int,
        batch_size: int,
        normalize: bool = True,
    ) -> None:
        if dimension < 1:
            raise ValueError("dimension must be positive")
        if max_input_tokens < 1:
            raise ValueError("max_input_tokens must be positive")
        if not 1 <= batch_size <= 256:
            raise ValueError("batch_size must be between 1 and 256")
        if not normalize:
            raise ValueError("normalize must be true")
        self._provider = provider
        self._token_counter = token_counter
        self._dimension = dimension
        self._max_input_tokens = max_input_tokens
        self._batch_size = batch_size

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @classmethod
    def from_config(
        cls,
        *,
        provider: EmbeddingProvider,
        token_counter: TokenCounter,
        config: EmbeddingConfig,
    ) -> EmbeddingService:
        """Build the runtime service from the pinned production contract."""

        return cls(
            provider=provider,
            token_counter=token_counter,
            dimension=config.dimension,
            max_input_tokens=config.max_input_tokens,
            batch_size=config.batch_size,
            normalize=config.normalize,
        )

    def embed_chunks(
        self,
        chunks: Iterable[DocumentChunk],
    ) -> tuple[EmbeddedChunk, ...]:
        """Embed all chunks only after the complete token preflight passes."""

        ordered_chunks = tuple(
            sorted(
                chunks,
                key=lambda chunk: (chunk.source_id, chunk.chunk_order),
            )
        )
        if not ordered_chunks:
            raise EmbeddingError("no chunks were provided")
        self._validate_unique_chunks(ordered_chunks)
        for chunk in ordered_chunks:
            self._validate_text(
                chunk.embedding_text,
                item_id=str(chunk.chunk_id),
            )

        embedded: list[EmbeddedChunk] = []
        for start in range(0, len(ordered_chunks), self._batch_size):
            batch = ordered_chunks[start : start + self._batch_size]
            texts = tuple(chunk.embedding_text for chunk in batch)
            batch_number = start // self._batch_size + 1
            try:
                output = tuple(
                    self._provider.embed_passages(
                        texts,
                        batch_size=self._batch_size,
                    )
                )
            except Exception as error:
                raise EmbeddingError(
                    f"provider failed for batch {batch_number}"
                ) from error
            if len(output) != len(batch):
                raise EmbeddingError(
                    f"provider count mismatch for batch {batch_number}"
                )
            for chunk, vector in zip(batch, output, strict=True):
                embedded.append(
                    EmbeddedChunk(
                        chunk_id=chunk.chunk_id,
                        vector=self._normalize_vector(
                            vector,
                            item_id=str(chunk.chunk_id),
                        ),
                    )
                )
        return tuple(embedded)

    def embed_query(self, text: str) -> tuple[float, ...]:
        """Embed one query after applying the same input and vector checks."""

        self._validate_text(text, item_id="query")
        try:
            vector = self._provider.embed_query(text)
        except Exception as error:
            raise EmbeddingError("provider failed for query") from error
        return self._normalize_vector(vector, item_id="query")

    @staticmethod
    def _validate_unique_chunks(chunks: tuple[DocumentChunk, ...]) -> None:
        chunk_ids: set[UUID] = set()
        positions: set[tuple[str, int]] = set()
        for chunk in chunks:
            if chunk.chunk_id in chunk_ids:
                raise EmbeddingError(f"duplicate chunk_id: {chunk.chunk_id}")
            chunk_ids.add(chunk.chunk_id)
            position = (chunk.source_id, chunk.chunk_order)
            if position in positions:
                raise EmbeddingError(
                    "duplicate source_id and chunk_order position"
                )
            positions.add(position)

    def _validate_text(self, text: str, *, item_id: str) -> None:
        if not text or not text.strip():
            raise EmbeddingError(f"embedding input is empty: {item_id}")
        try:
            token_count = self._token_counter.count_tokens(text)
        except Exception as error:
            raise EmbeddingError(
                f"token counting failed: {item_id}"
            ) from error
        if (
            isinstance(token_count, bool)
            or not isinstance(token_count, Integral)
            or token_count < 0
        ):
            raise EmbeddingError(f"token count is invalid: {item_id}")
        if token_count > self._max_input_tokens:
            raise EmbeddingInputTooLongError(
                f"input exceeds {self._max_input_tokens} tokens: {item_id}"
            )

    def _normalize_vector(
        self,
        vector: Sequence[float],
        *,
        item_id: str,
    ) -> tuple[float, ...]:
        try:
            values = tuple(_to_float32(value) for value in vector)
        except (OverflowError, TypeError, ValueError) as error:
            raise VectorValueInvalidError(
                f"vector contains a non-float32 value: {item_id}"
            ) from error
        if len(values) != self._dimension:
            raise VectorDimensionMismatchError(
                f"expected {self._dimension} values, got {len(values)}: {item_id}"
            )
        if not all(isfinite(value) for value in values):
            raise VectorValueInvalidError(
                f"vector contains a non-finite value: {item_id}"
            )

        norm = sqrt(fsum(value * value for value in values))
        if not isfinite(norm) or norm == 0:
            raise VectorValueInvalidError(
                f"vector norm must be finite and non-zero: {item_id}"
            )
        normalized = tuple(_to_float32(value / norm) for value in values)
        normalized_norm = sqrt(fsum(value * value for value in normalized))
        if not isfinite(normalized_norm) or abs(normalized_norm - 1.0) > 1e-5:
            raise VectorValueInvalidError(
                f"normalized vector norm is invalid: {item_id}"
            )
        return normalized


def _to_float32(value: float) -> float:
    return _FLOAT32.unpack(_FLOAT32.pack(float(value)))[0]
