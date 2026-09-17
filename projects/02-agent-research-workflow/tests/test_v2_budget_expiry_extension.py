"""Deadline renewal requires an explicit record and never resets resource caps."""
from datetime import datetime, timezone

import pytest

from agent_research.v2 import ledger as module
from agent_research.v2.contracts import BudgetAuthorization
from agent_research.v2.ledger import LedgerError, OperationLedger


def expired_ledger(tmp_path, monkeypatch):
    class Past(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2019, 1, 1, tzinfo=timezone.utc)
    budget = BudgetAuthorization(authorization_id="renewal-test", max_cost_minor_units=4,
        max_model_calls=2, max_input_tokens=4, max_output_tokens=4,
        expires_at="2020-01-01T00:00:00Z", approved=True)
    ledger = OperationLedger(tmp_path / "budget.sqlite3", single_authorization=True)
    monkeypatch.setattr(module, "datetime", Past)
    ledger.reserve_budget(key="a" * 64, budget=budget, input_tokens=1, output_tokens=1, cost_minor_units=1)
    monkeypatch.setattr(module, "datetime", datetime)
    return ledger, budget


def test_expired_budget_only_resumes_after_explicit_extension_without_reset(tmp_path, monkeypatch):
    ledger, budget = expired_ledger(tmp_path, monkeypatch)
    with pytest.raises(LedgerError, match="EXPIRED"):
        ledger.reserve_budget(key="b" * 64, budget=budget, input_tokens=1, output_tokens=1, cost_minor_units=1)
    args = dict(budget=budget, expires_at="2099-01-01T00:00:00Z", approval_ref="user-test-confirmation")
    ledger.extend_budget_expiry(**args)
    ledger.extend_budget_expiry(**args)
    assert ledger._connection.execute("SELECT authorization_json FROM budget_reservations").fetchone()[0] == budget.model_dump_json()
    assert ledger._connection.execute("SELECT COUNT(*) FROM budget_expiry_extensions").fetchone()[0] == 1
    ledger.close()
    with OperationLedger(tmp_path / "budget.sqlite3") as reopened:
        with pytest.raises(LedgerError, match="EXHAUSTED"):
            reopened.reserve_budget(key="b" * 64, budget=budget, input_tokens=1, output_tokens=1, cost_minor_units=4)
        reopened.reserve_budget(key="b" * 64, budget=budget, input_tokens=3, output_tokens=3, cost_minor_units=3)
        with pytest.raises(LedgerError, match="EXHAUSTED"):
            reopened.reserve_budget(key="c" * 64, budget=budget, input_tokens=0, output_tokens=0, cost_minor_units=0)


@pytest.mark.parametrize("date", ["not-a-date", "2099-01-01T00:00:00", "2000-01-01T00:00:00Z"])
def test_invalid_expiry_cannot_enable_sending(tmp_path, monkeypatch, date):
    ledger, budget = expired_ledger(tmp_path, monkeypatch)
    with pytest.raises(LedgerError, match="DATE_INVALID"):
        ledger.extend_budget_expiry(budget=budget, expires_at=date, approval_ref="confirmation")
    assert ledger._connection.execute("SELECT COUNT(*) FROM budget_expiry_extensions").fetchone()[0] == 0
    ledger.close()


def test_extension_cannot_change_authorization_or_reuse_approval(tmp_path, monkeypatch):
    ledger, budget = expired_ledger(tmp_path, monkeypatch)
    with pytest.raises(LedgerError, match="APPROVAL_REQUIRED"):
        ledger.extend_budget_expiry(budget=budget, expires_at="2099-01-01T00:00:00Z", approval_ref="")
    with pytest.raises(LedgerError, match="BINDING_MISMATCH"):
        ledger.extend_budget_expiry(budget=budget.model_copy(update={"max_cost_minor_units":500}),
            expires_at="2099-01-01T00:00:00Z", approval_ref="confirmation")
    ledger.extend_budget_expiry(budget=budget, expires_at="2099-01-01T00:00:00Z", approval_ref="confirmation")
    with pytest.raises(LedgerError, match="CONFLICT"):
        ledger.extend_budget_expiry(budget=budget, expires_at="2098-01-01T00:00:00Z", approval_ref="confirmation")
    with pytest.raises(LedgerError, match="MUST_EXTEND"):
        ledger.extend_budget_expiry(budget=budget, expires_at="2098-01-01T00:00:00Z", approval_ref="second-confirmation")
    with pytest.raises(LedgerError, match="AUTHORIZATION_CHANGED"):
        ledger.reserve_budget(key="b"*64,budget=budget.model_copy(update={"max_model_calls":99}),
            input_tokens=0,output_tokens=0,cost_minor_units=0)
    ledger.close()


def test_call_capacity_extension_is_explicit_idempotent_and_keeps_cost_limit(tmp_path, monkeypatch):
    ledger, budget = expired_ledger(tmp_path, monkeypatch)
    ledger.extend_budget_expiry(budget=budget, expires_at="2099-01-01T00:00:00Z", approval_ref="expiry")
    ledger.reserve_budget(key="b" * 64, budget=budget, input_tokens=1, output_tokens=1, cost_minor_units=1)
    with pytest.raises(LedgerError, match="EXHAUSTED"):
        ledger.reserve_budget(key="c" * 64, budget=budget, input_tokens=1, output_tokens=1, cost_minor_units=1)
    args = dict(budget=budget, additional_calls=1, approval_ref="user-new-three-case-scope")
    ledger.extend_budget_call_capacity(**args)
    ledger.extend_budget_call_capacity(**args)
    ledger.reserve_budget(key="c" * 64, budget=budget, input_tokens=1, output_tokens=1, cost_minor_units=1)
    with pytest.raises(LedgerError, match="EXHAUSTED"):
        ledger.reserve_budget(key="d" * 64, budget=budget, input_tokens=1, output_tokens=1, cost_minor_units=1)
    assert ledger._connection.execute("SELECT COUNT(*) FROM budget_call_capacity_extensions").fetchone()[0] == 1
    ledger.close()


@pytest.mark.parametrize("calls", [0, 13, True])
def test_call_capacity_extension_rejects_invalid_scope(tmp_path, monkeypatch, calls):
    ledger, budget = expired_ledger(tmp_path, monkeypatch)
    with pytest.raises(LedgerError, match="CALL_EXTENSION_INVALID"):
        ledger.extend_budget_call_capacity(budget=budget, additional_calls=calls, approval_ref="scope")
    ledger.close()


def test_call_capacity_extension_rejects_changed_authorization_or_reused_ref(tmp_path, monkeypatch):
    ledger, budget = expired_ledger(tmp_path, monkeypatch)
    with pytest.raises(LedgerError, match="BINDING_MISMATCH"):
        ledger.extend_budget_call_capacity(
            budget=budget.model_copy(update={"max_model_calls": 99}), additional_calls=1, approval_ref="scope",
        )
    ledger.extend_budget_call_capacity(budget=budget, additional_calls=1, approval_ref="scope")
    with pytest.raises(LedgerError, match="CONFLICT"):
        ledger.extend_budget_call_capacity(budget=budget, additional_calls=2, approval_ref="scope")
    ledger.close()
