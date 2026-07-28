import pytest
from pydantic import ValidationError

from structured_notes.errors import AppError, ErrorCode, ErrorPayload, ExitCode


def test_app_error_builds_stable_payload() -> None:
    error = AppError(
        ErrorCode.INVALID_MODEL_JSON,
        "模型返回内容不是合法 JSON。",
        retryable=False,
        exit_code=ExitCode.MODEL_OUTPUT_ERROR,
    )

    assert error.exit_code is ExitCode.MODEL_OUTPUT_ERROR
    assert error.to_payload().model_dump(mode="json") == {
        "code": "INVALID_MODEL_JSON",
        "message": "模型返回内容不是合法 JSON。",
        "retryable": False,
    }


def test_error_payload_rejects_unknown_code() -> None:
    with pytest.raises(ValidationError):
        ErrorPayload(
            code="UNKNOWN_CODE",
            message="未知错误。",
            retryable=False,
        )


def test_error_payload_rejects_extra_field() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ErrorPayload.model_validate(
            {
                "code": "INTERNAL_ERROR",
                "message": "内部错误。",
                "retryable": False,
                "details": "hidden",
            }
        )

    assert exc_info.value.errors()[0]["type"] == "extra_forbidden"
