"""Strict HTTP-only contracts for the Cited RAG API."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cited_rag.models import AnswerResult, PythonVersion


class ApiContractModel(BaseModel):
    """Reject coercion and unknown fields at the HTTP boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AnswerRequest(ApiContractModel):
    """One public, read-only answer request."""

    schema_version: Literal["1"]
    question: Annotated[str, Field(min_length=1, max_length=500)]
    python_version: PythonVersion | None = None

    @field_validator("question")
    @classmethod
    def require_trimmed_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be empty")
        if value != value.strip():
            raise ValueError(
                "question must not have surrounding whitespace"
            )
        return value


class AnswerResponse(ApiContractModel):
    """Validated business result plus HTTP request identity."""

    schema_version: Literal["1"] = "1"
    request_id: UUID
    result: AnswerResult


class HealthResponse(ApiContractModel):
    """Process liveness response with no dependency checks."""

    status: Literal["ok"] = "ok"
    service: Literal["cited-rag-api"] = "cited-rag-api"


class ReadinessChecks(ApiContractModel):
    """Required local dependencies after one successful probe."""

    configuration: Literal["ok"] = "ok"
    index: Literal["ok"] = "ok"
    retriever: Literal["ok"] = "ok"


class ReadinessResponse(ApiContractModel):
    """Successful readiness response."""

    status: Literal["ready"] = "ready"
    service: Literal["cited-rag-api"] = "cited-rag-api"
    checks: ReadinessChecks


class ProblemDetails(ApiContractModel):
    """Safe RFC 9457-style API error body."""

    type: Annotated[str, Field(pattern=r"^https://portfolio\.local/problems/")]
    title: Annotated[str, Field(min_length=1, max_length=120)]
    status: Annotated[int, Field(ge=400, le=599)]
    detail: Annotated[str, Field(min_length=1, max_length=500)]
    code: Annotated[
        str,
        Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$"),
    ]
    request_id: UUID
