"""Privacy-safe structured logs and manual OpenTelemetry instruments."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
import json
import logging
import os
from time import perf_counter
from typing import IO, Any
from uuid import UUID

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

SERVICE_NAME = "cited-rag-api"
SERVICE_VERSION = "0.2.0"
SCHEMA_VERSION = "1"
DEFAULT_OTLP_ENDPOINT = "http://otel-collector:4318"

_LOG_FIELDS = frozenset(
    {
        "schema_version",
        "timestamp",
        "severity",
        "event",
        "service",
        "service_version",
        "request_id",
        "trace_id",
        "span_id",
        "route",
        "method",
        "http_status",
        "duration_ms",
        "stage",
        "outcome",
        "error_code",
        "answer_status",
        "candidate_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "index_id",
        "build_id",
        "attempt",
        "max_attempts",
        "retry_reason",
        "retry_delay_ms",
        "billing_uncertain",
    }
)
_SPAN_FIELDS = frozenset(
    {
        "request_id",
        "route",
        "method",
        "http_status",
        "stage",
        "outcome",
        "error_code",
        "answer_status",
        "candidate_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "index_id",
        "build_id",
        "python_version",
        "attempt",
        "max_attempts",
        "retry_reason",
        "retry_delay_ms",
        "billing_uncertain",
    }
)

_CURRENT_OBSERVABILITY: ContextVar[Observability | None] = ContextVar(
    "cited_rag_observability",
    default=None,
)
_CURRENT_REQUEST_ID: ContextVar[str | None] = ContextVar(
    "cited_rag_request_id",
    default=None,
)


class _JsonEventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "telemetry_event", {})
        if not isinstance(event, dict):
            event = {}
        safe = {
            key: _json_value(value)
            for key, value in event.items()
            if key in _LOG_FIELDS and value is not None
        }
        return json.dumps(
            safe,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def build_json_logger(*, stream: IO[str] | None = None) -> logging.Logger:
    """Build an isolated stdout logger that only serializes allowlisted fields."""

    logger = logging.Logger("cited_rag.telemetry", level=logging.INFO)
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_JsonEventFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


class Observability:
    """Small failure-isolated facade over logs, traces, and metrics."""

    def __init__(
        self,
        *,
        tracer: Any | None = None,
        meter: Any | None = None,
        logger: logging.Logger | None = None,
        tracer_provider: Any | None = None,
        meter_provider: Any | None = None,
    ) -> None:
        self._tracer = tracer or trace.get_tracer(
            "cited_rag",
            SERVICE_VERSION,
        )
        self._meter = meter or metrics.get_meter(
            "cited_rag",
            SERVICE_VERSION,
        )
        self._logger = logger or build_json_logger()
        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._http_requests = self._meter.create_counter(
            "rag.http.server.requests",
            description="Completed HTTP requests.",
        )
        self._http_duration = self._meter.create_histogram(
            "rag.http.server.duration",
            unit="ms",
            description="HTTP request duration.",
        )
        self._stage_duration = self._meter.create_histogram(
            "rag.stage.duration",
            unit="ms",
            description="RAG stage duration.",
        )
        self._retrieval_candidates = self._meter.create_histogram(
            "rag.retrieval.candidates",
            description="Retrieval candidate count.",
        )
        self._answers = self._meter.create_counter(
            "rag.answers",
            description="Validated answer outcomes.",
        )
        self._errors = self._meter.create_counter(
            "rag.errors",
            description="Safe error categories.",
        )
        self._model_calls = self._meter.create_counter(
            "rag.model.calls",
            description="Physical model HTTP attempts by outcome.",
        )
        self._model_retries = self._meter.create_counter(
            "rag.model.retries",
            description="Scheduled model retries by safe reason.",
        )
        self._model_tokens = self._meter.create_counter(
            "rag.model.tokens",
            description="Model token usage.",
        )

    @contextmanager
    def stage(
        self,
        name: str,
        *,
        stage: str,
        attributes: Mapping[str, object] | None = None,
        record_duration: bool = True,
    ) -> Iterator[None]:
        """Create one safe span; exporter failure cannot change business flow."""

        started = perf_counter()
        outcome = "success"
        span = None
        scope = None
        span_attributes = _safe_attributes(attributes or {})
        request_id = _CURRENT_REQUEST_ID.get()
        if request_id is not None:
            span_attributes["request_id"] = request_id
        span_attributes["stage"] = stage
        try:
            scope = self._tracer.start_as_current_span(
                name,
                attributes=span_attributes,
                record_exception=False,
                set_status_on_exception=False,
            )
            span = scope.__enter__()
        except Exception:
            scope = None
            span = None
        try:
            yield
        except BaseException:
            outcome = "error"
            if span is not None:
                _safe_call(span.set_attribute, "outcome", outcome)
                _safe_call(span.set_status, Status(StatusCode.ERROR))
            raise
        finally:
            duration_ms = max(0.0, (perf_counter() - started) * 1000)
            if (
                span is not None
                and outcome == "success"
                and record_duration
            ):
                _safe_call(span.set_attribute, "outcome", outcome)
                _safe_call(span.set_status, Status(StatusCode.OK))
            if record_duration:
                _safe_call(
                    self._stage_duration.record,
                    duration_ms,
                    {"stage": stage, "outcome": outcome},
                )
                self.emit(
                    event="rag.stage.completed",
                    stage=stage,
                    outcome=outcome,
                    duration_ms=round(duration_ms, 3),
                )
            if scope is not None:
                try:
                    scope.__exit__(None, None, None)
                except Exception:
                    self.emit(
                        event="telemetry.export.failed",
                        stage="telemetry",
                        outcome="error",
                        error_code="telemetry_export_failed",
                    )

    def record_http(
        self,
        *,
        route: str,
        method: str,
        status: int,
        duration_ms: float,
        error_code: str | None = None,
    ) -> None:
        outcome = "success" if status < 400 else "error"
        status_class = f"{status // 100}xx"
        current_span = trace.get_current_span()
        _safe_call(current_span.set_attribute, "http_status", status)
        _safe_call(current_span.set_attribute, "outcome", outcome)
        _safe_call(
            current_span.set_status,
            Status(
                StatusCode.OK
                if outcome == "success"
                else StatusCode.ERROR
            ),
        )
        metric_attributes = {
            "route": route,
            "method": method,
            "status_class": status_class,
        }
        _safe_call(self._http_requests.add, 1, metric_attributes)
        _safe_call(
            self._http_duration.record,
            max(0.0, duration_ms),
            {"route": route, "method": method, "outcome": outcome},
        )
        if error_code is not None:
            self.record_error(stage="http", error_code=error_code)
        self.emit(
            event="http.request.completed",
            route=route,
            method=method,
            http_status=status,
            duration_ms=round(max(0.0, duration_ms), 3),
            outcome=outcome,
            error_code=error_code,
        )

    def record_candidates(self, *, source: str, count: int) -> None:
        if source not in {"dense", "sparse", "fused"}:
            return
        _safe_call(
            self._retrieval_candidates.record,
            max(0, count),
            {"source": source},
        )

    def record_answer(
        self,
        *,
        status: str,
        index_id: UUID,
        build_id: UUID,
    ) -> None:
        if status not in {"answered", "refused", "conflict"}:
            return
        _safe_call(self._answers.add, 1, {"status": status})
        self.emit(
            event="rag.answer.completed",
            stage="answer",
            outcome="success",
            answer_status=status,
            index_id=index_id,
            build_id=build_id,
        )

    def record_model_call(
        self,
        *,
        outcome: str,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        """Compatibility helper for one-attempt model clients."""

        self.record_model_attempt(attempt=1, outcome=outcome)
        self.record_model_completed(
            outcome=outcome,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def record_model_attempt(
        self,
        *,
        attempt: int,
        outcome: str,
        retry_reason: str | None = None,
        retry_delay_ms: int | None = None,
        billing_uncertain: bool = False,
    ) -> None:
        """Record one physical provider call and an optional scheduled retry."""

        if attempt not in {1, 2} or outcome not in {"success", "error"}:
            return
        allowed_reasons = {
            "rate_limit",
            "server_error",
            "connect_error",
            "connect_timeout",
            "pool_timeout",
        }
        if retry_reason not in allowed_reasons:
            retry_reason = None
            retry_delay_ms = None
        elif retry_delay_ms is None or not 0 <= retry_delay_ms <= 2000:
            return
        attributes = {"outcome": outcome, "attempt": attempt}
        _safe_call(self._model_calls.add, 1, attributes)
        if retry_reason is not None:
            _safe_call(
                self._model_retries.add,
                1,
                {"reason": retry_reason},
            )
        self.emit(
            event="rag.model.attempt",
            stage="generation",
            outcome=outcome,
            attempt=attempt,
            max_attempts=2,
            retry_reason=retry_reason,
            retry_delay_ms=retry_delay_ms,
            billing_uncertain=billing_uncertain,
        )

    def record_model_completed(
        self,
        *,
        outcome: str,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        """Record one logical model request and only known final usage."""

        if outcome not in {"success", "error"}:
            return
        for kind, value in (
            ("prompt", prompt_tokens),
            ("completion", completion_tokens),
        ):
            if value is not None:
                _safe_call(
                    self._model_tokens.add,
                    value,
                    {"kind": kind},
                )
        self.emit(
            event="rag.model.completed",
            stage="generation",
            outcome=outcome,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=(
                prompt_tokens + completion_tokens
                if prompt_tokens is not None
                and completion_tokens is not None
                else None
            ),
        )

    def record_error(self, *, stage: str, error_code: str) -> None:
        _safe_call(
            self._errors.add,
            1,
            {"stage": stage, "error_code": error_code},
        )

    def emit(self, *, event: str, **fields: object) -> None:
        context = _trace_context()
        payload: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "timestamp": datetime.now(UTC).isoformat(),
            "severity": (
                "ERROR" if fields.get("outcome") == "error" else "INFO"
            ),
            "event": event,
            "service": SERVICE_NAME,
            "service_version": SERVICE_VERSION,
            "request_id": _CURRENT_REQUEST_ID.get(),
            **context,
            **fields,
        }
        safe = {
            key: value
            for key, value in payload.items()
            if key in _LOG_FIELDS and value is not None
        }
        try:
            self._logger.info("", extra={"telemetry_event": safe})
        except Exception:
            pass

    def shutdown(self, *, timeout_millis: int = 2000) -> None:
        """Bounded best-effort flush for API process shutdown."""

        if self._tracer_provider is not None:
            _safe_call(
                self._tracer_provider.force_flush,
                timeout_millis=timeout_millis,
            )
            _safe_call(self._tracer_provider.shutdown)
        if self._meter_provider is not None:
            _safe_call(
                self._meter_provider.force_flush,
                timeout_millis=timeout_millis,
            )
            _safe_call(
                self._meter_provider.shutdown,
                timeout_millis=timeout_millis,
            )


@contextmanager
def bind_observability(
    observability: Observability,
    *,
    request_id: UUID | str | None = None,
) -> Iterator[Observability]:
    observation_token = _CURRENT_OBSERVABILITY.set(observability)
    request_token = _CURRENT_REQUEST_ID.set(
        str(request_id) if request_id is not None else None
    )
    try:
        yield observability
    finally:
        _CURRENT_REQUEST_ID.reset(request_token)
        _CURRENT_OBSERVABILITY.reset(observation_token)


def current_observability() -> Observability:
    current = _CURRENT_OBSERVABILITY.get()
    return current if current is not None else _NOOP_OBSERVABILITY


def build_observability_from_env() -> Observability:
    """Create JSON logging always; enable OTLP only by explicit environment."""

    logger = build_json_logger()
    if os.getenv("OTEL_ENABLED", "false").strip().lower() != "true":
        return Observability(logger=logger)

    endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        DEFAULT_OTLP_ENDPOINT,
    ).rstrip("/")
    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": SERVICE_VERSION,
        }
    )
    tracer_provider = TracerProvider(
        resource=resource,
        shutdown_on_exit=False,
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=f"{endpoint}/v1/traces",
                timeout=2,
            ),
            max_queue_size=512,
            max_export_batch_size=128,
            schedule_delay_millis=1000,
            export_timeout_millis=2000,
        )
    )
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(
            endpoint=f"{endpoint}/v1/metrics",
            timeout=2,
        ),
        export_interval_millis=10000,
        export_timeout_millis=2000,
    )
    meter_provider = MeterProvider(
        metric_readers=(metric_reader,),
        resource=resource,
        shutdown_on_exit=False,
    )
    return Observability(
        tracer=tracer_provider.get_tracer("cited_rag", SERVICE_VERSION),
        meter=meter_provider.get_meter("cited_rag", SERVICE_VERSION),
        logger=logger,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
    )


def _trace_context() -> dict[str, str]:
    try:
        context = trace.get_current_span().get_span_context()
        if not context.is_valid:
            return {}
        return {
            "trace_id": format(context.trace_id, "032x"),
            "span_id": format(context.span_id, "016x"),
        }
    except Exception:
        return {}


def _safe_attributes(values: Mapping[str, object]) -> dict[str, Any]:
    return {
        key: _attribute_value(value)
        for key, value in values.items()
        if key in _SPAN_FIELDS and value is not None
    }


def _attribute_value(value: object) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _json_value(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _safe_call(function, *args, **kwargs) -> None:
    try:
        function(*args, **kwargs)
    except Exception:
        pass


_NOOP_OBSERVABILITY = Observability(
    logger=logging.Logger("cited_rag.telemetry.noop"),
)
