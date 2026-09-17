"""Durable operation ledger for model calls and cost uncertainty."""

from __future__ import annotations

import sqlite3
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from agent_research.v2.contracts import (
    CallRecord,
    BudgetAuthorization,
    CallStatus,
    Usage,
    canonical_json,
    sha256_json,
    ModelResult,
)


class LedgerError(RuntimeError):
    """Raised when an operation cannot safely change ledger state."""


class OperationLedger:
    """Small single-process SQLite ledger with explicit crash states."""

    def __init__(self, path: Path, *, single_authorization: bool = False) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS operations (
                logical_call_key TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                node TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                status TEXT NOT NULL,
                provider TEXT NOT NULL,
                model_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response_hash TEXT,
                response_json TEXT,
                usage_json TEXT,
                error_code TEXT,
                record_json TEXT NOT NULL
            )
            """
        )
        self._connection.commit()
        self._connection.execute("CREATE TABLE IF NOT EXISTS ledger_policy (singleton INTEGER PRIMARY KEY CHECK(singleton=1), single_authorization INTEGER NOT NULL)")
        if single_authorization:
            self._connection.execute("INSERT OR REPLACE INTO ledger_policy VALUES (1, 1)")
        self._connection.commit()
        self._connection.execute("""CREATE TABLE IF NOT EXISTS budget_reservations (
            logical_call_key TEXT PRIMARY KEY, authorization_id TEXT NOT NULL,
            authorization_json TEXT NOT NULL, input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL, cost_minor_units INTEGER NOT NULL
        )""")
        self._connection.execute("""CREATE TABLE IF NOT EXISTS budget_settlements (
            logical_call_key TEXT PRIMARY KEY REFERENCES budget_reservations(logical_call_key),
            source_call_key TEXT NOT NULL, response_hash TEXT NOT NULL,
            reconciliation_id TEXT NOT NULL, input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL, cost_minor_units INTEGER NOT NULL
        )""")
        self._connection.execute("""CREATE TABLE IF NOT EXISTS budget_expiry_extensions (
            approval_ref TEXT PRIMARY KEY, authorization_id TEXT NOT NULL,
            authorization_json TEXT NOT NULL, expires_at TEXT NOT NULL
        )""")
        self._connection.execute("""CREATE TABLE IF NOT EXISTS budget_call_capacity_extensions (
            approval_ref TEXT PRIMARY KEY, authorization_id TEXT NOT NULL,
            authorization_json TEXT NOT NULL, additional_calls INTEGER NOT NULL
        )""")
        self._connection.commit()

    def extend_budget_expiry(self, *, budget: BudgetAuthorization,
                             expires_at: str, approval_ref: str) -> None:
        """Record an operator-authorized deadline extension without resetting limits.

        Never called automatically by the graph. The operator must obtain explicit
        approval first; this is an audit record, not authentication of that person.
        Original authorization JSON, reservations, usage and call counts stay intact.
        """
        if not budget.approved or not approval_ref.strip() or len(approval_ref) > 120:
            raise LedgerError("BUDGET_EXTENSION_APPROVAL_REQUIRED")
        try:
            target = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if target.tzinfo is None or target <= datetime.now(timezone.utc):
                raise ValueError
        except ValueError:
            raise LedgerError("BUDGET_EXTENSION_DATE_INVALID") from None
        serialized = budget.model_dump_json()
        values = (approval_ref, budget.authorization_id, serialized, expires_at)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                "SELECT * FROM budget_expiry_extensions WHERE approval_ref=?", (approval_ref,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != values:
                    raise LedgerError("BUDGET_EXTENSION_CONFLICT")
                self._connection.commit()
                return
            rows = self._connection.execute(
                "SELECT authorization_json FROM budget_reservations WHERE authorization_id=?",
                (budget.authorization_id,),
            ).fetchall()
            if not rows or any(row[0] != serialized for row in rows):
                raise LedgerError("BUDGET_EXTENSION_BINDING_MISMATCH")
            previous = datetime.fromisoformat(self._effective_expiry(budget).replace("Z", "+00:00"))
            if previous.tzinfo is None or target <= previous:
                raise LedgerError("BUDGET_EXTENSION_MUST_EXTEND")
            self._connection.execute("INSERT INTO budget_expiry_extensions VALUES (?, ?, ?, ?)", values)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def _effective_expiry(self, budget: BudgetAuthorization) -> str:
        row = self._connection.execute(
            "SELECT authorization_json, expires_at FROM budget_expiry_extensions "
            "WHERE authorization_id=? ORDER BY rowid DESC LIMIT 1", (budget.authorization_id,),
        ).fetchone()
        if row is None:
            return budget.expires_at
        if row[0] != budget.model_dump_json():
            raise LedgerError("BUDGET_AUTHORIZATION_CHANGED")
        return row[1]

    def extend_budget_call_capacity(self, *, budget: BudgetAuthorization,
                                    additional_calls: int, approval_ref: str) -> None:
        """Append a narrow, operator-approved call extension without changing spend cap.

        This keeps the original authorization JSON and all existing reservations.
        It cannot refund, delete, or reclassify historical calls; cost and token
        limits remain those in ``budget``. The fixed per-extension bound prevents
        an accidental replacement of a bounded approval with an open-ended limit.
        """
        if (not budget.approved or not approval_ref.strip() or len(approval_ref) > 120
                or isinstance(additional_calls, bool) or not 1 <= additional_calls <= 12):
            raise LedgerError("BUDGET_CALL_EXTENSION_INVALID")
        serialized = budget.model_dump_json()
        values = (approval_ref, budget.authorization_id, serialized, additional_calls)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            existing = self._connection.execute(
                "SELECT * FROM budget_call_capacity_extensions WHERE approval_ref=?", (approval_ref,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != values:
                    raise LedgerError("BUDGET_CALL_EXTENSION_CONFLICT")
                self._connection.commit()
                return
            rows = self._connection.execute(
                "SELECT authorization_json FROM budget_reservations WHERE authorization_id=?",
                (budget.authorization_id,),
            ).fetchall()
            if not rows or any(row[0] != serialized for row in rows):
                raise LedgerError("BUDGET_CALL_EXTENSION_BINDING_MISMATCH")
            self._connection.execute("INSERT INTO budget_call_capacity_extensions VALUES (?, ?, ?, ?)", values)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def _effective_call_capacity(self, budget: BudgetAuthorization) -> int:
        rows = self._connection.execute(
            "SELECT authorization_json, additional_calls FROM budget_call_capacity_extensions "
            "WHERE authorization_id=? ORDER BY rowid", (budget.authorization_id,),
        ).fetchall()
        if any(row[0] != budget.model_dump_json() for row in rows):
            raise LedgerError("BUDGET_AUTHORIZATION_CHANGED")
        return budget.max_model_calls + sum(row[1] for row in rows)

    def reserve_budget(self, *, key: str, budget: BudgetAuthorization,
                       input_tokens: int, output_tokens: int, cost_minor_units: int) -> None:
        """Permanently debit conservative maxima before sending, across runs.

        No automatic refunds: a crash or timeout may already have incurred cost.
        BEGIN IMMEDIATE serializes competing connections to this runtime ledger.
        """
        try:
            expiry = datetime.fromisoformat(self._effective_expiry(budget).replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                raise ValueError
        except ValueError:
            raise LedgerError("BUDGET_EXPIRED_OR_INVALID") from None
        if not budget.approved or min(input_tokens, output_tokens, cost_minor_units) < 0:
            raise LedgerError("BUDGET_RESERVATION_INVALID")
        serialized = budget.model_dump_json()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            policy = self._connection.execute("SELECT single_authorization FROM ledger_policy WHERE singleton=1").fetchone()
            if policy and policy[0] and self._connection.execute(
                "SELECT 1 FROM budget_reservations WHERE authorization_id != ? LIMIT 1",
                (budget.authorization_id,),
            ).fetchone():
                raise LedgerError("TOTAL_BUDGET_AUTHORIZATION_CHANGED")
            rows = self._connection.execute(
                """SELECT r.*, COALESCE(s.input_tokens, r.input_tokens) AS effective_input,
                          COALESCE(s.output_tokens, r.output_tokens) AS effective_output,
                          COALESCE(s.cost_minor_units, r.cost_minor_units) AS effective_cost
                   FROM budget_reservations r LEFT JOIN budget_settlements s
                   ON r.logical_call_key = s.logical_call_key WHERE r.authorization_id = ?""",
                (budget.authorization_id,),
            ).fetchall()
            if any(row["authorization_json"] != serialized for row in rows):
                raise LedgerError("BUDGET_AUTHORIZATION_CHANGED")
            if self._connection.execute(
                "SELECT 1 FROM budget_reservations WHERE logical_call_key = ?", (key,)
            ).fetchone():
                raise LedgerError("BUDGET_DISPATCH_ALREADY_RESERVED_REQUIRES_REVIEW")
            if (len(rows) >= self._effective_call_capacity(budget)
                or sum(row["effective_input"] for row in rows) + input_tokens > budget.max_input_tokens
                or sum(row["effective_output"] for row in rows) + output_tokens > budget.max_output_tokens
                or sum(row["effective_cost"] for row in rows) + cost_minor_units > budget.max_cost_minor_units):
                raise LedgerError("BUDGET_RESERVATION_EXHAUSTED")
            self._connection.execute(
                "INSERT INTO budget_reservations VALUES (?, ?, ?, ?, ?, ?)",
                (key, budget.authorization_id, serialized, input_tokens, output_tokens, cost_minor_units),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def settle_successful_call(self, *, budget: BudgetAuthorization,
                               source_ledger: "OperationLedger", source_key: str,
                               reconciliation_id: str) -> None:
        """Explicit operator settlement; never invoked by the production graph.

        Original reservations and call counts stay immutable. Only verified
        successful, known-usage receipts can replace their conservative bounds.
        Unknown calls and the unmatched historical debit remain fully reserved.
        """
        if not reconciliation_id or len(reconciliation_id) > 120:
            raise LedgerError("SETTLEMENT_RECONCILIATION_REQUIRED")
        record = source_ledger.get(source_key)
        if record is None or record.status is not CallStatus.SUCCEEDED:
            raise LedgerError("SETTLEMENT_SUCCESS_REQUIRED")
        response = source_ledger.cached_response(source_key)
        if response is None or hashlib.sha256(response.encode("utf-8")).hexdigest() != record.response_hash:
            raise LedgerError("SETTLEMENT_RESPONSE_HASH_MISMATCH")
        result = ModelResult.model_validate_json(response)
        usage = result.usage
        if usage != record.usage or usage.cost_status.value != "known" or any(
            value is None for value in (usage.input_tokens, usage.output_tokens, usage.cost_minor_units)
        ):
            raise LedgerError("SETTLEMENT_KNOWN_USAGE_REQUIRED")
        key = sha256_json({
            "schema_version": "p2-total-budget-reservation-v1",
            "total_authorization_id": budget.authorization_id, "local_call_key": source_key,
        })
        values = (key, source_key, record.response_hash, reconciliation_id,
                  usage.input_tokens, usage.output_tokens, usage.cost_minor_units)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            reserved = self._connection.execute(
                "SELECT * FROM budget_reservations WHERE logical_call_key=?", (key,),
            ).fetchone()
            if reserved is None or reserved["authorization_json"] != budget.model_dump_json():
                raise LedgerError("SETTLEMENT_RESERVATION_BINDING_MISMATCH")
            if any(value > reserved[field] for value, field in (
                (usage.input_tokens, "input_tokens"), (usage.output_tokens, "output_tokens"),
                (usage.cost_minor_units, "cost_minor_units"),
            )):
                raise LedgerError("SETTLEMENT_EXCEEDS_RESERVATION")
            previous = self._connection.execute(
                "SELECT * FROM budget_settlements WHERE logical_call_key=?", (key,),
            ).fetchone()
            if previous is not None:
                if tuple(previous) != values:
                    raise LedgerError("SETTLEMENT_CONFLICT")
            else:
                self._connection.execute("INSERT INTO budget_settlements VALUES (?, ?, ?, ?, ?, ?, ?)", values)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "OperationLedger":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(self, logical_call_key: str) -> CallRecord | None:
        row = self._connection.execute(
            "SELECT record_json FROM operations WHERE logical_call_key = ?",
            (logical_call_key,),
        ).fetchone()
        if row is None:
            return None
        return CallRecord.model_validate_json(row["record_json"])

    def reserve(
        self,
        *,
        logical_call_key: str,
        run_id: str,
        node: str,
        provider: str,
        model_id: str,
        request_hash: str,
    ) -> CallRecord:
        existing = self.get(logical_call_key)
        if existing is not None:
            if existing.request_hash != request_hash:
                raise LedgerError("LEDGER_KEY_REUSED_WITH_DIFFERENT_REQUEST")
            return existing
        record = CallRecord(
            logical_call_key=logical_call_key,
            run_id=run_id,
            node=node,
            attempt=1,
            status=CallStatus.RESERVED,
            provider=provider,
            model_id=model_id,
            request_hash=request_hash,
        )
        self._insert(record)
        return record

    def mark_dispatched(self, logical_call_key: str) -> CallRecord:
        return self._transition(logical_call_key, CallStatus.DISPATCHED)

    def cached_response(self, logical_call_key: str) -> str | None:
        row = self._connection.execute(
            "SELECT response_json FROM operations WHERE logical_call_key = ?",
            (logical_call_key,),
        ).fetchone()
        return None if row is None else row["response_json"]

    def record_success(
        self,
        *,
        logical_call_key: str,
        response_hash: str,
        response_payload: object,
        usage: Usage,
    ) -> CallRecord:
        return self._transition(
            logical_call_key,
            CallStatus.SUCCEEDED,
            response_hash=response_hash,
            response_payload=response_payload,
            usage=usage,
        )

    def record_failure(
        self,
        *,
        logical_call_key: str,
        error_code: str,
        unknown: bool = False,
        usage: Usage | None = None,
    ) -> CallRecord:
        return self._transition(
            logical_call_key,
            CallStatus.UNKNOWN if unknown else CallStatus.FAILED,
            error_code=error_code,
            usage=usage,
        )

    def records_for_run(self, run_id: str) -> tuple[CallRecord, ...]:
        rows = self._connection.execute(
            "SELECT record_json FROM operations WHERE run_id = ? ORDER BY rowid",
            (run_id,),
        ).fetchall()
        return tuple(CallRecord.model_validate_json(row["record_json"]) for row in rows)

    def _insert(self, record: CallRecord) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO operations
                (logical_call_key, run_id, node, attempt, status, provider,
                 model_id, request_hash, response_hash, response_json, usage_json, error_code,
                 record_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.logical_call_key,
                    record.run_id,
                    record.node,
                    record.attempt,
                    record.status.value,
                    record.provider,
                    record.model_id,
                    record.request_hash,
                    record.response_hash,
                    None,
                    record.usage.model_dump_json() if record.usage else None,
                    record.error_code,
                    record.model_dump_json(),
                ),
            )
            self._connection.commit()
        except sqlite3.IntegrityError as exc:
            self._connection.rollback()
            raise LedgerError("LEDGER_RESERVATION_CONFLICT") from exc

    def _transition(
        self,
        logical_call_key: str,
        status: CallStatus,
        *,
        response_hash: str | None = None,
        response_payload: object | None = None,
        usage: Usage | None = None,
        error_code: str | None = None,
    ) -> CallRecord:
        current = self.get(logical_call_key)
        if current is None:
            raise LedgerError("LEDGER_OPERATION_NOT_RESERVED")
        allowed = {
            CallStatus.RESERVED: {CallStatus.DISPATCHED, CallStatus.FAILED, CallStatus.UNKNOWN},
            CallStatus.DISPATCHED: {CallStatus.SUCCEEDED, CallStatus.FAILED, CallStatus.UNKNOWN},
            CallStatus.SUCCEEDED: {CallStatus.SUCCEEDED},
            CallStatus.FAILED: {CallStatus.FAILED},
            CallStatus.UNKNOWN: {CallStatus.UNKNOWN},
        }
        if status not in allowed[current.status]:
            raise LedgerError(
                f"LEDGER_INVALID_TRANSITION:{current.status.value}:{status.value}"
            )
        updated = current.model_copy(
            update={
                "status": status,
            "response_hash": response_hash or current.response_hash,
                "usage": usage or current.usage,
                "error_code": error_code or current.error_code,
            }
        )
        self._connection.execute(
            """
            UPDATE operations SET status = ?, response_hash = ?, response_json = ?,
            usage_json = ?, error_code = ?, record_json = ?
            WHERE logical_call_key = ?
            """,
            (
                updated.status.value,
                updated.response_hash,
                canonical_json(response_payload) if response_payload is not None else None,
                updated.usage.model_dump_json() if updated.usage else None,
                updated.error_code,
                updated.model_dump_json(),
                logical_call_key,
            ),
        )
        self._connection.commit()
        return updated


def request_hash(payload: object) -> str:
    import hashlib

    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def logical_call_key(
    *,
    run_id: str,
    node: str,
    request_hash_value: str,
    snapshot_id: str,
    prompt_hash: str,
    model_config_hash: str,
    logical_revision: int,
) -> str:
    return request_hash(
        {
            "run_id": run_id,
            "node": node,
            "request_hash": request_hash_value,
            "snapshot_id": snapshot_id,
            "prompt_hash": prompt_hash,
            "model_config_hash": model_config_hash,
            "logical_revision": logical_revision,
        }
    )
