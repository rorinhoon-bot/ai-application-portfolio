from __future__ import annotations

from io import StringIO
import json
from uuid import UUID

import anyio
import httpx
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from cited_rag.api import create_app
from cited_rag.models import AnswerResult
from cited_rag.observability import (
    Observability,
    build_json_logger,
    current_observability,
)

INDEX_ID = UUID("614f6c23-7c35-5832-8086-c29651d60866")
BUILD_ID = UUID("4facb454-cca4-476f-b623-fa29b40fcf00")
QUESTION_SECRET = "QUESTION_SECRET_7f12"
EVIDENCE_SECRET = "EVIDENCE_SECRET_b98a"
ANSWER_SECRET = "ANSWER_SECRET_991c"
API_KEY_SECRET = "API_KEY_SECRET_456d"
ABSOLUTE_PATH_SECRET = "H:\\private\\secret.txt"


class FakeObservedApplication:
    def check_ready(self) -> None:
        pass

    def answer(self, *, question: str, python_version=None) -> AnswerResult:
        telemetry = current_observability()
        with telemetry.stage(
            "rag.answer",
            stage="answer",
            attributes={
                "question": QUESTION_SECRET,
                "python_version": python_version,
            },
        ):
            with telemetry.stage(
                "rag.retrieval",
                stage="retrieval",
            ):
                with telemetry.stage(
                    "rag.embedding",
                    stage="embedding",
                ):
                    pass
                with telemetry.stage(
                    "rag.qdrant.dense",
                    stage="qdrant.dense",
                ):
                    pass
                with telemetry.stage(
                    "rag.qdrant.sparse",
                    stage="qdrant.sparse",
                ):
                    pass
                with telemetry.stage("rag.fusion", stage="fusion"):
                    telemetry.record_candidates(source="dense", count=20)
                    telemetry.record_candidates(source="sparse", count=20)
                    telemetry.record_candidates(source="fused", count=20)
            with telemetry.stage(
                "rag.generation",
                stage="generation",
            ):
                telemetry.record_model_call(
                    outcome="success",
                    prompt_tokens=12,
                    completion_tokens=3,
                )
            telemetry.record_answer(
                status="refused",
                index_id=INDEX_ID,
                build_id=BUILD_ID,
            )
            telemetry.emit(
                event="privacy.fixture",
                question=QUESTION_SECRET,
                evidence=EVIDENCE_SECRET,
                answer=ANSWER_SECRET,
                api_key=API_KEY_SECRET,
                absolute_path=ABSOLUTE_PATH_SECRET,
            )
        return AnswerResult(
            question=question,
            status="refused",
            answer=ANSWER_SECRET,
            citations=(),
            index_id=INDEX_ID,
            build_id=BUILD_ID,
            prompt_tokens=12,
            completion_tokens=3,
            total_tokens=15,
        )


def make_in_memory_observability():
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider(shutdown_on_exit=False)
    tracer_provider.add_span_processor(
        SimpleSpanProcessor(span_exporter)
    )
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(
        metric_readers=(metric_reader,),
        shutdown_on_exit=False,
    )
    stream = StringIO()
    observability = Observability(
        tracer=tracer_provider.get_tracer("test"),
        meter=meter_provider.get_meter("test"),
        logger=build_json_logger(stream=stream),
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )
    return observability, span_exporter, metric_reader, stream


def request(application, method: str, path: str, **kwargs):
    async def send():
        transport = httpx.ASGITransport(
            app=application,
            raise_app_exceptions=False,
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    return anyio.run(send)


def metric_records(reader: InMemoryMetricReader):
    data = reader.get_metrics_data()
    assert data is not None
    return {
        metric.name: list(metric.data.data_points)
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }


def test_fake_http_chain_has_correlated_safe_spans_logs_and_metrics() -> None:
    telemetry, span_exporter, metric_reader, stream = (
        make_in_memory_observability()
    )
    application = create_app(
        application_factory=FakeObservedApplication,
        readiness_probe=lambda: None,
        observability=telemetry,
    )

    response = request(
        application,
        "POST",
        "/v1/answers",
        json={"schema_version": "1", "question": QUESTION_SECRET},
    )

    assert response.status_code == 200
    request_id = response.headers["X-Request-ID"]
    spans = {
        span.name: span for span in span_exporter.get_finished_spans()
    }
    assert set(spans) == {
        "rag.http.request",
        "rag.answer",
        "rag.retrieval",
        "rag.embedding",
        "rag.qdrant.dense",
        "rag.qdrant.sparse",
        "rag.fusion",
        "rag.generation",
    }
    root = spans["rag.http.request"]
    answer = spans["rag.answer"]
    assert root.parent is None
    assert answer.parent.span_id == root.context.span_id
    assert spans["rag.retrieval"].parent.span_id == answer.context.span_id
    assert spans["rag.generation"].parent.span_id == answer.context.span_id
    assert all(
        span.attributes.get("request_id") == request_id
        for span in spans.values()
    )
    assert all("question" not in span.attributes for span in spans.values())

    raw_log = stream.getvalue()
    for secret in (
        QUESTION_SECRET,
        EVIDENCE_SECRET,
        ANSWER_SECRET,
        API_KEY_SECRET,
        ABSOLUTE_PATH_SECRET,
    ):
        assert secret not in raw_log
    events = [json.loads(line) for line in raw_log.splitlines()]
    assert events
    assert all(event["request_id"] == request_id for event in events)
    assert all(set(event).isdisjoint(
        {"question", "evidence", "answer", "api_key", "absolute_path"}
    ) for event in events)

    metrics = metric_records(metric_reader)
    assert metrics["rag.http.server.requests"][0].value == 1
    assert metrics["rag.answers"][0].value == 1
    token_points = {
        point.attributes["kind"]: point.value
        for point in metrics["rag.model.tokens"]
    }
    assert token_points == {"prompt": 12, "completion": 3}
    assert all(
        set(point.attributes).isdisjoint(
            {"question", "chunk_id", "index_id", "build_id"}
        )
        for points in metrics.values()
        for point in points
    )


def test_invalid_request_is_correlated_without_body_echo() -> None:
    telemetry, span_exporter, metric_reader, stream = (
        make_in_memory_observability()
    )
    application = create_app(
        application_factory=FakeObservedApplication,
        readiness_probe=lambda: None,
        observability=telemetry,
    )

    response = request(
        application,
        "POST",
        "/v1/answers",
        json={"schema_version": "2", "question": QUESTION_SECRET},
    )

    assert response.status_code == 422
    request_id = response.headers["X-Request-ID"]
    spans = span_exporter.get_finished_spans()
    assert [span.name for span in spans] == ["rag.http.request"]
    assert spans[0].attributes["request_id"] == request_id
    assert spans[0].attributes["http_status"] == 422
    assert spans[0].status.status_code.name == "ERROR"
    assert QUESTION_SECRET not in stream.getvalue()
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert events[-1]["error_code"] == "request_validation_failed"
    metrics = metric_records(metric_reader)
    error_point = metrics["rag.errors"][0]
    assert error_point.value == 1
    assert error_point.attributes == {
        "stage": "http",
        "error_code": "request_validation_failed",
    }


def test_retry_metrics_count_physical_attempts_and_safe_reason() -> None:
    telemetry, _span_exporter, metric_reader, stream = (
        make_in_memory_observability()
    )

    telemetry.record_model_attempt(
        attempt=1,
        outcome="error",
        retry_reason="server_error",
        retry_delay_ms=250,
        billing_uncertain=True,
    )
    telemetry.record_model_attempt(attempt=2, outcome="success")
    telemetry.record_model_completed(
        outcome="success",
        prompt_tokens=12,
        completion_tokens=3,
    )

    metrics = metric_records(metric_reader)
    call_points = {
        (point.attributes["attempt"], point.attributes["outcome"]): (
            point.value
        )
        for point in metrics["rag.model.calls"]
    }
    assert call_points == {(1, "error"): 1, (2, "success"): 1}
    retry_point = metrics["rag.model.retries"][0]
    assert retry_point.value == 1
    assert retry_point.attributes == {"reason": "server_error"}
    token_points = {
        point.attributes["kind"]: point.value
        for point in metrics["rag.model.tokens"]
    }
    assert token_points == {"prompt": 12, "completion": 3}

    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    attempt_events = [
        item for item in events if item["event"] == "rag.model.attempt"
    ]
    assert attempt_events[0]["attempt"] == 1
    assert attempt_events[0]["max_attempts"] == 2
    assert attempt_events[0]["retry_reason"] == "server_error"
    assert attempt_events[0]["retry_delay_ms"] == 250
    assert attempt_events[0]["billing_uncertain"] is True
    assert attempt_events[1]["attempt"] == 2
    assert "retry_reason" not in attempt_events[1]


class FailingTracer:
    def start_as_current_span(self, *args, **kwargs):
        raise RuntimeError("telemetry unavailable")


class FailingInstrument:
    def add(self, *args, **kwargs):
        raise RuntimeError("telemetry unavailable")

    def record(self, *args, **kwargs):
        raise RuntimeError("telemetry unavailable")


class FailingMeter:
    def create_counter(self, *args, **kwargs):
        return FailingInstrument()

    def create_histogram(self, *args, **kwargs):
        return FailingInstrument()


def test_telemetry_failure_does_not_change_business_response() -> None:
    telemetry = Observability(
        tracer=FailingTracer(),
        meter=FailingMeter(),
        logger=build_json_logger(stream=StringIO()),
    )
    application = create_app(
        application_factory=FakeObservedApplication,
        readiness_probe=lambda: None,
        observability=telemetry,
    )

    response = request(
        application,
        "POST",
        "/v1/answers",
        json={"schema_version": "1", "question": QUESTION_SECRET},
    )

    assert response.status_code == 200
    assert response.json()["result"]["status"] == "refused"
