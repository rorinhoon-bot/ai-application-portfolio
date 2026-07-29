from __future__ import annotations

from pathlib import Path

import pytest

from cited_rag.adapters.fastembed_local import (
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.errors import EmbeddingError
from cited_rag.models import EmbeddingConfig


def embedding_config() -> EmbeddingConfig:
    return EmbeddingConfig(
        schema_version="1",
        provider="fastembed",
        model_name="BAAI/bge-small-zh-v1.5",
        resolved_model_source="Qdrant/bge-small-zh-v1.5",
        model_revision="1" * 40,
        model_assets_sha256="2" * 64,
        model_license="mit",
        model_cache_relative_path="data/models/fastembed",
        dimension=512,
        max_input_tokens=512,
        batch_size=64,
        distance="cosine",
        normalize=True,
        query_instruction=None,
        passage_instruction=None,
    )


class FakeTextEmbedding:
    def __init__(self) -> None:
        self.passage_calls: list[tuple[tuple[str, ...], int]] = []
        self.query_calls: list[tuple[str, int]] = []

    def passage_embed(self, texts, *, batch_size):
        self.passage_calls.append((texts, batch_size))
        return ([1.0, 0.0] for _ in texts)

    def query_embed(self, text, *, batch_size):
        self.query_calls.append((text, batch_size))
        return iter(([0.0, 1.0],))


def test_local_provider_forces_pinned_path_offline_and_cpu(
    tmp_path: Path,
) -> None:
    model_dir = tmp_path / "snapshot"
    model_dir.mkdir()
    calls: list[dict[str, object]] = []
    fake = FakeTextEmbedding()

    def factory(**kwargs):
        calls.append(kwargs)
        return fake

    provider = FastEmbedLocalProvider(
        model_dir=model_dir,
        config=embedding_config(),
        factory=factory,
    )

    assert calls == [
        {
            "model_name": "BAAI/bge-small-zh-v1.5",
            "cache_dir": str(tmp_path),
            "specific_model_path": str(model_dir),
            "local_files_only": True,
            "cuda": False,
        }
    ]
    assert tuple(
        provider.embed_passages(("a", "b"), batch_size=64)
    ) == ([1.0, 0.0], [1.0, 0.0])
    assert provider.embed_query("q") == [0.0, 1.0]
    assert fake.passage_calls == [(("a", "b"), 64)]
    assert fake.query_calls == [("q", 1)]


def test_local_provider_rejects_missing_model_directory(
    tmp_path: Path,
) -> None:
    with pytest.raises(EmbeddingError, match="EMBEDDING_ERROR.*unavailable"):
        FastEmbedLocalProvider(
            model_dir=tmp_path / "missing",
            config=embedding_config(),
        )


def test_no_truncation_counter_disables_truncation_and_padding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_dir = tmp_path / "snapshot"
    model_dir.mkdir()

    class Encoding:
        ids = [1, 2, 3]

    class FakeTokenizer:
        truncation_disabled = False
        padding_disabled = False

        def no_truncation(self):
            self.truncation_disabled = True

        def no_padding(self):
            self.padding_disabled = True

        def encode(self, text, *, add_special_tokens):
            assert text == "abc"
            assert add_special_tokens is True
            return Encoding()

    tokenizer = FakeTokenizer()
    monkeypatch.setattr(
        "cited_rag.adapters.fastembed_local.load_tokenizer",
        lambda _path: (tokenizer, {}),
    )

    counter = FastEmbedNoTruncationTokenCounter(model_dir=model_dir)

    assert counter.count_tokens("abc") == 3
    assert tokenizer.truncation_disabled
    assert tokenizer.padding_disabled
