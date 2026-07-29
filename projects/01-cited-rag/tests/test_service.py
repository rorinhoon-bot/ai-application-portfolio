from hashlib import sha256
from uuid import UUID

from cited_rag.models import (
    AnswerResult,
    ChunkPayload,
    RetrievalResult,
    RetrievedChunk,
)
from cited_rag.retrieval import (
    DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    make_retrieval_query,
)
from cited_rag.service import (
    CitedRagService,
    extract_comparison_versions,
    make_comparison_search_text,
)

INDEX_ID = UUID("614f6c23-7c35-5832-8086-c29651d60866")
BUILD_ID = UUID("4facb454-cca4-476f-b623-fa29b40fcf00")


def _chunk(version: str, rank: int) -> RetrievedChunk:
    release = "3.13.14" if version == "3.13" else "3.14.6"
    text = f"{version} evidence {rank}"
    chunk_id = UUID(
        f"00000000-0000-0000-0{version.replace('.', '')}-"
        f"{rank:012d}"
    )
    payload = ChunkPayload(
        payload_schema_version="payload-v1",
        chunk_id=chunk_id,
        snapshot_id=UUID("10000000-0000-0000-0000-000000000000"),
        source_id=f"source-{version.replace('.', '-')}",
        document_key="library-argparse",
        python_version=version,
        documentation_release=release,
        chunk_order=rank,
        block_start=rank,
        block_start_offset=0,
        block_end=rank,
        block_end_offset=len(text),
        paragraph_start=rank,
        paragraph_end=rank,
        text=text,
        section_path=("ArgumentParser 对象",),
        section_anchor="argumentparser-objects",
        source_url=(
            f"https://docs.python.org/zh-cn/{version}/"
            "library/argparse.html"
        ),
        relative_path=f"html/{release}/library/argparse.html",
        content_sha256=sha256(text.encode("utf-8")).hexdigest(),
        chunking_schema_version="chunker-v1",
        chunk_config_sha256="c" * 64,
    )
    return RetrievedChunk(
        rank=rank,
        score=0.9 - rank / 100,
        payload=payload,
        citation_url=f"{payload.source_url}#argumentparser-objects",
        retrieval_reason="dense",
    )


class FakeRetriever:
    def __init__(self) -> None:
        self.queries = []

    def retrieve(self, query):
        self.queries.append(query)
        version = query.python_version or "3.14"
        return RetrievalResult(
            query=query,
            retrieval_config=DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
            index_id=INDEX_ID,
            build_id=BUILD_ID,
            collection_name="cited-rag-test",
            results=tuple(_chunk(version, rank) for rank in range(1, 6)),
        )


class FakeAnswerer:
    def __init__(self) -> None:
        self.retrieval = None

    def answer(self, retrieval):
        self.retrieval = retrieval
        return AnswerResult(
            question=retrieval.query.question,
            status="refused",
            answer="当前知识库没有足够证据支持该问题。",
            citations=(),
            index_id=retrieval.index_id,
            build_id=retrieval.build_id,
        )


def test_explicit_two_version_question_uses_balanced_retrieval() -> None:
    retriever = FakeRetriever()
    answerer = FakeAnswerer()
    service = CitedRagService(
        retriever=retriever,
        answerer=answerer,
    )
    question = "Python 3.13 与 3.14 的 ArgumentParser 有何不同？"

    result = service.answer(question=question)

    assert result.question == question
    assert [query.python_version for query in retriever.queries] == [
        "3.13",
        "3.14",
    ]
    assert all(
        "3.13" not in query.question and "3.14" not in query.question
        for query in retriever.queries
    )
    assert answerer.retrieval.query.question == question
    assert [
        item.payload.python_version
        for item in answerer.retrieval.results
    ] == ["3.13", "3.14", "3.13", "3.14", "3.13"]
    assert [
        item.rank for item in answerer.retrieval.results
    ] == [1, 2, 3, 4, 5]


def test_single_version_question_keeps_one_retrieval() -> None:
    retriever = FakeRetriever()
    answerer = FakeAnswerer()
    service = CitedRagService(
        retriever=retriever,
        answerer=answerer,
    )

    service.answer(
        question="Python 3.14 的 ArgumentParser 如何使用？",
        python_version="3.14",
    )

    assert len(retriever.queries) == 1
    assert retriever.queries[0] == make_retrieval_query(
        question="Python 3.14 的 ArgumentParser 如何使用？",
        python_version="3.14",
    )


def test_comparison_helpers_require_both_supported_versions() -> None:
    assert extract_comparison_versions(
        "比较 Python 3.14 和 3.13"
    ) == ("3.13", "3.14")
    assert extract_comparison_versions("只问 3.14") == ("3.14",)
    assert (
        make_comparison_search_text(
            "Python 3.13 与 3.14 的 ArgumentParser 默认 prog 规则"
        )
        == "ArgumentParser 默认 prog 规则"
    )
