"""Run deterministic V2-D3 retry smoke with no network or real waiting."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
import sys
from typing import Literal, NoReturn

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from cited_rag.adapters.mimo import (  # noqa: E402
    DEFAULT_RETRY_DELAY_SECONDS,
    MAX_ATTEMPTS,
    MAX_RETRY_DELAY_SECONDS,
    RETRYABLE_HTTP_STATUSES,
    MiMoClient,
)
from cited_rag.answering import parse_model_answer  # noqa: E402
from cited_rag.config import Settings  # noqa: E402
from cited_rag.errors import CitedRagError  # noqa: E402
from cited_rag.model_client import (  # noqa: E402
    AnswerModelRequest,
    AnswerModelResponse,
)

DATA_ROOT = PROJECT_ROOT / "data"


class SmokeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RetryScenarioResult(SmokeContract):
    name: str
    outcome: Literal["success", "error"]
    error_code: str | None = None
    physical_attempt_count: int = Field(ge=1, le=2)
    retry_count: int = Field(ge=0, le=1)
    retry_delays_ms: tuple[int, ...]
    usage_complete: bool
    billing_uncertain_attempts: int = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_counts(self) -> "RetryScenarioResult":
        if self.retry_count != len(self.retry_delays_ms):
            raise ValueError("retry count must match recorded delays")
        if self.physical_attempt_count != self.retry_count + 1:
            raise ValueError("physical attempts must equal retries plus one")
        return self


class RetrySmokeReport(SmokeContract):
    schema_version: Literal["1"] = "1"
    slice: Literal["V2-D3"] = "V2-D3"
    status: Literal["fake-verified"] = "fake-verified"
    max_attempts: Literal[2] = 2
    retryable_http_statuses: tuple[int, ...]
    default_retry_delay_ms: Literal[250] = 250
    maximum_retry_delay_ms: Literal[2000] = 2000
    scenarios: tuple[RetryScenarioResult, ...]
    external_side_effects: dict[str, bool]

    @model_validator(mode="after")
    def validate_report(self) -> "RetrySmokeReport":
        if tuple(sorted(RETRYABLE_HTTP_STATUSES)) != (
            self.retryable_http_statuses
        ):
            raise ValueError("retryable HTTP status contract changed")
        if len(self.scenarios) != 5:
            raise ValueError("retry smoke requires five scenarios")
        if any(self.external_side_effects.values()):
            raise ValueError("retry smoke must have no external side effects")
        return self


def settings() -> Settings:
    return Settings(
        _env_file=None,
        model_provider="mimo",
        model_api_key="fake-only-key",
        model_base_url="https://api.xiaomimimo.com/v1",
        model_name="mimo-v2.5",
        model_timeout_seconds=30,
    )


def request() -> AnswerModelRequest:
    return AnswerModelRequest(
        system_prompt="只返回 JSON。",
        user_payload={"question": "离线测试", "evidence": []},
        response_schema={"type": "object"},
    )


def success_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"schema_version":"1","status":"refused"}'
                        )
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12,
            },
        },
    )


def run_success_sequence(
    *,
    name: str,
    first: httpx.Response | Exception,
) -> RetryScenarioResult:
    calls = 0
    delays: list[float] = []

    def fake_post(url: str, **_kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            if isinstance(first, Exception):
                raise first
            return first
        return success_response()

    response = MiMoClient(
        settings(),
        post=fake_post,
        clock=lambda: 0.0,
        sleeper=delays.append,
    ).generate(request())
    return _success_result(name=name, response=response, delays=delays)


def run_error_sequence(
    *,
    name: str,
    post: Callable[..., httpx.Response],
) -> RetryScenarioResult:
    delays: list[float] = []
    try:
        MiMoClient(
            settings(),
            post=post,
            clock=lambda: 0.0,
            sleeper=delays.append,
        ).generate(request())
    except CitedRagError as error:
        attempts = error.model_attempts
        return RetryScenarioResult(
            name=name,
            outcome="error",
            error_code=error.code,
            physical_attempt_count=len(attempts),
            retry_count=sum(
                item.retry_reason is not None for item in attempts
            ),
            retry_delays_ms=tuple(round(item * 1000) for item in delays),
            usage_complete=False,
            billing_uncertain_attempts=sum(
                item.billing_uncertain for item in attempts
            ),
        )
    raise AssertionError("error smoke scenario unexpectedly succeeded")


def run_invalid_json() -> RetryScenarioResult:
    response = MiMoClient(
        settings(),
        post=lambda _url, **_kwargs: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        ),
        clock=lambda: 0.0,
        sleeper=lambda _delay: None,
    ).generate(request())
    try:
        parse_model_answer(response.content)
    except CitedRagError as error:
        return RetryScenarioResult(
            name="invalid_model_json",
            outcome="error",
            error_code=error.code,
            physical_attempt_count=len(response.attempts),
            retry_count=0,
            retry_delays_ms=(),
            usage_complete=False,
            billing_uncertain_attempts=0,
        )
    raise AssertionError("invalid JSON smoke unexpectedly succeeded")


def build_report() -> RetrySmokeReport:
    connect_request = httpx.Request(
        "POST",
        "https://api.xiaomimimo.com/v1/chat/completions",
    )
    read_request = httpx.Request(
        "POST",
        "https://api.xiaomimimo.com/v1/chat/completions",
    )
    exhausted_calls = 0

    def exhausted_post(_url: str, **_kwargs: object) -> httpx.Response:
        nonlocal exhausted_calls
        exhausted_calls += 1
        return httpx.Response(503 if exhausted_calls == 1 else 504)

    report = RetrySmokeReport(
        retryable_http_statuses=tuple(sorted(RETRYABLE_HTTP_STATUSES)),
        scenarios=(
            run_success_sequence(
                name="rate_limit_then_success",
                first=httpx.Response(
                    429,
                    headers={"Retry-After": "0.5"},
                ),
            ),
            run_success_sequence(
                name="connect_error_then_success",
                first=httpx.ConnectError(
                    "fake connect error",
                    request=connect_request,
                ),
            ),
            run_error_sequence(
                name="read_timeout_no_retry",
                post=lambda _url, **_kwargs: _raise(
                    httpx.ReadTimeout(
                        "fake read timeout",
                        request=read_request,
                    )
                ),
            ),
            run_error_sequence(
                name="server_errors_exhausted",
                post=exhausted_post,
            ),
            run_invalid_json(),
        ),
        external_side_effects={
            "network_accessed": False,
            "mimo_called": False,
            "qdrant_written": False,
            "docker_changed": False,
            "dependency_installed": False,
        },
    )
    assert MAX_ATTEMPTS == report.max_attempts
    assert round(DEFAULT_RETRY_DELAY_SECONDS * 1000) == (
        report.default_retry_delay_ms
    )
    assert round(MAX_RETRY_DELAY_SECONDS * 1000) == (
        report.maximum_retry_delay_ms
    )
    return report


def _success_result(
    *,
    name: str,
    response: AnswerModelResponse,
    delays: list[float],
) -> RetryScenarioResult:
    return RetryScenarioResult(
        name=name,
        outcome="success",
        physical_attempt_count=len(response.attempts),
        retry_count=sum(
            item.retry_reason is not None for item in response.attempts
        ),
        retry_delays_ms=tuple(round(item * 1000) for item in delays),
        usage_complete=response.total_tokens is not None,
        billing_uncertain_attempts=sum(
            item.billing_uncertain for item in response.attempts
        ),
    )


def _raise(error: Exception) -> NoReturn:
    raise error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report()
    payload = report.model_dump_json(indent=2) + "\n"
    if args.output is not None:
        output = args.output.resolve()
        data_root = DATA_ROOT.resolve()
        if output.parent != data_root or output.suffix.lower() != ".json":
            raise ValueError("output must be one JSON file in project data/")
        if output.exists():
            raise FileExistsError(f"refusing to overwrite report: {output}")
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
