"""Local-only FastEmbed provider and no-truncation token counter."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Callable

from fastembed import TextEmbedding
from fastembed.common.preprocessor_utils import load_tokenizer

from cited_rag.errors import EmbeddingError
from cited_rag.models import EmbeddingConfig

TextEmbeddingFactory = Callable[..., Any]


class FastEmbedLocalProvider:
    """CPU FastEmbed adapter pinned to an already verified local snapshot."""

    def __init__(
        self,
        *,
        model_dir: Path,
        config: EmbeddingConfig,
        factory: TextEmbeddingFactory = TextEmbedding,
    ) -> None:
        try:
            resolved_model_dir = model_dir.resolve(strict=True)
        except OSError as error:
            raise EmbeddingError("local model directory is unavailable") from error
        if not resolved_model_dir.is_dir():
            raise EmbeddingError("local model path is not a directory")
        try:
            self._model = factory(
                model_name=config.model_name,
                cache_dir=str(resolved_model_dir.parent),
                specific_model_path=str(resolved_model_dir),
                local_files_only=True,
                cuda=False,
            )
        except Exception as error:
            raise EmbeddingError("could not load pinned local model") from error

    def embed_passages(
        self,
        texts: Sequence[str],
        *,
        batch_size: int,
    ) -> Iterable[Sequence[float]]:
        yield from self._model.passage_embed(
            tuple(texts),
            batch_size=batch_size,
        )

    def embed_query(self, text: str) -> Sequence[float]:
        vectors = tuple(self._model.query_embed(text, batch_size=1))
        if len(vectors) != 1:
            raise EmbeddingError("query provider did not return exactly one vector")
        return vectors[0]


class FastEmbedNoTruncationTokenCounter:
    """Count with FastEmbed's tokenizer after explicitly disabling truncation."""

    def __init__(self, *, model_dir: Path) -> None:
        try:
            tokenizer, _ = load_tokenizer(model_dir.resolve(strict=True))
        except Exception as error:
            raise EmbeddingError("could not load pinned local tokenizer") from error
        tokenizer.no_truncation()
        tokenizer.no_padding()
        self._tokenizer = tokenizer

    def count_tokens(self, text: str) -> int:
        return len(
            self._tokenizer.encode(
                text,
                add_special_tokens=True,
            ).ids
        )
