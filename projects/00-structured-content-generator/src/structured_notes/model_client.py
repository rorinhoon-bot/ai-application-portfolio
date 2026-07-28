from typing import Protocol

from structured_notes.models import ModelRequest, ModelResponse


class ModelClient(Protocol):
    def generate(self, request: ModelRequest) -> ModelResponse:
        ...


class ModelClientError(Exception):
    """Base error raised by a provider adapter."""


class ModelTimeoutError(ModelClientError):
    """The provider request exceeded its timeout."""


class ModelNetworkError(ModelClientError):
    """The provider request failed before receiving an HTTP response."""


class ModelHttpError(ModelClientError):
    """The provider returned a non-success HTTP status."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"Model API returned HTTP {status_code}")
        self.status_code = status_code
