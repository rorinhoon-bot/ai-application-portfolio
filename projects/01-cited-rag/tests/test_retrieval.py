from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from cited_rag.embedding import EmbeddingService
from cited_rag.evidence import assess_evidence
from cited_rag.errors import IndexConsistencyError, RetrievalInputError
from cited_rag.indexing import (
    activate_index,
    make_active_pointer,
    make_chunk_payload,
    make_index_manifest,
    write_index_manifest,
)
from cited_rag.models import (
    DocumentChunk,
    EvidencePolicy,
    IndexSpecification,
    RetrievalEvaluationSet,
    RetrievalResult,
    RetrievedChunk,
)
from cited_rag.retrieval import (
    DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    QdrantRetrievalService,
    extract_query_identifiers,
    make_retrieval_query,
)

BUILD_ID = UUID("00000000-0000-4000-8000-000000000041")
FIXED_TIME = datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc)


class TokenCounter:
    def count_tokens(self, text: str) -> int:
        return len(text)


class Provider:
    def __init__(self) -> None:
        self.query_calls: list[str] = []

    def embed_passages(self, texts, *, batch_size):
        raise AssertionError("retrieval must not embed passages")

    def embed_query(self, text):
        self.query_calls.append(text)
        return [1.0, 0.0, 0.0]


def make_chunk(
    label: str,
    *,
    python_version: str,
) -> DocumentChunk:
    text = {
        "a": "使用 python -m venv 创建虚拟环境。",
        "b": "Python 3.13 的 argparse 文档。",
        "c": "Path.read_text 可以读取文件系统路径中的文本。",
    }[label]
    release = "3.14.6" if python_version == "3.14" else "3.13.14"
    return DocumentChunk(
        chunk_id=UUID(f"00000000-0000-0000-0000-{ord(label):012d}"),
        snapshot_id=UUID(f"10000000-0000-0000-0000-{ord(label):012d}"),
        source_id=f"source-{label}",
        document_key=f"document-{label}",
        python_version=python_version,
        documentation_release=release,
        chunking_schema_version="chunker-v1",
        chunk_config_sha256="c" * 64,
        chunk_order=1,
        block_start=1,
        block_start_offset=0,
        block_end=1,
        block_end_offset=len(text),
        paragraph_start=1,
        paragraph_end=1,
        text=text,
        embedding_text=f"Page {label.upper()}\n\n{text}",
        section_path=(f"Page {label.upper()}",),
        section_anchor=f"section-{label}",
        source_url=(
            f"https://docs.python.org/zh-cn/{python_version}/"
            f"library/{label}.html"
        ),
        relative_path=f"html/{release}/library/{label}.html",
        content_sha256=sha256(text.encode("utf-8")).hexdigest(),
    )


def chunks() -> tuple[DocumentChunk, ...]:
    return (
        make_chunk("a", python_version="3.14"),
        make_chunk("b", python_version="3.13"),
        make_chunk("c", python_version="3.14"),
    )


def specification() -> IndexSpecification:
    return IndexSpecification(
        schema_version="1",
        corpus_id=UUID("5386ccee-bb5f-5417-b70a-33395abe9669"),
        source_manifest_sha256="a" * 64,
        parser_schema_version="parser-v1",
        chunking_schema_version="chunker-v1",
        chunk_config_sha256="c" * 64,
        chunk_count=3,
        embedding_config_sha256="d" * 64,
        embedding_dimension=3,
        distance="cosine",
        payload_schema_version="payload-v1",
    )


def create_index(
    index_root: Path,
    *,
    corrupt_point_id: bool = False,
) -> None:
    index_root.mkdir(parents=True)
    manifest = make_index_manifest(
        specification=specification(),
        build_id=BUILD_ID,
        built_at=FIXED_TIME,
        qdrant_client_version="1.18.0",
    )
    vectors = {
        "a": [1.0, 0.0, 0.0],
        "b": [0.8, 0.2, 0.0],
        "c": [0.0, 1.0, 0.0],
    }
    client = QdrantClient(path=str(index_root / "qdrant"))
    try:
        client.create_collection(
            collection_name=manifest.collection_name,
            vectors_config=VectorParams(
                size=3,
                distance=Distance.COSINE,
            ),
        )
        points = []
        for label, chunk in zip(("a", "b", "c"), chunks(), strict=True):
            payload = make_chunk_payload(chunk).model_dump(mode="json")
            if corrupt_point_id and label == "b":
                payload["chunk_id"] = str(chunks()[0].chunk_id)
            points.append(
                PointStruct(
                    id=str(chunk.chunk_id),
                    vector=vectors[label],
                    payload=payload,
                )
            )
        client.upsert(
            collection_name=manifest.collection_name,
            points=points,
            wait=True,
        )
    finally:
        client.close()

    pointer = make_active_pointer(manifest)
    write_index_manifest(
        index_root=index_root,
        pointer=pointer,
        manifest=manifest,
    )
    activate_index(
        index_root=index_root,
        pointer=pointer,
        manifest=manifest,
    )


def service(
    index_root: Path,
    provider: Provider,
    *,
    dimension: int = 3,
    retrieval_config=None,
) -> QdrantRetrievalService:
    values = {
        "embedding_service": EmbeddingService(
            provider=provider,
            token_counter=TokenCounter(),
            dimension=dimension,
            max_input_tokens=512,
            batch_size=2,
        ),
        "index_root": index_root,
    }
    if retrieval_config is not None:
        values["retrieval_config"] = retrieval_config
    return QdrantRetrievalService(
        **values,
    )


def test_query_contract_rejects_untrusted_boundary_values() -> None:
    assert make_retrieval_query(question="如何创建虚拟环境？").top_k == 5

    for values in (
        {"question": ""},
        {"question": " 两边有空白 "},
        {"question": "x" * 501},
        {"question": "问题", "python_version": "3.12"},
        {"question": "问题", "top_k": 10},
    ):
        with pytest.raises(
            RetrievalInputError,
            match="RETRIEVAL_INPUT_ERROR",
        ):
            make_retrieval_query(**values)


def test_retrieval_returns_ranked_traceable_payloads(tmp_path: Path) -> None:
    index_root = tmp_path / "indexes"
    create_index(index_root)
    provider = Provider()

    result = service(index_root, provider).retrieve(
        make_retrieval_query(question="如何创建虚拟环境？")
    )

    assert provider.query_calls == ["如何创建虚拟环境？"]
    assert len(result.results) == 3
    assert result.results[0].rank == 1
    assert result.results[0].payload.chunk_id == chunks()[0].chunk_id
    assert str(result.results[0].citation_url) == (
        "https://docs.python.org/zh-cn/3.14/library/a.html#section-a"
    )
    assert result.index_id.version == 5
    assert result.build_id == BUILD_ID


def test_python_version_filter_is_exact(tmp_path: Path) -> None:
    index_root = tmp_path / "indexes"
    create_index(index_root)

    result = service(index_root, Provider()).retrieve(
        make_retrieval_query(
            question="argparse 有什么变化？",
            python_version="3.13",
        )
    )

    assert [item.payload.python_version for item in result.results] == [
        "3.13"
    ]
    assert result.results[0].payload.chunk_id == chunks()[1].chunk_id


def test_dimension_mismatch_fails_before_query_embedding(
    tmp_path: Path,
) -> None:
    index_root = tmp_path / "indexes"
    create_index(index_root)
    provider = Provider()

    with pytest.raises(
        IndexConsistencyError,
        match="dimension does not match",
    ):
        service(index_root, provider, dimension=4).retrieve(
            make_retrieval_query(question="问题")
        )

    assert provider.query_calls == []


def test_retrieval_rejects_point_payload_identity_mismatch(
    tmp_path: Path,
) -> None:
    index_root = tmp_path / "indexes"
    create_index(index_root, corrupt_point_id=True)

    with pytest.raises(
        IndexConsistencyError,
        match="point ID does not match payload chunk_id",
    ):
        service(index_root, Provider()).retrieve(
            make_retrieval_query(question="问题")
        )


def test_result_contract_rejects_programmatically_false_citation() -> None:
    payload = make_chunk_payload(chunks()[0])

    with pytest.raises(ValidationError, match="citation_url"):
        RetrievedChunk(
            rank=1,
            score=0.9,
            payload=payload,
            citation_url=(
                "https://docs.python.org/zh-cn/3.14/library/a.html#made-up"
            ),
            retrieval_reason="dense",
        )


def test_evaluation_set_requires_fixed_manual_cases() -> None:
    base_case = {
        "question": "如何创建虚拟环境？",
        "relevant_chunk_ids": [str(chunks()[0].chunk_id)],
        "rationale": "目标片段明确给出 python -m venv。",
    }
    evaluation_set = RetrievalEvaluationSet.model_validate(
        {
            "schema_version": "1",
            "evaluation_set_id": "retrieval-v1",
            "index_fingerprint": "e" * 64,
            "top_k": 5,
            "authoring_method": "manual-from-verified-corpus",
            "cases": [
                {**base_case, "case_id": f"case-{number}"}
                for number in range(1, 11)
            ],
        }
    )

    assert len(evaluation_set.cases) == 10
    with pytest.raises(ValidationError, match="at least 10"):
        RetrievalEvaluationSet.model_validate(
            {
                **evaluation_set.model_dump(mode="json"),
                "cases": evaluation_set.model_dump(mode="json")["cases"][:9],
            }
        )


def test_identifier_lane_promotes_explicit_api_without_guessing(
    tmp_path: Path,
) -> None:
    index_root = tmp_path / "indexes"
    create_index(index_root)

    result = service(
        index_root,
        Provider(),
        retrieval_config=DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    ).retrieve(
        make_retrieval_query(
            question="Python 3.14 的 Path.read_text 返回什么？",
            python_version="3.14",
        )
    )

    assert result.results[0].payload.chunk_id == chunks()[2].chunk_id
    assert result.results[0].retrieval_reason == "identifier"
    assert result.retrieval_config.mode == "dense-plus-identifiers"


def test_identifier_extraction_uses_only_explicit_code_like_text() -> None:
    assert extract_query_identifiers(
        "Python 3.14 的 Path.read_text 和 zip 怎么用？"
    ) == ("Path.read_text", "zip")
    assert extract_query_identifiers("怎样获得模块名称？") == ()


def make_test_evidence_policy(
    result: RetrievalResult,
    *,
    threshold: float,
) -> EvidencePolicy:
    return EvidencePolicy(
        schema_version="1",
        policy_id="test-evidence-policy",
        index_id=result.index_id,
        retrieval_config=result.retrieval_config,
        calibration_set_id="test-calibration",
        calibration_set_sha256="f" * 64,
        score_definition="maximum-cosine-among-returned-results",
        threshold=threshold,
    )


def test_evidence_gate_uses_maximum_score_not_hybrid_rank_one(
    tmp_path: Path,
) -> None:
    index_root = tmp_path / "indexes"
    create_index(index_root)
    result = service(index_root, Provider()).retrieve(
        make_retrieval_query(question="问题")
    )
    first = RetrievedChunk.model_validate(
        {
            **result.results[0].model_dump(mode="json"),
            "score": 0.6,
        }
    )
    second = RetrievedChunk.model_validate(
        {
            **result.results[1].model_dump(mode="json"),
            "score": 0.7,
        }
    )
    reranked = RetrievalResult(
        query=result.query,
        retrieval_config=result.retrieval_config,
        index_id=result.index_id,
        build_id=result.build_id,
        collection_name=result.collection_name,
        results=(first, second),
    )

    assessment = assess_evidence(
        retrieval=reranked,
        policy=make_test_evidence_policy(reranked, threshold=0.65),
    )

    assert assessment.decision == "sufficient"
    assert assessment.max_score == 0.7
    assert assessment.max_score_rank == 2


def test_evidence_gate_refuses_low_score_and_empty_results(
    tmp_path: Path,
) -> None:
    index_root = tmp_path / "indexes"
    create_index(index_root)
    result = service(index_root, Provider()).retrieve(
        make_retrieval_query(question="问题")
    )
    low_items = tuple(
        RetrievedChunk.model_validate(
            {
                **item.model_dump(mode="json"),
                "score": 0.5 - item.rank / 100,
            }
        )
        for item in result.results
    )
    low_result = RetrievalResult(
        query=result.query,
        retrieval_config=result.retrieval_config,
        index_id=result.index_id,
        build_id=result.build_id,
        collection_name=result.collection_name,
        results=low_items,
    )
    empty_result = low_result.model_copy(update={"results": ()})
    policy = make_test_evidence_policy(low_result, threshold=0.6)

    low = assess_evidence(retrieval=low_result, policy=policy)
    empty = assess_evidence(retrieval=empty_result, policy=policy)

    assert (low.decision, low.reason) == (
        "insufficient",
        "score-below-threshold",
    )
    assert (empty.decision, empty.reason) == (
        "insufficient",
        "no-results",
    )
