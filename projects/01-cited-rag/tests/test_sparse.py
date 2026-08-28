from hashlib import sha256
from pathlib import Path

import pytest

from cited_rag.errors import IndexConsistencyError
from cited_rag.sparse import (
    build_sparse_corpus,
    load_sparse_vocabulary,
    make_sparse_config_sha256,
    make_sparse_query_vector,
    tokenize_sparse,
    write_sparse_vocabulary,
)
from tests.test_retrieval import chunks


def test_fixed_sparse_tokenizer_and_config_hash() -> None:
    assert tokenize_sparse("路径Path.read_text在3.14.6读取文件") == (
        "h:路径",
        "a:path.read_text",
        "a:path",
        "a:read_text",
        "h:在",
        "n:3.14.6",
        "h:读取",
        "h:取文",
        "h:文件",
    )
    assert make_sparse_config_sha256() == (
        "53400f58436e2faf179eb5383aac62e63ca8ab86d161e7c8a05b413ee3b9d8a2"
    )


def test_sparse_corpus_is_nonempty_deterministic_and_content_addressed(tmp_path) -> None:
    first = build_sparse_corpus(chunks())
    second = build_sparse_corpus(tuple(reversed(chunks())))

    assert first.config_sha256 == second.config_sha256
    assert first.vocabulary_sha256 == second.vocabulary_sha256
    assert first.document_length_sum == second.document_length_sum
    assert all(vector.indices and vector.values for vector in first.vectors.values())

    path = write_sparse_vocabulary(root=tmp_path, corpus=first)
    loaded = load_sparse_vocabulary(
        root=tmp_path,
        expected_sha256=first.vocabulary_sha256,
    )
    assert loaded == first.vocabulary
    assert sha256(path.read_bytes().rstrip(b"\n")).hexdigest() == first.vocabulary_sha256


def test_sparse_query_uses_unique_sorted_indices() -> None:
    corpus = build_sparse_corpus(chunks())
    vector = make_sparse_query_vector(
        text="Path.read_text Path.read_text 文本",
        vocabulary=corpus.vocabulary,
    )

    assert vector.indices == sorted(set(vector.indices))
    assert vector.values == [1.0] * len(vector.indices)


def test_sparse_build_fails_before_vector_creation_on_collision(monkeypatch) -> None:
    monkeypatch.setattr("cited_rag.sparse.mmh3.hash", lambda *args, **kwargs: 7)

    with pytest.raises(IndexConsistencyError, match="hash collision"):
        build_sparse_corpus(chunks())


def test_vocabulary_loader_accepts_only_hash_identity(tmp_path) -> None:
    with pytest.raises(IndexConsistencyError, match="hash is invalid"):
        load_sparse_vocabulary(root=tmp_path, expected_sha256="../escape")


def test_vocabulary_writer_rejects_non_directory_root(tmp_path: Path) -> None:
    unsafe = tmp_path / "vocabularies"
    unsafe.write_text("not a directory", encoding="utf-8")

    with pytest.raises(IndexConsistencyError, match="root is unsafe"):
        write_sparse_vocabulary(root=unsafe, corpus=build_sparse_corpus(chunks()))


def test_vocabulary_writer_rejects_directory_symlink(tmp_path: Path, monkeypatch) -> None:
    unsafe = tmp_path / "vocabularies"
    unsafe.mkdir()
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda value: value == unsafe or original(value),
    )

    with pytest.raises(IndexConsistencyError, match="root is unsafe"):
        write_sparse_vocabulary(root=unsafe, corpus=build_sparse_corpus(chunks()))
