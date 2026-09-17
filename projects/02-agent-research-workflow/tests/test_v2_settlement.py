"""Operator reconciliation preserves original debits and refuses uncertain receipts."""
import hashlib
from pathlib import Path

import pytest

from agent_research.v2.contracts import BudgetAuthorization, ModelResult, Usage, canonical_json, sha256_json
from agent_research.v2.ledger import OperationLedger, LedgerError


def setup(tmp_path, *, status="succeeded", usage=None):
    source = OperationLedger(tmp_path / "source.sqlite3")
    total = OperationLedger(tmp_path / "total.sqlite3", single_authorization=True)
    budget = BudgetAuthorization(authorization_id="total-test", max_cost_minor_units=10,
        max_model_calls=2, max_input_tokens=20, max_output_tokens=20,
        expires_at="2099-01-01T00:00:00Z", approved=True)
    key = "a" * 64
    shared = sha256_json({"schema_version":"p2-total-budget-reservation-v1",
                         "total_authorization_id":budget.authorization_id,"local_call_key":key})
    total.reserve_budget(key=shared, budget=budget, input_tokens=20, output_tokens=20, cost_minor_units=10)
    source.reserve(logical_call_key=key,run_id="run-test",node="review",provider="scripted",
                   model_id="scripted-v2",request_hash="b"*64)
    source.mark_dispatched(key)
    if status=="succeeded":
        usage = usage or Usage(input_tokens=2,output_tokens=3,cost_minor_units=2,cost_status="known")
        result = ModelResult(task="review",provider="scripted",model_id="scripted-v2",review_completed=True,usage=usage)
        payload = result.model_dump(mode="json")
        source.record_success(logical_call_key=key,response_hash=hashlib.sha256(canonical_json(payload).encode()).hexdigest(),response_payload=payload,usage=usage)
    elif status=="unknown":
        source.record_failure(logical_call_key=key,error_code="TIMEOUT",unknown=True)
    return source,total,budget,key,shared


def test_settlement_is_idempotent_durable_and_does_not_refund_call_count(tmp_path):
    source,total,budget,key,shared=setup(tmp_path)
    args=dict(budget=budget,source_ledger=source,source_key=key,reconciliation_id="bill-123")
    with pytest.raises(LedgerError,match="EXHAUSTED"):
        total.reserve_budget(key="c"*64,budget=budget,input_tokens=1,output_tokens=1,cost_minor_units=1)
    total.settle_successful_call(**args)
    total.settle_successful_call(**args)
    assert total._connection.execute("select cost_minor_units from budget_reservations").fetchone()[0]==10
    assert total._connection.execute("select count(*) from budget_settlements").fetchone()[0]==1
    total.close()
    with OperationLedger(tmp_path/"total.sqlite3") as reopened:
        with pytest.raises(LedgerError, match="EXHAUSTED"):
            reopened.reserve_budget(key="c"*64,budget=budget,input_tokens=18,output_tokens=17,cost_minor_units=9)
        reopened.reserve_budget(key="c"*64,budget=budget,input_tokens=18,output_tokens=17,cost_minor_units=8)
        with pytest.raises(LedgerError,match="EXHAUSTED"):
            reopened.reserve_budget(key="d"*64,budget=budget,input_tokens=0,output_tokens=0,cost_minor_units=0)
    source.close()


@pytest.mark.parametrize("status",["dispatched","unknown"])
def test_uncertain_call_cannot_release_reservation(tmp_path,status):
    source,total,budget,key,shared=setup(tmp_path,status=status)
    with pytest.raises(LedgerError,match="SUCCESS_REQUIRED"):
        total.settle_successful_call(budget=budget,source_ledger=source,source_key=key,reconciliation_id="bill")
    assert total._connection.execute("select count(*) from budget_settlements").fetchone()[0]==0
    source.close();total.close()


@pytest.mark.parametrize("usage,error",[
    (Usage(cost_status="unknown"),"KNOWN_USAGE_REQUIRED"),
    (Usage(input_tokens=21,output_tokens=1,cost_minor_units=1,cost_status="known"),"EXCEEDS_RESERVATION"),
])
def test_unknown_or_over_limit_usage_is_not_settled(tmp_path,usage,error):
    source,total,budget,key,shared=setup(tmp_path,usage=usage)
    with pytest.raises(LedgerError,match=error):
        total.settle_successful_call(budget=budget,source_ledger=source,source_key=key,reconciliation_id="bill")
    source.close();total.close()


def test_changed_receipt_or_authorization_is_rejected(tmp_path):
    source,total,budget,key,shared=setup(tmp_path)
    args=dict(budget=budget,source_ledger=source,source_key=key,reconciliation_id="bill")
    with pytest.raises(LedgerError,match="BINDING_MISMATCH"):
        total.settle_successful_call(**(args|{"budget":budget.model_copy(update={"max_cost_minor_units":500})}))
    total.settle_successful_call(**args)
    with pytest.raises(LedgerError,match="SETTLEMENT_CONFLICT"):
        total.settle_successful_call(**(args|{"reconciliation_id":"another-bill"}))
    source._connection.execute("update operations set response_json='{}'")
    source._connection.commit()
    with pytest.raises(LedgerError,match="HASH_MISMATCH"):
        total.settle_successful_call(**args)
    source.close();total.close()
