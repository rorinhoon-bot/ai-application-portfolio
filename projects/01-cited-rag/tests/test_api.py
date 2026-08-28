from collections.abc import Callable
from uuid import UUID

import anyio
import httpx
import pytest

from cited_rag.api import create_app
from cited_rag.errors import (
    EmbeddingInputTooLongError,
    IndexConsistencyError,
    InvalidModelJsonError,
    ModelHttpError,
    ModelNetworkError,
    ModelTimeoutError,
    RetrievalError,
    RetrievalInputError,
)
from cited_rag.models import AnswerCitation, AnswerResult

INDEX_ID = UUID("614f6c23-7c35-5832-8086-c29651d60866")
BUILD_ID = UUID("4facb454-cca4-476f-b623-fa29b40fcf00")
CHUNK_14 = UUID("10000000-0000-0000-0000-000000000014")
CHUNK_13 = UUID("10000000-0000-0000-0000-000000000013")


class FakeApplication:
    def __init__(self, result: AnswerResult) -> None:
        self.result = result
        self.answer_calls: list[tuple[str, str | None]] = []
        self.readiness_calls = 0

    def answer(
        self,
        *,
        question: str,
        python_version: str | None = None,
    ) -> AnswerResult:
        self.answer_calls.append((question, python_version))
        return self.result

    def check_ready(self) -> None:
        self.readiness_calls += 1


class FailingApplication:
    def __init__(self, error_factory: Callable[[], Exception]) -> None:
        self._error_factory = error_factory

    def answer(self, *, question: str, python_version=None) -> AnswerResult:
        raise self._error_factory()

    def check_ready(self) -> None:
        pass


class ApiClient:
    """Small synchronous wrapper around HTTPX's existing ASGI transport."""

    def __init__(self, application) -> None:
        self._application = application

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(
                app=self._application,
                raise_app_exceptions=False,
            )
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path, **kwargs)

        return anyio.run(send)

    def get(self, path: str, **kwargs) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> httpx.Response:
        return self.request("POST", path, **kwargs)


def _citation(
    *,
    rank: int,
    version: str,
    chunk_id: UUID,
) -> AnswerCitation:
    release = "3.14.6" if version == "3.14" else "3.13.14"
    return AnswerCitation(
        rank=rank,
        chunk_id=chunk_id,
        python_version=version,
        documentation_release=release,
        section_path=("ArgumentParser 对象",),
        citation_url=(
            f"https://docs.python.org/zh-cn/{version}/"
            "library/argparse.html#argumentparser-objects"
        ),
        excerpt=f"Python {version} 官方证据。",
    )


def _answer_result(question: str, status: str) -> AnswerResult:
    if status == "refused":
        citations = ()
        answer = "当前知识库没有检索到足够证据支持该问题。"
    elif status == "conflict":
        citations = (
            _citation(rank=1, version="3.14", chunk_id=CHUNK_14),
            _citation(rank=2, version="3.13", chunk_id=CHUNK_13),
        )
        answer = "Python 3.13 与 3.14 的证据不同。"
    else:
        citations = (
            _citation(rank=1, version="3.14", chunk_id=CHUNK_14),
        )
        answer = "Python 3.14 的答案。"
    return AnswerResult(
        question=question,
        status=status,
        answer=answer,
        citations=citations,
        index_id=INDEX_ID,
        build_id=BUILD_ID,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
    )


def _client(
    application,
    *,
    readiness_probe: Callable[[], None] | None = lambda: None,
) -> ApiClient:
    return ApiClient(
        create_app(
            application_factory=lambda: application,
            readiness_probe=readiness_probe,
        )
    )


def _assert_request_id(response, *, body_field: bool) -> UUID:
    header_id = UUID(response.headers["X-Request-ID"])
    if response.status_code >= 400:
        assert response.headers["content-type"].startswith(
            "application/problem+json"
        )
    if body_field:
        assert UUID(response.json()["request_id"]) == header_id
    return header_id


def test_health_is_live_without_initializing_application() -> None:
    factory_calls = 0

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        return FakeApplication(_answer_result("问题", "refused"))

    client = ApiClient(
        create_app(application_factory=factory)
    )

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "cited-rag-api",
    }
    _assert_request_id(response, body_field=False)
    assert factory_calls == 0


def test_default_readiness_probe_initializes_once_and_checks_service() -> None:
    application = FakeApplication(_answer_result("问题", "refused"))
    factory_calls = 0

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        return application

    client = ApiClient(
        create_app(application_factory=factory)
    )

    first = client.get("/readyz")
    second = client.get("/readyz")

    assert first.status_code == second.status_code == 200
    assert first.json() == {
        "status": "ready",
        "service": "cited-rag-api",
        "checks": {
            "configuration": "ok",
            "index": "ok",
            "retriever": "ok",
        },
    }
    assert factory_calls == 1
    assert application.readiness_calls == 2


def test_readiness_failure_returns_safe_problem_details() -> None:
    def failing_probe() -> None:
        raise RuntimeError("MODEL_API_KEY=must-not-leak")

    response = _client(
        FakeApplication(_answer_result("问题", "refused")),
        readiness_probe=failing_probe,
    ).get("/readyz")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith(
        "application/problem+json"
    )
    assert response.json()["code"] == "service_not_ready"
    assert "must-not-leak" not in response.text
    _assert_request_id(response, body_field=True)


@pytest.mark.parametrize("status", ["answered", "refused", "conflict"])
def test_answer_wraps_validated_business_result(status: str) -> None:
    question = "Python 3.14 的 ArgumentParser 如何使用？"
    application = FakeApplication(_answer_result(question, status))

    response = _client(application).post(
        "/v1/answers",
        json={
            "schema_version": "1",
            "question": question,
            "python_version": "3.14",
        },
    )

    assert response.status_code == 200
    assert response.json()["schema_version"] == "1"
    assert response.json()["result"]["status"] == status
    assert response.json()["result"]["index_id"] == str(INDEX_ID)
    assert application.answer_calls == [(question, "3.14")]
    _assert_request_id(response, body_field=True)


def test_answer_uses_server_request_id_and_optional_version() -> None:
    question = "如何创建虚拟环境？"
    application = FakeApplication(_answer_result(question, "refused"))
    supplied_id = "00000000-0000-0000-0000-000000000001"

    response = _client(application).post(
        "/v1/answers",
        json={"schema_version": "1", "question": question},
        headers={"X-Request-ID": supplied_id},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != supplied_id
    assert application.answer_calls == [(question, None)]
    _assert_request_id(response, body_field=True)


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "问题"},
        {"schema_version": "2", "question": "问题"},
        {"schema_version": "1", "question": ""},
        {"schema_version": "1", "question": " 问题"},
        {"schema_version": "1", "question": "问" * 501},
        {
            "schema_version": "1",
            "question": "问题",
            "python_version": "3.12",
        },
        {
            "schema_version": "1",
            "question": "问题",
            "unexpected": "SECRET_VALUE_MUST_NOT_LEAK",
        },
    ],
)
def test_answer_rejects_invalid_request_without_echo(payload: dict) -> None:
    application = FakeApplication(_answer_result("问题", "refused"))

    response = _client(application).post("/v1/answers", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "request_validation_failed"
    assert "SECRET_VALUE_MUST_NOT_LEAK" not in response.text
    assert application.answer_calls == []
    _assert_request_id(response, body_field=True)


def test_malformed_json_uses_problem_details_without_echo() -> None:
    response = _client(
        FakeApplication(_answer_result("问题", "refused"))
    ).post(
        "/v1/answers",
        content='{"schema_version":"1","question":"SECRET_BROKEN"',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "request_validation_failed"
    assert "SECRET_BROKEN" not in response.text
    _assert_request_id(response, body_field=True)


@pytest.mark.parametrize(
    ("error_factory", "expected_status", "expected_code"),
    [
        (
            lambda: RetrievalInputError("bad input"),
            422,
            "request_validation_failed",
        ),
        (
            lambda: EmbeddingInputTooLongError("too long"),
            422,
            "request_validation_failed",
        ),
        (
            lambda: IndexConsistencyError("index secret"),
            503,
            "service_not_ready",
        ),
        (
            lambda: RetrievalError("retrieval secret"),
            503,
            "service_not_ready",
        ),
        (
            lambda: ModelNetworkError("supplier secret"),
            502,
            "model_upstream_failed",
        ),
        (
            lambda: ModelHttpError(429),
            502,
            "model_upstream_failed",
        ),
        (
            lambda: InvalidModelJsonError("raw model secret"),
            502,
            "model_upstream_failed",
        ),
        (
            lambda: ModelTimeoutError("timeout secret"),
            504,
            "model_upstream_timeout",
        ),
    ],
)
def test_domain_errors_map_to_safe_http_contract(
    error_factory,
    expected_status: int,
    expected_code: str,
) -> None:
    response = _client(FailingApplication(error_factory)).post(
        "/v1/answers",
        json={"schema_version": "1", "question": "问题"},
    )

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert "secret" not in response.text.lower()
    _assert_request_id(response, body_field=True)


def test_unexpected_error_hides_details_and_keeps_request_id() -> None:
    response = _client(
        FailingApplication(
            lambda: RuntimeError("MODEL_API_KEY=must-not-leak")
        )
    ).post(
        "/v1/answers",
        json={"schema_version": "1", "question": "问题"},
    )

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert "must-not-leak" not in response.text
    _assert_request_id(response, body_field=True)


def test_factory_failure_is_service_not_ready() -> None:
    def failing_factory():
        raise RuntimeError("LOCAL_SECRET=must-not-leak")

    client = ApiClient(
        create_app(
            application_factory=failing_factory,
            readiness_probe=lambda: None,
        )
    )

    response = client.post(
        "/v1/answers",
        json={"schema_version": "1", "question": "问题"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "service_not_ready"
    assert "must-not-leak" not in response.text
    _assert_request_id(response, body_field=True)


def test_mismatched_service_question_is_internal_error() -> None:
    application = FakeApplication(
        _answer_result("另一个问题", "refused")
    )

    response = _client(application).post(
        "/v1/answers",
        json={"schema_version": "1", "question": "当前问题"},
    )

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    _assert_request_id(response, body_field=True)


def test_unknown_route_uses_problem_details() -> None:
    response = _client(
        FakeApplication(_answer_result("问题", "refused"))
    ).get("/missing")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    _assert_request_id(response, body_field=True)


def test_openapi_exposes_only_versioned_read_contract() -> None:
    response = _client(
        FakeApplication(_answer_result("问题", "refused"))
    ).get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["version"] == "0.2.0"
    assert set(response.json()["paths"]) == {
        "/healthz",
        "/readyz",
        "/v1/answers",
    }
    answer_responses = response.json()["paths"]["/v1/answers"][
        "post"
    ]["responses"]
    for status in ("422", "500", "502", "503", "504"):
        assert set(answer_responses[status]["content"]) == {
            "application/problem+json"
        }


def test_cors_is_disabled_by_default() -> None:
    response = _client(
        FakeApplication(_answer_result("问题", "refused"))
    ).request(
        "OPTIONS",
        "/v1/answers",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 405
    assert "access-control-allow-origin" not in response.headers
    assert "POST" in response.headers["allow"]
    _assert_request_id(response, body_field=True)
