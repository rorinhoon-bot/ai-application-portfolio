"""Deterministic Chinese/code BM25 sparse vectors without model downloads."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import mmh3
from pydantic import ValidationError
from qdrant_client.models import SparseVector

from cited_rag.errors import IndexConsistencyError, RetrievalError
from cited_rag.models import (
    DocumentChunk,
    SparseIndexConfig,
    SparseVocabulary,
)

SPARSE_CONFIG = SparseIndexConfig(
    schema_version="1",
    name="unicode-code-bm25-v1",
    unicode_normalization="NFKC",
    han_codepoint_ranges=(
        "3400-4DBF",
        "4E00-9FFF",
        "F900-FAFF",
        "20000-2EBEF",
        "30000-323AF",
    ),
    han_ngram_size=2,
    single_han_fallback=True,
    ascii_identifier_pattern=(
        r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"
    ),
    dotted_identifier_emission="full-and-components",
    numeric_pattern=r"[0-9]+(?:\.[0-9]+)*",
    token_namespaces={
        "han": "h:",
        "ascii_identifier": "a:",
        "number": "n:",
    },
    hash_algorithm="mmh3-x86-32",
    hash_seed=0,
    hash_signed=False,
    k1=1.2,
    b=0.75,
    idf_provider="qdrant-modifier-idf",
    dense_vector_name="dense-bge-v1",
    sparse_vector_name="lexical-bm25-v1",
)

_HAN_RANGES = tuple(
    (int(value[:4], 16), int(value[5:], 16))
    for value in SPARSE_CONFIG.han_codepoint_ranges[:3]
) + tuple(
    (int(value.split("-")[0], 16), int(value.split("-")[1], 16))
    for value in SPARSE_CONFIG.han_codepoint_ranges[3:]
)
_ASCII_IDENTIFIER = re.compile(SPARSE_CONFIG.ascii_identifier_pattern)
_NUMBER = re.compile(SPARSE_CONFIG.numeric_pattern)


@dataclass(frozen=True, slots=True)
class SparseCorpus:
    """Complete collision-audited sparse build input."""

    config_sha256: str
    vocabulary: SparseVocabulary
    vocabulary_sha256: str
    document_length_sum: int
    vectors: dict[UUID, SparseVector]


def make_sparse_config_sha256(
    config: SparseIndexConfig = SPARSE_CONFIG,
) -> str:
    return sha256(_canonical_model_bytes(config)).hexdigest()


def tokenize_sparse(text: str) -> tuple[str, ...]:
    """Apply the fixed NFKC/Han/identifier/number tokenizer."""

    normalized = unicodedata.normalize("NFKC", text)
    tokens: list[str] = []
    position = 0
    while position < len(normalized):
        if _is_han(normalized[position]):
            end = position + 1
            while end < len(normalized) and _is_han(normalized[end]):
                end += 1
            run = normalized[position:end]
            if len(run) == 1:
                tokens.append(f"h:{run}")
            else:
                tokens.extend(
                    f"h:{run[index:index + 2]}"
                    for index in range(len(run) - 1)
                )
            position = end
            continue

        identifier = _ASCII_IDENTIFIER.match(normalized, position)
        if identifier is not None:
            value = identifier.group(0).lower()
            tokens.append(f"a:{value}")
            if "." in value:
                tokens.extend(f"a:{part}" for part in value.split("."))
            position = identifier.end()
            continue

        number = _NUMBER.match(normalized, position)
        if number is not None:
            tokens.append(f"n:{number.group(0)}")
            position = number.end()
            continue
        position += 1
    return tuple(tokens)


def build_sparse_corpus(chunks: Sequence[DocumentChunk]) -> SparseCorpus:
    """Build all BM25 TF vectors only after global collision audit."""

    if not chunks:
        raise IndexConsistencyError("sparse index requires at least one chunk")
    tokenized = {chunk.chunk_id: tokenize_sparse(chunk.text) for chunk in chunks}
    if any(not tokens for tokens in tokenized.values()):
        raise IndexConsistencyError("sparse index contains an empty document vector")
    vocabulary_tokens = tuple(
        sorted({token for tokens in tokenized.values() for token in tokens})
    )
    _make_hash_registry(vocabulary_tokens, error_type=IndexConsistencyError)
    config_sha256 = make_sparse_config_sha256()
    vocabulary = SparseVocabulary(
        schema_version="1",
        sparse_config_sha256=config_sha256,
        tokens=vocabulary_tokens,
    )
    vocabulary_sha256 = sha256(_canonical_model_bytes(vocabulary)).hexdigest()
    document_length_sum = sum(len(tokens) for tokens in tokenized.values())
    average_document_length = document_length_sum / len(tokenized)
    vectors = {
        chunk_id: _make_document_vector(
            tokens=tokens,
            average_document_length=average_document_length,
        )
        for chunk_id, tokens in tokenized.items()
    }
    return SparseCorpus(
        config_sha256=config_sha256,
        vocabulary=vocabulary,
        vocabulary_sha256=vocabulary_sha256,
        document_length_sum=document_length_sum,
        vectors=vectors,
    )


def write_sparse_vocabulary(*, root: Path, corpus: SparseCorpus) -> Path:
    """Write or verify one immutable content-addressed vocabulary."""

    resolved_root = _resolve_vocabulary_root(root, create=True)
    target = resolved_root / f"{corpus.vocabulary_sha256}.json"
    serialized = _canonical_model_bytes(corpus.vocabulary) + b"\n"
    if target.exists():
        if not target.is_file() or target.is_symlink() or target.read_bytes() != serialized:
            raise IndexConsistencyError("existing sparse vocabulary changed")
        return target
    try:
        with target.open("xb") as file:
            file.write(serialized)
            file.flush()
    except OSError as error:
        raise IndexConsistencyError("could not write sparse vocabulary") from error
    return target


def load_sparse_vocabulary(*, root: Path, expected_sha256: str) -> SparseVocabulary:
    """Load and hash-check one vocabulary without accepting a path."""

    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise IndexConsistencyError("sparse vocabulary hash is invalid")
    try:
        resolved_root = _resolve_vocabulary_root(root, create=False)
        path = (resolved_root / f"{expected_sha256}.json").resolve(strict=True)
        path.relative_to(resolved_root)
        if not path.is_file() or path.is_symlink():
            raise OSError
        raw = path.read_bytes()
        vocabulary = SparseVocabulary.model_validate_json(raw)
    except (OSError, ValueError, ValidationError) as error:
        raise IndexConsistencyError("sparse vocabulary is unavailable") from error
    if sha256(_canonical_model_bytes(vocabulary)).hexdigest() != expected_sha256:
        raise IndexConsistencyError("sparse vocabulary hash changed")
    return vocabulary


def make_sparse_query_vector(
    *,
    text: str,
    vocabulary: SparseVocabulary,
) -> SparseVector:
    """Hash unique query tokens and reject collisions with corpus terms."""

    registry = _make_hash_registry(
        vocabulary.tokens,
        error_type=IndexConsistencyError,
    )
    indices: set[int] = set()
    for token in set(tokenize_sparse(text)):
        index = _token_index(token)
        existing = registry.get(index)
        if existing is not None and existing != token:
            raise RetrievalError("sparse query token hash collision")
        indices.add(index)
    if not indices:
        raise RetrievalError("sparse query contains no supported tokens")
    ordered = sorted(indices)
    return SparseVector(indices=ordered, values=[1.0] * len(ordered))


def _make_document_vector(
    *,
    tokens: tuple[str, ...],
    average_document_length: float,
) -> SparseVector:
    counts = Counter(tokens)
    denominator_length = 1 - SPARSE_CONFIG.b + (
        SPARSE_CONFIG.b * len(tokens) / average_document_length
    )
    pairs = []
    for token, frequency in counts.items():
        value = (
            frequency * (SPARSE_CONFIG.k1 + 1)
            / (frequency + SPARSE_CONFIG.k1 * denominator_length)
        )
        if not math.isfinite(value) or value <= 0:
            raise IndexConsistencyError("sparse document weight is invalid")
        pairs.append((_token_index(token), value))
    pairs.sort()
    return SparseVector(
        indices=[index for index, _ in pairs],
        values=[value for _, value in pairs],
    )


def _make_hash_registry(tokens, *, error_type):
    registry: dict[int, str] = {}
    for token in tokens:
        index = _token_index(token)
        existing = registry.get(index)
        if existing is not None and existing != token:
            raise error_type("sparse token hash collision")
        registry[index] = token
    return registry


def _token_index(token: str) -> int:
    return mmh3.hash(token, seed=0, signed=False)


def _is_han(character: str) -> bool:
    codepoint = ord(character)
    return any(start <= codepoint <= end for start, end in _HAN_RANGES)


def _resolve_vocabulary_root(root: Path, *, create: bool) -> Path:
    """Reject a replaced vocabulary directory instead of following links."""

    try:
        parent = root.parent.resolve(strict=True)
        if root.exists():
            if root.is_symlink() or not root.is_dir():
                raise OSError
        elif create:
            root.mkdir()
        else:
            raise OSError
        if root.is_symlink():
            raise OSError
        resolved = root.resolve(strict=True)
        if resolved.parent != parent:
            raise OSError
        return resolved
    except OSError as error:
        raise IndexConsistencyError("sparse vocabulary root is unsafe") from error


def _canonical_model_bytes(value) -> bytes:
    return json.dumps(
        value.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
