"""Durable pre-send ceilings, including competing connections and crashes."""
from pathlib import Path

import pytest

from agent_research.v2.contracts import BudgetAuthorization
from agent_research.v2.ledger import OperationLedger, LedgerError


def budget(**changes):
    return BudgetAuthorization(authorization_id="budget-batch", approved=True,
        expires_at="2099-01-01T00:00:00Z", max_model_calls=2,
        max_input_tokens=200, max_output_tokens=100, max_cost_minor_units=10
    ).model_copy(update=changes)


def reserve(ledger, key="a", authorization=None, **changes):
    values = dict(input_tokens=100, output_tokens=50, cost_minor_units=5)
    ledger.reserve_budget(key=key * 64, budget=authorization or budget(), **(values | changes))


@pytest.mark.parametrize("field,value", [("max_model_calls", 1), ("max_input_tokens", 199),
    ("max_output_tokens", 99), ("max_cost_minor_units", 9)])
def test_second_connection_cannot_exceed_any_batch_limit(tmp_path: Path, field, value):
    path = tmp_path / "ledger.sqlite3"
    authorization = budget(**{field: value})
    with OperationLedger(path) as first, OperationLedger(path) as second:
        reserve(first, authorization=authorization)
        with pytest.raises(LedgerError, match="BUDGET_RESERVATION_EXHAUSTED"):
            reserve(second, "b", authorization=authorization)


def test_crash_reservation_is_not_refunded_or_resent(tmp_path: Path):
    path = tmp_path / "ledger.sqlite3"
    with OperationLedger(path) as ledger:
        reserve(ledger)
    with OperationLedger(path) as reopened:
        with pytest.raises(LedgerError, match="ALREADY_RESERVED_REQUIRES_REVIEW"):
            reserve(reopened)
        reserve(reopened, "b")
        with pytest.raises(LedgerError, match="BUDGET_RESERVATION_EXHAUSTED"):
            reserve(reopened, "c")


def test_same_authorization_cannot_be_enlarged(tmp_path: Path):
    with OperationLedger(tmp_path / "ledger.sqlite3") as ledger:
        reserve(ledger)
        with pytest.raises(LedgerError, match="BUDGET_AUTHORIZATION_CHANGED"):
            reserve(ledger, "b", authorization=budget(max_cost_minor_units=500))


def test_total_authorization_binding_survives_reopen_without_flag(tmp_path: Path):
    path = tmp_path / "total.sqlite3"
    with OperationLedger(path, single_authorization=True) as ledger:
        reserve(ledger)
    with OperationLedger(path) as reopened:
        with pytest.raises(LedgerError, match="TOTAL_BUDGET_AUTHORIZATION_CHANGED"):
            reserve(reopened, "b", authorization=budget(authorization_id="new-budget"))
        reserve(reopened, "c")
        with pytest.raises(LedgerError, match="BUDGET_RESERVATION_EXHAUSTED"):
            reserve(reopened, "d")


@pytest.mark.parametrize("expiry", ["2000-01-01T00:00:00Z", "2099-01-01T00:00:00", "invalid-date"])
def test_expired_or_ambiguous_authorization_never_reserves(tmp_path: Path, expiry):
    with OperationLedger(tmp_path / "ledger.sqlite3") as ledger:
        with pytest.raises(LedgerError, match="BUDGET_EXPIRED_OR_INVALID"):
            reserve(ledger, authorization=budget(expires_at=expiry))
