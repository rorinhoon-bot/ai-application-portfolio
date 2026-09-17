"""V2 durable call ledger tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_research.v2.contracts import CallStatus, CostStatus, Usage
from agent_research.v2.ledger import LedgerError, OperationLedger


def test_ledger_reserves_replays_success_and_keeps_payload(tmp_path: Path) -> None:
    with OperationLedger(tmp_path / "operations.sqlite3") as ledger:
        record = ledger.reserve(
            logical_call_key="a" * 64,
            run_id="run-v2",
            node="plan",
            provider="scripted-offline",
            model_id="scripted-v2",
            request_hash="b" * 64,
        )
        assert record.status is CallStatus.RESERVED
        ledger.mark_dispatched("a" * 64)
        ledger.record_success(
            logical_call_key="a" * 64,
            response_hash="c" * 64,
            response_payload={"task": "plan", "answer": "free-form"},
            usage=Usage(cost_status=CostStatus.NOT_APPLICABLE),
        )
        replay = ledger.reserve(
            logical_call_key="a" * 64,
            run_id="run-v2",
            node="plan",
            provider="scripted-offline",
            model_id="scripted-v2",
            request_hash="b" * 64,
        )
        assert replay.status is CallStatus.SUCCEEDED
        assert ledger.cached_response("a" * 64) == '{"answer":"free-form","task":"plan"}'


def test_dispatched_failure_is_unknown_and_not_retried(tmp_path: Path) -> None:
    with OperationLedger(tmp_path / "operations.sqlite3") as ledger:
        ledger.reserve(
            logical_call_key="d" * 64,
            run_id="run-v2",
            node="draft",
            provider="deepseek",
            model_id="deepseek-v4-flash",
            request_hash="e" * 64,
        )
        ledger.mark_dispatched("d" * 64)
        record = ledger.record_failure(
            logical_call_key="d" * 64,
            error_code="MODEL_CALL_UNKNOWN",
            unknown=True,
        )
        assert record.status is CallStatus.UNKNOWN
        with pytest.raises(LedgerError, match="LEDGER_INVALID_TRANSITION"):
            ledger.mark_dispatched("d" * 64)
