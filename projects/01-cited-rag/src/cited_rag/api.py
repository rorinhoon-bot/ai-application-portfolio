"""Read-only FastAPI boundary for the validated Cited RAG service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Protocol
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHttpException

from cited_rag.api_models import (
    AnswerRequest,
    AnswerResponse,
    HealthResponse,
    ProblemDetails,
    ReadinessChecks,
    ReadinessResponse,
)
from cited_rag.cli import build_local_application
from cited_rag.errors import (
    CitedRagError,
    EmbeddingError,
    EmbeddingInputTooLongError,
    IndexConsistencyError,
    IndexVersionMismatchError,
    InvalidCitationIdError,
    InvalidModelJsonError,
    ModelHttpError,
    ModelNetworkError,
    ModelOutputError,
    ModelTimeoutError,
    RetrievalError,
    RetrievalInputError,
    VectorDimensionMismatchError,
    VectorValueInvalidError,
)
from cited_rag.models import AnswerResult, PythonVersion
from cited_rag.observability import (
    Observability,
    bind_observability,
    build_observability_from_env,
)

REQUEST_ID_HEADER = "X-Request-ID"
PROBLEM_BASE = "https://portfolio.local/problems"


class ApiApplication(Protocol):
    """Minimum service surface used by the HTTP boundary."""

    def answer(
        self,
        *,
        question: str,
        python_version: PythonVersion | None = None,
    ) -> AnswerResult:
        ...

    def check_ready(self) -> None:
        ...


ApplicationFactory = Callable[[], ApiApplication]
ReadinessProbe = Callable[[], None]


@dataclass(frozen=True, slots=True)
class _ProblemSpec:
    slug: str
    title: str
    status: int
    detail: str
    code: str


_REQUEST_VALIDATION_FAILED = _ProblemSpec(
    slug="request-validation-failed",
    title="Request validation failed",
    status=422,
    detail="The request body or parameters are invalid.",
    code="request_validation_failed",
)
_SERVICE_NOT_READY = _ProblemSpec(
    slug="service-not-ready",
    title="Service is not ready",
    status=503,
    detail="The local retrieval service is unavailable.",
    code="service_not_ready",
)
_MODEL_UPSTREAM_FAILED = _ProblemSpec(
    slug="model-upstream-failed",
    title="Model upstream failed",
    status=502,
    detail="The model upstream did not return a valid answer.",
    code="model_upstream_failed",
)
_MODEL_UPSTREAM_TIMEOUT = _ProblemSpec(
    slug="model-upstream-timeout",
    title="Model upstream timed out",
    status=504,
    detail="The model upstream exceeded its configured timeout.",
    code="model_upstream_timeout",
)
_INTERNAL_ERROR = _ProblemSpec(
    slug="internal-error",
    title="Internal server error",
    status=500,
    detail="The request could not be completed safely.",
    code="internal_error",
)
_NOT_FOUND = _ProblemSpec(
    slug="not-found",
    title="API route not found",
    status=404,
    detail="The requested API route does not exist.",
    code="not_found",
)
_METHOD_NOT_ALLOWED = _ProblemSpec(
    slug="method-not-allowed",
    title="Method not allowed",
    status=405,
    detail="The HTTP method is not allowed for this route.",
    code="method_not_allowed",
)


class _ServiceNotReadyError(RuntimeError):
    """Internal marker that never exposes its original exception."""


class _LazyApplicationProvider:
    """Create one heavy local application only when readiness or answer asks."""

    def __init__(self, factory: ApplicationFactory) -> None:
        self._factory = factory
        self._application: ApiApplication | None = None
        self._lock = Lock()

    def get(self) -> ApiApplication:
        application = self._application
        if application is not None:
            return application
        with self._lock:
            application = self._application
            if application is None:
                application = self._factory()
                if application is None:
                    raise TypeError("application factory returned None")
                self._application = application
        return application


def create_app(
    *,
    application_factory: ApplicationFactory = build_local_application,
    readiness_probe: ReadinessProbe | None = None,
    observability: Observability | None = None,
) -> FastAPI:
    """Create one API without initializing local models or indexes."""

    provider = _LazyApplicationProvider(application_factory)
    probe = readiness_probe or (
        lambda: provider.get().check_ready()
    )
    telemetry = observability or build_observability_from_env()
    owns_telemetry = observability is None

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        yield
        if owns_telemetry:
            telemetry.shutdown()

    application = FastAPI(
        title="Cited RAG API",
        version="0.2.0",
        description=(
            "Read-only, evidence-constrained Python documentation answers."
        ),
        redoc_url=None,
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = uuid4()
        started = perf_counter()
        route = _route_template(request.url.path)
        with bind_observability(
            telemetry,
            request_id=_request_id(request),
        ):
            with telemetry.stage(
                "rag.http.request",
                stage="http",
                attributes={
                    "route": route,
                    "method": request.method,
                },
                record_duration=False,
            ):
                try:
                    response = await call_next(request)
                except Exception:
                    response = _problem_response(
                        request,
                        _INTERNAL_ERROR,
                    )
                response.headers[REQUEST_ID_HEADER] = str(
                    _request_id(request)
                )
                telemetry.record_http(
                    route=route,
                    method=request.method,
                    status=response.status_code,
                    duration_ms=(perf_counter() - started) * 1000,
                    error_code=getattr(
                        request.state,
                        "error_code",
                        None,
                    ),
                )
                return response

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return _problem_response(request, _REQUEST_VALIDATION_FAILED)

    @application.exception_handler(_ServiceNotReadyError)
    async def handle_not_ready(
        request: Request,
        _error: _ServiceNotReadyError,
    ) -> JSONResponse:
        return _problem_response(request, _SERVICE_NOT_READY)

    @application.exception_handler(CitedRagError)
    async def handle_domain_error(
        request: Request,
        error: CitedRagError,
    ) -> JSONResponse:
        return _problem_response(request, _domain_problem(error))

    @application.exception_handler(StarletteHttpException)
    async def handle_http_error(
        request: Request,
        error: StarletteHttpException,
    ) -> JSONResponse:
        if error.status_code == 404:
            problem = _NOT_FOUND
        elif error.status_code == 405:
            problem = _METHOD_NOT_ALLOWED
        else:
            problem = _ProblemSpec(
                slug="http-error",
                title="HTTP request failed",
                status=error.status_code,
                detail="The HTTP request could not be completed.",
                code="http_error",
            )
        response = _problem_response(request, problem)
        if (
            error.status_code == 405
            and error.headers is not None
            and "Allow" in error.headers
        ):
            response.headers["Allow"] = error.headers["Allow"]
        return response

    @application.get(
        "/healthz",
        response_model=HealthResponse,
        responses={500: _problem_openapi("Internal server error")},
        tags=["operations"],
    )
    def health() -> HealthResponse:
        return HealthResponse()

    @application.get(
        "/readyz",
        response_model=ReadinessResponse,
        responses={
            500: _problem_openapi("Internal server error"),
            503: _problem_openapi("Service unavailable"),
        },
        tags=["operations"],
    )
    def ready() -> ReadinessResponse:
        try:
            probe()
        except Exception as error:
            raise _ServiceNotReadyError from error
        return ReadinessResponse(checks=ReadinessChecks())

    @application.post(
        "/v1/answers",
        response_model=AnswerResponse,
        responses={
            422: _problem_openapi("Request validation failed"),
            500: _problem_openapi("Internal server error"),
            502: _problem_openapi("Model upstream failed"),
            503: _problem_openapi("Service unavailable"),
            504: _problem_openapi("Model upstream timed out"),
        },
        tags=["answers"],
    )
    def answer(
        payload: AnswerRequest,
        request: Request,
    ) -> AnswerResponse:
        try:
            service = provider.get()
        except Exception as error:
            raise _ServiceNotReadyError from error
        result = service.answer(
            question=payload.question,
            python_version=payload.python_version,
        )
        if (
            not isinstance(result, AnswerResult)
            or result.question != payload.question
        ):
            raise RuntimeError("application returned a mismatched result")
        return AnswerResponse(
            request_id=_request_id(request),
            result=result,
        )

    return application


def _domain_problem(error: CitedRagError) -> _ProblemSpec:
    if isinstance(
        error,
        (RetrievalInputError, EmbeddingInputTooLongError),
    ):
        return _REQUEST_VALIDATION_FAILED
    if isinstance(error, ModelTimeoutError):
        return _MODEL_UPSTREAM_TIMEOUT
    if isinstance(
        error,
        (
            ModelNetworkError,
            ModelHttpError,
            InvalidModelJsonError,
            ModelOutputError,
            InvalidCitationIdError,
        ),
    ):
        return _MODEL_UPSTREAM_FAILED
    if isinstance(
        error,
        (
            EmbeddingError,
            IndexConsistencyError,
            IndexVersionMismatchError,
            RetrievalError,
            VectorDimensionMismatchError,
            VectorValueInvalidError,
        ),
    ):
        return _SERVICE_NOT_READY
    return _INTERNAL_ERROR


def _request_id(request: Request) -> UUID:
    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, UUID):
        request_id = uuid4()
        request.state.request_id = request_id
    return request_id


def _problem_response(
    request: Request,
    problem: _ProblemSpec,
) -> JSONResponse:
    request.state.error_code = problem.code
    body = ProblemDetails(
        type=f"{PROBLEM_BASE}/{problem.slug}",
        title=problem.title,
        status=problem.status,
        detail=problem.detail,
        code=problem.code,
        request_id=_request_id(request),
    )
    return JSONResponse(
        status_code=problem.status,
        content=body.model_dump(mode="json"),
        media_type="application/problem+json",
    )


def _route_template(path: str) -> str:
    if path in {
        "/healthz",
        "/readyz",
        "/v1/answers",
        "/openapi.json",
    }:
        return path
    return "unmatched"


def _problem_openapi(description: str) -> dict[str, object]:
    return {
        "description": description,
        "content": {
            "application/problem+json": {
                "schema": ProblemDetails.model_json_schema(),
            }
        },
    }


app = create_app()
