from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(StrEnum):
    INPUT_VALIDATION_ERROR = "INPUT_VALIDATION_ERROR"
    MATERIAL_FILE_ERROR = "MATERIAL_FILE_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"
    UNKNOWN_MODEL_PROVIDER = "UNKNOWN_MODEL_PROVIDER"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_NETWORK_ERROR = "MODEL_NETWORK_ERROR"
    MODEL_HTTP_ERROR = "MODEL_HTTP_ERROR"
    EMPTY_MODEL_RESPONSE = "EMPTY_MODEL_RESPONSE"
    INVALID_MODEL_JSON = "INVALID_MODEL_JSON"
    OUTPUT_SCHEMA_ERROR = "OUTPUT_SCHEMA_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ExitCode(IntEnum):
    SUCCESS = 0
    INTERNAL_ERROR = 1
    INPUT_OR_CONFIG_ERROR = 2
    MODEL_API_ERROR = 3
    MODEL_OUTPUT_ERROR = 4


class ErrorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str = Field(min_length=1)
    retryable: bool


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool,
        exit_code: ExitCode,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.exit_code = exit_code

    def to_payload(self) -> ErrorPayload:
        return ErrorPayload(
            code=self.code,
            message=self.message,
            retryable=self.retryable,
        )
