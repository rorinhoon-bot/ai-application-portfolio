from __future__ import annotations

import json
from hashlib import sha256
from uuid import UUID

import pytest

from cited_rag.answering import (
    AnsweringService,
    NO_EVIDENCE_ANSWER,
)
from cited_rag.errors import (
    InvalidCitationIdError,
    InvalidModelJsonError,
    ModelHttpError,
    ModelOutputError,
)
from cited_rag.model_client import (
    AnswerModelAttempt,
    AnswerModelRequest,
    AnswerModelResponse,
)
from cited_rag.models import (
    ChunkPayload,
    RetrievalResult,
    RetrievedChunk,
)
from cited_rag.retrieval import DENSE_IDENTIFIER_RETRIEVAL_CONFIG
from cited_rag.observability import bind_observability

INDEX_ID = UUID("614f6c23-7c35-5832-8086-c29651d60866")
BUILD_ID = UUID("4facb454-cca4-476f-b623-fa29b40fcf00")
CHUNK_314 = UUID("00000000-0000-0000-0000-000000000314")
CHUNK_313 = UUID("00000000-0000-0000-0000-000000000313")


class FakeModelClient:
    def __init__(
        self,
        content: str,
        *,
        attempts: tuple[AnswerModelAttempt, ...] = (),
    ) -> None:
        self.content = content
        self.attempts = attempts
        self.requests: list[AnswerModelRequest] = []

    def generate(self, request: AnswerModelRequest) -> AnswerModelResponse:
        self.requests.append(request)
        return AnswerModelResponse(
            content=self.content,
            prompt_tokens=120,
            completion_tokens=30,
            total_tokens=150,
            attempts=self.attempts,
        )


class RecordingTelemetry:
    def __init__(self) -> None:
        self.attempts: list[dict[str, object]] = []
        self.completions: list[dict[str, object]] = []

    def record_model_attempt(self, **fields: object) -> None:
        self.attempts.append(fields)

    def record_model_completed(self, **fields: object) -> None:
        self.completions.append(fields)


class FailingRetryClient:
    def generate(self, request: AnswerModelRequest) -> AnswerModelResponse:
        error = ModelHttpError(503)
        error.model_attempts = (
            AnswerModelAttempt(
                attempt=1,
                outcome="error",
                retry_reason="server_error",
                retry_delay_ms=250,
                billing_uncertain=True,
            ),
            AnswerModelAttempt(attempt=2, outcome="error"),
        )
        raise error


def make_retrieved(
    *,
    rank: int,
    chunk_id: UUID,
    python_version: str,
    text: str,
) -> RetrievedChunk:
    release = "3.14.6" if python_version == "3.14" else "3.13.14"
    payload = ChunkPayload(
        payload_schema_version="payload-v1",
        chunk_id=chunk_id,
        snapshot_id=UUID(
            "10000000-0000-0000-0000-000000000000"
        ),
        source_id=f"source-{python_version.replace('.', '-')}",
        document_key="venv",
        python_version=python_version,
        documentation_release=release,
        chunk_order=rank,
        block_start=rank,
        block_start_offset=0,
        block_end=rank,
        block_end_offset=len(text),
        paragraph_start=rank,
        paragraph_end=rank,
        text=text,
        section_path=("创建虚拟环境",),
        section_anchor=f"venv-{python_version.replace('.', '-')}",
        source_url=(
            f"https://docs.python.org/zh-cn/{python_version}/"
            "library/venv.html"
        ),
        relative_path=f"html/{release}/library/venv.html",
        content_sha256=sha256(text.encode("utf-8")).hexdigest(),
        chunking_schema_version="chunker-v1",
        chunk_config_sha256="c" * 64,
    )
    return RetrievedChunk(
        rank=rank,
        score=0.8 - rank / 100,
        payload=payload,
        citation_url=f"{payload.source_url}#{payload.section_anchor}",
        retrieval_reason="dense",
    )


def make_retrieval(
    *,
    include_results: bool = True,
) -> RetrievalResult:
    results = ()
    if include_results:
        results = (
            make_retrieved(
                rank=1,
                chunk_id=CHUNK_314,
                python_version="3.14",
                text="使用 python -m venv ENV_DIR 创建虚拟环境。",
            ),
            make_retrieved(
                rank=2,
                chunk_id=CHUNK_313,
                python_version="3.13",
                text="Python 3.13 同样使用 python -m venv ENV_DIR。",
            ),
        )
    return RetrievalResult(
        query={
            "question": "如何创建虚拟环境？",
            "python_version": None,
            "top_k": 5,
        },
        retrieval_config=DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
        index_id=INDEX_ID,
        build_id=BUILD_ID,
        collection_name="cited-rag-test",
        results=results,
    )


def output(
    *,
    status: str,
    answer: str,
    citation_ids: list[str],
) -> str:
    return json.dumps(
        {
            "schema_version": "1",
            "status": status,
            "answer": answer,
            "citation_ids": citation_ids,
        },
        ensure_ascii=False,
    )


def test_answer_binds_source_metadata_only_from_retrieval() -> None:
    client = FakeModelClient(
        output(
            status="answered",
            answer="运行 python -m venv ENV_DIR。",
            citation_ids=[str(CHUNK_314)],
        )
    )

    result = AnsweringService(model_client=client).answer(make_retrieval())

    assert result.status == "answered"
    assert result.total_tokens == 150
    assert len(result.citations) == 1
    citation = result.citations[0]
    assert citation.chunk_id == CHUNK_314
    assert citation.python_version == "3.14"
    assert citation.excerpt == (
        "使用 python -m venv ENV_DIR 创建虚拟环境。"
    )
    assert str(citation.citation_url).endswith("#venv-3-14")

    request = client.requests[0]
    assert "python -m venv" not in request.system_prompt
    assert request.user_payload["evidence"][0]["chunk_id"] == str(CHUNK_314)
    assert "citation_ids" in request.response_schema["properties"]
    assert "source_url" not in request.response_schema["properties"]


def test_answer_records_each_physical_attempt_and_final_usage() -> None:
    attempts = (
        AnswerModelAttempt(
            attempt=1,
            outcome="error",
            retry_reason="server_error",
            retry_delay_ms=250,
            billing_uncertain=True,
        ),
        AnswerModelAttempt(attempt=2, outcome="success"),
    )
    client = FakeModelClient(
        output(
            status="answered",
            answer="运行 python -m venv ENV_DIR。",
            citation_ids=[str(CHUNK_314)],
        ),
        attempts=attempts,
    )
    telemetry = RecordingTelemetry()

    with bind_observability(telemetry):
        result = AnsweringService(model_client=client).answer(
            make_retrieval()
        )

    assert result.status == "answered"
    assert telemetry.attempts == [
        {
            "attempt": 1,
            "outcome": "error",
            "retry_reason": "server_error",
            "retry_delay_ms": 250,
            "billing_uncertain": True,
        },
        {
            "attempt": 2,
            "outcome": "success",
            "retry_reason": None,
            "retry_delay_ms": None,
            "billing_uncertain": False,
        },
    ]
    assert telemetry.completions == [
        {
            "outcome": "success",
            "prompt_tokens": 120,
            "completion_tokens": 30,
        }
    ]


def test_exhausted_retry_records_two_attempts_and_one_completion() -> None:
    telemetry = RecordingTelemetry()

    with bind_observability(telemetry):
        with pytest.raises(ModelHttpError, match="MODEL_HTTP_ERROR"):
            AnsweringService(model_client=FailingRetryClient()).answer(
                make_retrieval()
            )

    assert [item["attempt"] for item in telemetry.attempts] == [1, 2]
    assert telemetry.attempts[0]["retry_reason"] == "server_error"
    assert telemetry.completions == [{"outcome": "error"}]


def test_refusal_has_no_program_bound_citations() -> None:
    client = FakeModelClient(
        output(
            status="refused",
            answer="现有证据不足。",
            citation_ids=[],
        )
    )

    result = AnsweringService(model_client=client).answer(make_retrieval())

    assert result.status == "refused"
    assert result.citations == ()


def test_empty_refusal_text_uses_deterministic_program_message() -> None:
    client = FakeModelClient(
        '{"status":"refused"}'
    )

    result = AnsweringService(model_client=client).answer(make_retrieval())

    assert result.status == "refused"
    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.citations == ()


def test_no_results_refuses_without_spending_model_call() -> None:
    client = FakeModelClient("must not be used")

    result = AnsweringService(model_client=client).answer(
        make_retrieval(include_results=False)
    )

    assert result.status == "refused"
    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.total_tokens is None
    assert client.requests == []


def test_unknown_citation_id_fails_closed() -> None:
    client = FakeModelClient(
        output(
            status="answered",
            answer="伪造回答",
            citation_ids=[
                "99999999-9999-4999-8999-999999999999"
            ],
        )
    )

    with pytest.raises(
        InvalidCitationIdError,
        match="INVALID_CITATION_ID",
    ):
        AnsweringService(model_client=client).answer(make_retrieval())


@pytest.mark.parametrize("content", ["not-json", "[]", "null"])
def test_non_object_or_invalid_json_fails_closed(content: str) -> None:
    with pytest.raises(
        InvalidModelJsonError,
        match="INVALID_MODEL_JSON",
    ):
        AnsweringService(
            model_client=FakeModelClient(content)
        ).answer(make_retrieval())


@pytest.mark.parametrize(
    "content",
    [
        output(
            status="answered",
            answer="",
            citation_ids=[str(CHUNK_314)],
        ),
        output(
            status="answered",
            answer="没有引用",
            citation_ids=[],
        ),
        output(
            status="refused",
            answer="拒答却引用",
            citation_ids=[str(CHUNK_314)],
        ),
        '{"schema_version":"1","status":"answered"}',
        (
            '{"schema_version":"1","status":"answered",'
            '"answer":"回答","citation_ids":[],'
            '"source_url":"https://evil.example"}'
        ),
    ],
)
def test_schema_violation_fails_closed(content: str) -> None:
    with pytest.raises(ModelOutputError, match="MODEL_OUTPUT_ERROR") as error:
        AnsweringService(
            model_client=FakeModelClient(content)
        ).answer(make_retrieval())

    assert error.value.model_usage == (120, 30, 150)
    assert "https://evil.example" not in str(error.value)


def test_conflict_requires_citations_from_two_versions() -> None:
    client = FakeModelClient(
        output(
            status="conflict",
            answer="证据存在版本冲突。",
            citation_ids=[str(CHUNK_314), str(CHUNK_313)],
        )
    )

    result = AnsweringService(model_client=client).answer(make_retrieval())

    assert result.status == "conflict"
    assert {item.python_version for item in result.citations} == {
        "3.13",
        "3.14",
    }


def test_conflict_rejects_two_chunks_from_same_version() -> None:
    retrieval = make_retrieval()
    duplicate_version_result = make_retrieved(
        rank=2,
        chunk_id=CHUNK_313,
        python_version="3.14",
        text="第二个 3.14 片段。",
    )
    retrieval = retrieval.model_copy(
        update={
            "results": (
                retrieval.results[0],
                duplicate_version_result,
            )
        }
    )
    client = FakeModelClient(
        output(
            status="conflict",
            answer="错误冲突判断。",
            citation_ids=[str(CHUNK_314), str(CHUNK_313)],
        )
    )

    with pytest.raises(ModelOutputError, match="MODEL_OUTPUT_ERROR"):
        AnsweringService(model_client=client).answer(retrieval)
