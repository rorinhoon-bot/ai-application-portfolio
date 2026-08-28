"""Provider-neutral answer model boundary."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnswerModelRequest(ModelContract):
    """Prompt material passed to a model adapter."""

    system_prompt: str = Field(min_length=1)
    user_payload: dict[str, Any]
    response_schema: dict[str, Any]


RetryReason = Literal[
    "rate_limit",
    "server_error",
    "connect_error",
    "connect_timeout",
    "pool_timeout",
]


class AnswerModelAttempt(ModelContract):
    """One physical provider call, safe for logs and metrics."""

    attempt: int = Field(ge=1, le=2)
    outcome: Literal["success", "error"]
    retry_reason: RetryReason | None = None
    retry_delay_ms: int | None = Field(default=None, ge=0, le=2000)
    billing_uncertain: bool = False

    @model_validator(mode="after")
    def validate_retry_schedule(self) -> "AnswerModelAttempt":
        if self.retry_reason is None:
            if self.retry_delay_ms is not None:
                raise ValueError(
                    "retry delay requires a retry reason"
                )
            return self
        if self.outcome != "error" or self.attempt != 1:
            raise ValueError(
                "only the first failed attempt may schedule a retry"
            )
        if self.retry_delay_ms is None:
            raise ValueError("retry reason requires a retry delay")
        return self


class AnswerModelResponse(ModelContract):
    """Provider text plus optional billing-token evidence."""

    content: str
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    attempts: tuple[AnswerModelAttempt, ...] = ()

    @model_validator(mode="after")
    def validate_attempts(self) -> "AnswerModelResponse":
        if not self.attempts:
            return self
        if tuple(item.attempt for item in self.attempts) != tuple(
            range(1, len(self.attempts) + 1)
        ):
            raise ValueError("model attempts must be contiguous")
        if self.attempts[-1].outcome != "success":
            raise ValueError("model response requires a successful attempt")
        if any(
            item.retry_reason is None
            for item in self.attempts[:-1]
        ):
            raise ValueError(
                "each prior failed attempt must schedule the next attempt"
            )
        return self


class AnswerModelClient(Protocol):
    def generate(self, request: AnswerModelRequest) -> AnswerModelResponse:
        ...
