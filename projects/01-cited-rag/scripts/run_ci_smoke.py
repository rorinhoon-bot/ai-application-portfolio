"""Run one fixed, fully fake P1 CI smoke without env, network, or model assets."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cited_rag.answering import AnsweringService  # noqa: E402
from cited_rag.model_client import (  # noqa: E402
    AnswerModelRequest,
    AnswerModelResponse,
)
from cited_rag.models import (  # noqa: E402
    AnswerResult,
    ChunkPayload,
    RetrievalResult,
    RetrievedChunk,
)
from cited_rag.retrieval import (  # noqa: E402
    BASELINE_DENSE_RETRIEVAL_CONFIG,
)
from cited_rag.service import CitedRagService  # noqa: E402

INDEX_ID = UUID("00000000-0000-0000-0000-000000000101")
BUILD_ID = UUID("00000000-0000-0000-0000-000000000102")
CHUNK_ID = UUID("00000000-0000-0000-0000-000000000103")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000104")
FIXED_QUESTION = "Python 3.14 如何创建虚拟环境？"
EVIDENCE_TEXT = "python -m venv 命令可创建虚拟环境。"


class SmokeReport(BaseModel):
    """Small machine contract revalidated before being printed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^1$")
    smoke_id: str = Field(pattern=r"^p1-ci-smoke-v1$")
    status: str = Field(pattern=r"^passed$")
    question_sha256: str = Field(min_length=64, max_length=64)
    embedding_provider: str = Field(pattern=r"^fake$")
    qdrant_provider: str = Field(pattern=r"^fake$")
    model_provider: str = Field(pattern=r"^fake$")
    embedding_calls: int = Field(ge=1)
    qdrant_calls: int = Field(ge=1)
    model_calls: int = Field(ge=1)
    retrieval_results: int = Field(ge=1, le=5)
    citations_bound: bool
    total_tokens: int = Field(ge=1)
    network_accessed: bool
    dotenv_read: bool
    model_downloaded: bool
    mimo_called: bool


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> tuple[float, float]:
        self.calls += 1
        if not text:
            raise ValueError("fake embedding received empty text")
        return (1.0, 0.0)


class FakeQdrantProvider:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, vector: tuple[float, float]) -> tuple[UUID, ...]:
        self.calls += 1
        if vector != (1.0, 0.0):
            raise ValueError("fake Qdrant received unexpected vector")
        return (CHUNK_ID,)


class FakeRetriever:
    def __init__(
        self,
        *,
        embedding: FakeEmbeddingProvider,
        qdrant: FakeQdrantProvider,
    ) -> None:
        self.embedding = embedding
        self.qdrant = qdrant

    def check_ready(self) -> None:
        return None

    def retrieve(self, query: Any) -> RetrievalResult:
        vector = self.embedding.embed(query.question)
        point_ids = self.qdrant.search(vector)
        if point_ids != (CHUNK_ID,):
            raise ValueError("fake Qdrant returned unexpected point")
        return RetrievalResult(
            query=query,
            retrieval_config=BASELINE_DENSE_RETRIEVAL_CONFIG,
            index_id=INDEX_ID,
            build_id=BUILD_ID,
            collection_name="p1-ci-smoke",
            results=(_retrieved_chunk(),),
        )


class FakeModelProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: AnswerModelRequest) -> AnswerModelResponse:
        self.calls += 1
        evidence = request.user_payload["evidence"]
        citation_id = evidence[0]["chunk_id"]
        content = json.dumps(
            {
                "schema_version": "1",
                "status": "answered",
                "answer": "使用 `python -m venv` 创建虚拟环境。",
                "citation_ids": [citation_id],
            },
            ensure_ascii=False,
        )
        return AnswerModelResponse(
            content=content,
            prompt_tokens=17,
            completion_tokens=9,
            total_tokens=26,
        )


def _retrieved_chunk() -> RetrievedChunk:
    payload = ChunkPayload(
        payload_schema_version="payload-v1",
        chunk_id=CHUNK_ID,
        snapshot_id=SNAPSHOT_ID,
        source_id="python-314-venv",
        document_key="library-venv",
        python_version="3.14",
        documentation_release="3.14.6",
        chunk_order=1,
        block_start=1,
        block_start_offset=0,
        block_end=1,
        block_end_offset=len(EVIDENCE_TEXT),
        paragraph_start=1,
        paragraph_end=1,
        text=EVIDENCE_TEXT,
        section_path=("虚拟环境",),
        section_anchor="creating-virtual-environments",
        source_url="https://docs.python.org/zh-cn/3.14/library/venv.html",
        relative_path="html/3.14.6/library/venv.html",
        content_sha256=sha256(EVIDENCE_TEXT.encode("utf-8")).hexdigest(),
        chunking_schema_version="chunker-v1",
        chunk_config_sha256="c" * 64,
    )
    return RetrievedChunk(
        rank=1,
        score=0.99,
        payload=payload,
        citation_url=(
            "https://docs.python.org/zh-cn/3.14/library/venv.html"
            "#creating-virtual-environments"
        ),
        retrieval_reason="dense",
    )


def run_smoke() -> SmokeReport:
    embedding = FakeEmbeddingProvider()
    qdrant = FakeQdrantProvider()
    model = FakeModelProvider()
    service = CitedRagService(
        retriever=FakeRetriever(embedding=embedding, qdrant=qdrant),
        answerer=AnsweringService(model_client=model),
    )
    result: AnswerResult = service.answer(question=FIXED_QUESTION)
    if result.status != "answered" or len(result.citations) != 1:
        raise AssertionError("fixed smoke did not produce one cited answer")
    if result.total_tokens != 26:
        raise AssertionError("fixed smoke token accounting changed")

    report = SmokeReport(
        schema_version="1",
        smoke_id="p1-ci-smoke-v1",
        status="passed",
        question_sha256=sha256(FIXED_QUESTION.encode("utf-8")).hexdigest(),
        embedding_provider="fake",
        qdrant_provider="fake",
        model_provider="fake",
        embedding_calls=embedding.calls,
        qdrant_calls=qdrant.calls,
        model_calls=model.calls,
        retrieval_results=1,
        citations_bound=True,
        total_tokens=result.total_tokens,
        network_accessed=False,
        dotenv_read=False,
        model_downloaded=False,
        mimo_called=False,
    )
    return SmokeReport.model_validate(report.model_dump(mode="python"))


def main() -> int:
    print(run_smoke().model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
