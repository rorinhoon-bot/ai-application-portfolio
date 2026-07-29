"""Provider-neutral answer model boundary."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ModelContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnswerModelRequest(ModelContract):
    """Prompt material passed to a model adapter."""

    system_prompt: str = Field(min_length=1)
    user_payload: dict[str, Any]
    response_schema: dict[str, Any]


class AnswerModelResponse(ModelContract):
    """Provider text plus optional billing-token evidence."""

    content: str
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class AnswerModelClient(Protocol):
    def generate(self, request: AnswerModelRequest) -> AnswerModelResponse:
        ...
