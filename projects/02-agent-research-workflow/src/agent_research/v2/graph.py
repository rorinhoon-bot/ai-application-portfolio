"""V2 single-workflow graph with two human gates and durable call accounting."""

from __future__ import annotations

import hashlib
import re
from functools import partial
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_research.v2.contracts import (
    BudgetAuthorization,
    CallStatus,
    DecisionStatus,
    DimensionSpec,
    EvidenceRecord,
    HumanAction,
    ModelResult,
    ModelToolCall,
    RunStatus,
    RuntimeStateV2,
    SourceSnapshotV2,
    canonical_json,
    sha256_json,
)
from agent_research.v2.exporter import ExportError, V2Exporter
from agent_research.v2.ledger import (
    LedgerError,
    OperationLedger,
    logical_call_key,
    request_hash,
)
from agent_research.v2.model_client import ModelClient, ModelClientError
from agent_research.v2.source_store import SourceStore, SourceStoreError


class V2GraphState(TypedDict, total=False):
    schema_version: str
    graph_version: str
    run_id: str
    thread_id: str
    status: str
    current_node: str
    request: dict[str, object]
    request_revision: int
    request_hash: str | None
    report_revision: int
    report_hash: str | None
    evidence: list[dict[str, object]]
    evidence_cells: list[dict[str, object]]
    report: dict[str, object] | None
    review_findings: list[str]
    pending_tool_calls: list[dict[str, object]]
    errors: list[str]
    model_call_count: int
    tool_call_count: int
    unknown_call_count: int
    approved_request_revision: int | None
    approved_request_hash: str | None
    approved_report_revision: int | None
    approved_report_hash: str | None
    artifact_id: str | None


class V2GraphError(RuntimeError):
    """Stable graph error."""


def create_initial_state(*, run_id: str, thread_id: str, request: object) -> dict[str, object]:
    state = RuntimeStateV2(
        run_id=run_id,
        thread_id=thread_id,
        request=request,
    )
    return state.model_dump(mode="json")


def graph_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def build_v2_graph(
    *,
    checkpointer: BaseCheckpointSaver,
    model: ModelClient,
    source_store: SourceStore,
    ledger: OperationLedger,
    budget: BudgetAuthorization,
    exporter: V2Exporter,
    total_budget_ledger: OperationLedger | None = None,
    total_budget: BudgetAuthorization | None = None,
) -> object:
    dependencies = _Dependencies(
        model=model,
        source_store=source_store,
        ledger=ledger,
        budget=budget,
        exporter=exporter,
        total_budget_ledger=total_budget_ledger,
        total_budget=total_budget,
    )
    builder = StateGraph(V2GraphState)
    builder.add_node("validate_request", partial(_validate_request, deps=dependencies))
    builder.add_node("requirements_gate", partial(_requirements_gate, deps=dependencies))
    builder.add_node("plan_research", partial(_plan_research, deps=dependencies))
    builder.add_node("execute_tools", partial(_execute_tools, deps=dependencies))
    builder.add_node("draft_report", partial(_draft_report, deps=dependencies))
    builder.add_node("review_report", partial(_review_report, deps=dependencies))
    builder.add_node("report_gate", partial(_report_gate, deps=dependencies))
    builder.add_node("export_report", partial(_export_report, deps=dependencies))
    builder.add_edge(START, "validate_request")
    builder.add_conditional_edges(
        "validate_request",
        _route_validate,
        {"gate": "requirements_gate", "end": END},
    )
    builder.add_conditional_edges(
        "requirements_gate",
        _route_requirements,
        {"plan": "plan_research", "requirements": "requirements_gate", "end": END},
    )
    builder.add_conditional_edges(
        "plan_research",
        _route_plan,
        {"execute": "execute_tools", "end": END},
    )
    builder.add_conditional_edges(
        "execute_tools",
        _route_execute,
        {"draft": "draft_report", "end": END},
    )
    builder.add_conditional_edges(
        "draft_report",
        _route_draft,
        {"review": "review_report", "end": END},
    )
    builder.add_conditional_edges(
        "review_report",
        _route_review,
        {"gate": "report_gate", "end": END},
    )
    builder.add_conditional_edges(
        "report_gate",
        _route_report,
        {"draft": "draft_report", "export": "export_report", "end": END},
    )
    builder.add_edge("export_report", END)
    return builder.compile(checkpointer=checkpointer)


class _Dependencies:
    def __init__(
        self,
        *,
        model: ModelClient,
        source_store: SourceStore,
        ledger: OperationLedger,
        budget: BudgetAuthorization,
        exporter: V2Exporter,
        total_budget_ledger: OperationLedger | None,
        total_budget: BudgetAuthorization | None,
    ) -> None:
        self.model = model
        self.source_store = source_store
        self.ledger = ledger
        self.budget = budget
        self.exporter = exporter
        if (total_budget_ledger is None) != (total_budget is None):
            raise V2GraphError("TOTAL_BUDGET_CONFIGURATION_INVALID")
        self.total_budget_ledger = total_budget_ledger
        self.total_budget = total_budget


def _validated(data: dict[str, object]) -> dict[str, object]:
    return RuntimeStateV2.model_validate(data).model_dump(mode="json")


def _state(raw: dict[str, object]) -> RuntimeStateV2:
    return RuntimeStateV2.model_validate(raw)


def _validate_request(state: dict[str, object], *, deps: _Dependencies) -> dict[str, object]:
    current = _state(state)
    if current.request.source_snapshot_id != deps.source_store.snapshot.snapshot_id:
        return _failed(current, "SOURCE_SNAPSHOT_MISMATCH")
    if current.request.budget_authorization_id != deps.budget.authorization_id:
        return _failed(current, "BUDGET_AUTHORIZATION_MISMATCH")
    if current.request.model_config_hash != deps.model.config_hash:
        return _failed(current, "MODEL_CONFIGURATION_MISMATCH")
    return _validated(
        current.model_copy(
            update={
                "status": RunStatus.NEEDS_HUMAN,
                "current_node": "requirements-gate",
                "request_hash": current.request.content_hash(),
            }
        ).model_dump(mode="json")
    )


def _requirements_gate(state: dict[str, object], *, deps: _Dependencies) -> dict[str, object]:
    current = _state(state)
    pause = {
        "gate": "requirements",
        "run_id": current.run_id,
        "thread_id": current.thread_id,
        "request_revision": current.request_revision,
        "request_hash": current.request_hash or current.request.content_hash(),
        "source_snapshot_id": current.request.source_snapshot_id,
        "budget_authorization_id": current.request.budget_authorization_id,
        "model_id": deps.model.model_id,
        "message": "Approve scope, snapshot, model and budget before any model call.",
    }
    raw_decision = interrupt(pause)
    if not isinstance(raw_decision, dict):
        return _failed(current, "HUMAN_DECISION_INVALID")
    if raw_decision.get("run_id") != current.run_id or raw_decision.get("thread_id") != current.thread_id:
        return _failed(current, "HUMAN_DECISION_IDENTITY_MISMATCH")
    expected_hash = current.request_hash or current.request.content_hash()
    if raw_decision.get("expected_request_hash") != expected_hash:
        return _failed(current, "HUMAN_DECISION_REQUEST_HASH_MISMATCH")
    try:
        action = HumanAction(str(raw_decision.get("action")))
    except ValueError:
        return _failed(current, "HUMAN_DECISION_ACTION_INVALID")
    if action is HumanAction.APPROVE:
        if not deps.budget.approved:
            return _failed(current, "BUDGET_AUTHORIZATION_REQUIRED")
        return _validated(
            current.model_copy(
                update={
                    "status": RunStatus.RUNNING,
                    "current_node": "plan-research",
                    "request_hash": expected_hash,
                    "approved_request_revision": current.request_revision,
                    "approved_request_hash": expected_hash,
                }
            ).model_dump(mode="json")
        )
    if action is HumanAction.EDIT:
        if not isinstance(raw_decision.get("request"), dict):
            return _failed(current, "HUMAN_EDIT_REQUEST_REQUIRED")
        try:
            from agent_research.v2.contracts import ResearchRequestV2

            edited = ResearchRequestV2.model_validate(raw_decision["request"])
        except ValueError:
            return _failed(current, "HUMAN_EDIT_REQUEST_INVALID")
        return _validated(
            current.model_copy(
                update={
                    "request": edited,
                    "request_revision": current.request_revision + 1,
                    "request_hash": edited.content_hash(),
                    "status": RunStatus.RUNNING,
                    "current_node": "requirements-gate",
                }
            ).model_dump(mode="json")
        )
    if action is HumanAction.CANCEL:
        return _validated(current.model_copy(update={"status": RunStatus.CANCELLED, "current_node": "end"}).model_dump(mode="json"))
    return _validated(current.model_copy(update={"status": RunStatus.FAILED, "current_node": "end", "errors": (*current.errors, "HUMAN_REQUEST_REJECTED")}).model_dump(mode="json"))


def _plan_research(state: dict[str, object], *, deps: _Dependencies) -> dict[str, object]:
    current = _state(state)
    try:
        result = _model_call(current, deps, task="plan", payload={"request": current.request.model_dump(mode="json")})
    except (ModelClientError, LedgerError) as exc:
        return _failed(current, str(exc))
    if not result.tool_calls:
        return _failed(current, "MODEL_PLAN_HAS_NO_TOOL_CALL")
    return _validated(current.model_copy(update={
        "current_node": "execute-tools",
        "pending_tool_calls": result.tool_calls,
        "model_call_count": current.model_call_count + 1,
    }).model_dump(mode="json"))


def _execute_tools(state: dict[str, object], *, deps: _Dependencies) -> dict[str, object]:
    current = _state(state)
    evidence = list(current.evidence)
    for tool_call in current.pending_tool_calls:
        if tool_call.tool_name != "search_sources":
            return _failed(current, "TOOL_NOT_ALLOWED")
        args = tool_call.arguments
        raw_candidate_ids = args.get("candidate_ids", ())
        raw_dimension_ids = args.get("dimension_ids", ())
        query = args.get("query")
        top_k = args.get("top_k", 6)
        if (
            not isinstance(raw_candidate_ids, (list, tuple))
            or not all(isinstance(item, str) for item in raw_candidate_ids)
            or not isinstance(raw_dimension_ids, (list, tuple))
            or not all(isinstance(item, str) for item in raw_dimension_ids)
            or not isinstance(query, str)
            or isinstance(top_k, bool)
            or not isinstance(top_k, int)
        ):
            return _failed(current, "TOOL_ARGUMENTS_INVALID")
        candidate_ids = set(raw_candidate_ids)
        required_candidate_ids = {item.candidate_id for item in current.request.candidates}
        dimension_ids = set(raw_dimension_ids)
        required_dimension_ids = {item.dimension_id for item in current.request.dimensions}
        if candidate_ids != required_candidate_ids or len(raw_candidate_ids) != len(candidate_ids):
            return _failed(current, "TOOL_CANDIDATE_COVERAGE_INCOMPLETE")
        if dimension_ids != required_dimension_ids or len(raw_dimension_ids) != len(dimension_ids):
            return _failed(current, "TOOL_DIMENSION_COVERAGE_INCOMPLETE")
        try:
            found = tuple(
                evidence_item
                for candidate_id in sorted(candidate_ids)
                for dimension in current.request.dimensions
                for evidence_item in deps.source_store.search(
                    query=_coverage_query(dimension),
                    request=current.request,
                    top_k=1,
                    candidate_ids=frozenset({candidate_id}),
                )
            )
        except (SourceStoreError, ValueError, TypeError) as exc:
            return _failed(current, str(exc))
        try:
            # One additional hit per candidate answers the actual question, while
            # keeping at most two extra excerpts (4800 characters for this MVP).
            question_hits = tuple(
                item for candidate_id in sorted(candidate_ids)
                for item in deps.source_store.search(
                    query=current.request.research_question[:300],
                    request=current.request, top_k=1,
                    candidate_ids=frozenset({candidate_id}),
                )
            )
            found = (*found, *question_hits)
        except (SourceStoreError, ValueError, TypeError) as exc:
            return _failed(current, str(exc))
        known = {item.evidence_id for item in evidence}
        for item in found:
            if item.evidence_id not in known:
                evidence.append(item)
                known.add(item.evidence_id)
    if not evidence:
        return _failed(current, "NO_VALID_EVIDENCE")
    return _validated(current.model_copy(update={
        "current_node": "draft-report",
        "evidence": tuple(evidence),
        "pending_tool_calls": (),
        "tool_call_count": current.tool_call_count + len(current.pending_tool_calls),
    }).model_dump(mode="json"))


def _draft_report(state: dict[str, object], *, deps: _Dependencies) -> dict[str, object]:
    current = _state(state)
    try:
        result = _model_call(
            current,
            deps,
            task="draft",
            payload={
                "request": current.request.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in current.evidence],
                "previous_review_findings": list(current.review_findings),
            },
        )
    except (ModelClientError, LedgerError) as exc:
        return _failed(current, str(exc))
    report_hash = sha256_json(result.model_dump(mode="json"))
    return _validated(current.model_copy(update={
        "status": RunStatus.RUNNING,
        "current_node": "review-report",
        "report": result,
        "report_revision": current.report_revision + 1,
        "report_hash": report_hash,
        "evidence_cells": result.evidence_cells,
        "model_call_count": current.model_call_count + 1,
    }).model_dump(mode="json"))


def _review_report(state: dict[str, object], *, deps: _Dependencies) -> dict[str, object]:
    current = _state(state)
    if current.report is None:
        return _failed(current, "REPORT_MISSING")
    candidate_ids = {item.candidate_id for item in current.request.candidates}
    dimension_ids = {item.dimension_id for item in current.request.dimensions}
    pairs = [(cell.candidate_id, cell.dimension_id) for cell in current.report.evidence_cells]
    if len(pairs) != len(set(pairs)) or set(pairs) != {(c, d) for c in candidate_ids for d in dimension_ids}:
        return _failed(current, "REPORT_MATRIX_INCOMPLETE_OR_DUPLICATE")
    if current.report.recommendation is not None and current.report.recommendation not in candidate_ids:
        return _failed(current, "REPORT_RECOMMENDATION_OUTSIDE_SCOPE")
    for cell in current.report.evidence_cells:
        if cell.candidate_id not in candidate_ids or cell.dimension_id not in dimension_ids:
            return _failed(current, "REPORT_SCOPE_INVALID")
        if not set(cell.evidence_ids) <= {item.evidence_id for item in current.evidence}:
            return _failed(current, "REPORT_CITATION_OUTSIDE_READ_SET")
        if any(item.candidate_id not in {None, cell.candidate_id} for item in current.evidence if item.evidence_id in cell.evidence_ids):
            return _failed(current, "REPORT_CITATION_CANDIDATE_MISMATCH")
    decision_has_choice = current.report.decision_status in {
        DecisionStatus.RECOMMENDED, DecisionStatus.CONDITIONAL,
    }
    deterministic_findings = []
    if decision_has_choice != (current.report.recommendation is not None):
        deterministic_findings.append("REPORT_DECISION_INCONSISTENT")
    if _has_overbroad_absence_claim(current.report):
        deterministic_findings.append("REPORT_SCOPE_CLAIM_INVALID")
    if deterministic_findings:
        return _validated(current.model_copy(update={
            "status": RunStatus.REPORT_NEEDS_HUMAN,
            "current_node": "report-gate",
            "review_findings": tuple(deterministic_findings),
        }).model_dump(mode="json"))
    try:
        review = _model_call(
            current,
            deps,
            task="review",
            payload={
                "request": current.request.model_dump(mode="json"),
                "report": current.report.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in current.evidence],
            },
        )
    except (ModelClientError, LedgerError) as exc:
        return _failed(current, str(exc))
    if not review.review_completed:
        return _failed(current, "MODEL_REVIEW_INCOMPLETE")
    # Persist the paused status before the interrupt node runs. LangGraph
    # checkpoints the state produced by the previous node; marking the gate
    # here keeps status/status polling truthful across process restarts.
    return _validated(current.model_copy(update={
        "status": RunStatus.REPORT_NEEDS_HUMAN,
        "current_node": "report-gate",
        "model_call_count": current.model_call_count + 1,
        "review_findings": review.review_findings,
    }).model_dump(mode="json"))


def _report_gate(state: dict[str, object], *, deps: _Dependencies) -> dict[str, object]:
    current = _state(state)
    pause = {
        "gate": "report",
        "run_id": current.run_id,
        "thread_id": current.thread_id,
        "report_revision": current.report_revision,
        "report_hash": current.report_hash,
        "decision_status": current.report.decision_status.value if current.report and current.report.decision_status else None,
        "review_findings": list(current.review_findings),
        "message": "Approve, request changes, reject or cancel this report.",
    }
    raw_decision = interrupt(pause)
    if not isinstance(raw_decision, dict):
        return _failed(current, "REPORT_DECISION_INVALID")
    if raw_decision.get("run_id") != current.run_id or raw_decision.get("thread_id") != current.thread_id:
        return _failed(current, "REPORT_DECISION_IDENTITY_MISMATCH")
    if raw_decision.get("report_hash") != current.report_hash or raw_decision.get("report_revision") != current.report_revision:
        return _failed(current, "REPORT_DECISION_BINDING_MISMATCH")
    try:
        action = HumanAction(str(raw_decision.get("action")))
    except ValueError:
        return _failed(current, "REPORT_DECISION_ACTION_INVALID")
    if action is HumanAction.APPROVE:
        if current.report is None or current.report_hash != sha256_json(current.report.model_dump(mode="json")):
            return _failed(current, "REPORT_CONTENT_HASH_MISMATCH")
        if _blocking_report_error(current.report):
            return _failed(current, "REPORT_APPROVAL_BLOCKED")
        return _validated(current.model_copy(update={
            "status": RunStatus.EXPORT_READY,
            "current_node": "export-report",
            "approved_report_revision": current.report_revision,
            "approved_report_hash": current.report_hash,
        }).model_dump(mode="json"))
    if action is HumanAction.REQUEST_CHANGES:
        if current.report_revision >= 2:
            return _failed(current, "REPORT_REVISION_LIMIT_EXHAUSTED")
        feedback = raw_decision.get("feedback", "")
        if not isinstance(feedback, str) or len(feedback) > 900:
            return _failed(current, "REPORT_FEEDBACK_INVALID")
        findings = current.review_findings
        if feedback.strip():
            findings = (*findings, feedback.strip())
        return _validated(current.model_copy(update={
            "status": RunStatus.RUNNING,
            "current_node": "draft-report",
            "report": None,
            "evidence_cells": (),
            # Keep the concrete feedback for the next draft payload. A new
            # review replaces it only after that draft has been checked.
            "review_findings": findings,
            "report_hash": None,
            "report_revision": current.report_revision,
        }).model_dump(mode="json"))
    if action is HumanAction.CANCEL:
        return _validated(current.model_copy(update={"status": RunStatus.CANCELLED, "current_node": "end"}).model_dump(mode="json"))
    return _validated(current.model_copy(update={"status": RunStatus.FAILED, "current_node": "end", "errors": (*current.errors, "REPORT_REJECTED")}).model_dump(mode="json"))


def _export_report(state: dict[str, object], *, deps: _Dependencies) -> dict[str, object]:
    current = _state(state)
    if current.report is None or current.approved_report_hash is None:
        return _failed(current, "EXPORT_REQUIRES_APPROVED_REPORT")
    if (current.approved_report_revision != current.report_revision
            or current.approved_report_hash != current.report_hash
            or current.report_hash != sha256_json(current.report.model_dump(mode="json"))):
        return _failed(current, "EXPORT_APPROVAL_BINDING_MISMATCH")
    if _blocking_report_error(current.report):
        return _failed(current, "REPORT_APPROVAL_BLOCKED")
    try:
        artifact_id, _, _ = deps.exporter.export(
            run_id=current.run_id,
            request=current.request,
            report=current.report,
            report_revision=current.report_revision,
            evidence=current.evidence,
        )
    except ExportError as exc:
        return _failed(current, str(exc))
    except Exception:
        return _failed(current, "V2_EXPORT_FAILED")
    return _validated(current.model_copy(update={
        "status": RunStatus.COMPLETED,
        "current_node": "end",
        "artifact_id": artifact_id,
    }).model_dump(mode="json"))


def _route_requirements(state: dict[str, object]) -> str:
    current = _state(state)
    if current.current_node == "plan-research" and current.status is RunStatus.RUNNING:
        return "plan"
    if current.current_node == "requirements-gate" and current.status is RunStatus.RUNNING:
        return "requirements"
    return "end"


def _coverage_query(dimension: DimensionSpec) -> str:
    """Use stable request dimensions, not a model's free-form query, for coverage."""

    aliases = {
        "state-model": "state structured output schema",
        "human-approval": "human approval interrupt approval",
        "recovery": "persistence recovery durable execution checkpoint",
    }
    terms = aliases.get(
        dimension.dimension_id,
        dimension.dimension_id.replace("-", " "),
    )
    return f"{terms} {dimension.question}"


def _blocking_report_error(report: ModelResult) -> bool:
    """Recheck deterministic content invariants at approval and publication."""
    has_choice = report.decision_status in {DecisionStatus.RECOMMENDED, DecisionStatus.CONDITIONAL}
    return has_choice != (report.recommendation is not None) or _has_overbroad_absence_claim(report)


def _has_overbroad_absence_claim(report: ModelResult) -> bool:
    """Reject absence claims about a whole frozen corpus, not scoped unknown cells."""

    text = "\n".join(
        (report.executive_summary, *(cell.claim for cell in report.evidence_cells),
         *(cell.caveat for cell in report.evidence_cells), *report.limitations)
    ).casefold()
    patterns = (
        r"(?:本|该)快照.{0,40}(?:没有|未包含|缺少|未找到|未提供)",
        r"冻结(?:证据|快照).{0,40}(?:没有|未包含|缺少|未找到)",
        r"(?:整个|全部).{0,12}(?:快照|snapshot).{0,40}(?:没有|未包含|缺少|未找到)",
        r"(?:frozen evidence|frozen snapshot).{0,80}(?:has no|contains no|lacks|does not contain)",
        r"(?:whole|entire).{0,20}snapshot.{0,80}(?:has no|contains no|lacks|does not contain)",
    )
    # Scope disclaimers often contain the forbidden words inside a negation.
    # Inspect individual clauses so unrelated neighboring text cannot match.
    for clause in re.split(r"[。！？；;\n]", text):
        for pattern in patterns:
            for match in re.finditer(pattern, clause):
                prefix = clause[max(0, match.start() - 70):match.start()]
                if match.group().startswith(("冻结证据", "冻结快照")) and re.search(
                    r"本次(?:运行)?(?:实际)?(?:读取|已读|提供)(?:的)?\s*$", prefix
                ):
                    continue
                if re.search(
                    r"(?:不代表|并非|不表示|不能说明|不意味着|不等于|不得推断)\s*(?:整个|全部)?\s*$"
                    r"|(?:does not mean|doesn't mean|not imply|must not infer)\s+(?:that\s+)?(?:the\s+)?(?:(?:whole|entire)\s+)?$",
                    prefix,
                ):
                    continue
                return True
    return False


def _route_validate(state: dict[str, object]) -> str:
    current = _state(state)
    if current.current_node == "requirements-gate" and current.status is RunStatus.NEEDS_HUMAN:
        return "gate"
    return "end"


def _route_report(state: dict[str, object]) -> str:
    current = _state(state)
    if current.current_node == "draft-report" and current.status is RunStatus.RUNNING:
        return "draft"
    if current.current_node == "export-report" and current.status is RunStatus.EXPORT_READY:
        return "export"
    return "end"


def _route_plan(state: dict[str, object]) -> str:
    current = _state(state)
    if current.current_node == "execute-tools" and current.status is RunStatus.RUNNING:
        return "execute"
    return "end"


def _route_execute(state: dict[str, object]) -> str:
    current = _state(state)
    if current.current_node == "draft-report" and current.status is RunStatus.RUNNING:
        return "draft"
    return "end"


def _route_draft(state: dict[str, object]) -> str:
    current = _state(state)
    if current.current_node == "review-report" and current.status is RunStatus.RUNNING:
        return "review"
    return "end"


def _route_review(state: dict[str, object]) -> str:
    current = _state(state)
    if current.current_node == "report-gate" and current.status is RunStatus.REPORT_NEEDS_HUMAN:
        return "gate"
    return "end"


def _model_call(
    state: RuntimeStateV2,
    deps: _Dependencies,
    *,
    task: str,
    payload: dict[str, object],
) -> ModelResult:
    if state.request.model_config_hash != deps.model.config_hash:
        raise ModelClientError("MODEL_CONFIGURATION_MISMATCH")
    if state.request.source_snapshot_id != deps.source_store.snapshot.snapshot_id:
        raise ModelClientError("SOURCE_SNAPSHOT_MISMATCH")
    if state.request.budget_authorization_id != deps.budget.authorization_id:
        raise ModelClientError("BUDGET_AUTHORIZATION_MISMATCH")
    if not deps.budget.approved:
        raise ModelClientError("BUDGET_AUTHORIZATION_REQUIRED")
    if state.model_call_count >= deps.budget.max_model_calls:
        raise ModelClientError("MODEL_CALL_BUDGET_EXHAUSTED")
    _enforce_worst_case_budget(deps)
    payload_hash = request_hash(payload)
    key = logical_call_key(
        run_id=state.run_id,
        node=task,
        request_hash_value=payload_hash,
        snapshot_id=state.request.source_snapshot_id,
        prompt_hash=sha256_json({"task": task, "contract": "model-result-v2"}),
        model_config_hash=state.request.model_config_hash,
        logical_revision=state.report_revision,
    )
    existing = deps.ledger.reserve(
        logical_call_key=key,
        run_id=state.run_id,
        node=task,
        provider=deps.model.provider,
        model_id=deps.model.model_id,
        request_hash=payload_hash,
    )
    if existing.status is CallStatus.SUCCEEDED:
        cached = deps.ledger.cached_response(key)
        if cached is None:
            raise LedgerError("LEDGER_SUCCEEDED_RESPONSE_MISSING")
        cached_result = ModelResult.model_validate_json(cached)
        _enforce_usage_budget(state, deps, cached_result, include_result=False)
        if cached_result.usage.cost_status.value == "unknown":
            raise ModelClientError("MODEL_USAGE_UNKNOWN_REQUIRES_REVIEW")
        return cached_result
    if existing.status in {CallStatus.UNKNOWN, CallStatus.DISPATCHED}:
        raise ModelClientError("MODEL_CALL_STATUS_UNKNOWN_REQUIRES_REVIEW")
    bounds = getattr(deps.model, "reservation_bounds", None)
    if bounds is not None:
        input_bound, output_bound = bounds(task=task, payload=payload)
        cost_bound = deps.model.estimate_cost_minor_units(input_tokens=input_bound, output_tokens=output_bound)
        if cost_bound is None:
            raise ModelClientError("MODEL_USAGE_UNKNOWN_REQUIRES_REVIEW")
        deps.ledger.reserve_budget(key=key, budget=deps.budget, input_tokens=input_bound,
                                   output_tokens=output_bound, cost_minor_units=cost_bound)
        if deps.total_budget_ledger is not None and deps.total_budget is not None:
            total_key = sha256_json(
                {
                    "schema_version": "p2-total-budget-reservation-v1",
                    "total_authorization_id": deps.total_budget.authorization_id,
                    "local_call_key": key,
                }
            )
            deps.total_budget_ledger.reserve_budget(
                key=total_key,
                budget=deps.total_budget,
                input_tokens=input_bound,
                output_tokens=output_bound,
                cost_minor_units=cost_bound,
            )
    deps.ledger.mark_dispatched(key)
    try:
        result = deps.model.generate(task=task, payload=payload)
    except ModelClientError as exc:
        # The provider may have received the request before returning this
        # stable diagnostic. Keep the operator-facing state generic, but put
        # the safe transport/HTTP code in the local ledger for diagnosis.
        deps.ledger.record_failure(
            logical_call_key=key,
            error_code=str(exc),
            unknown=True,
            usage=getattr(exc, "usage", None),
        )
        raise ModelClientError("MODEL_CALL_UNKNOWN_REQUIRES_REVIEW") from exc
    except Exception as exc:
        deps.ledger.record_failure(logical_call_key=key, error_code="MODEL_CALL_UNKNOWN", unknown=True)
        raise ModelClientError("MODEL_CALL_UNKNOWN_REQUIRES_REVIEW") from exc
    response_payload = result.model_dump(mode="json")
    deps.ledger.record_success(
        logical_call_key=key,
        response_hash=hashlib.sha256(canonical_json(response_payload).encode("utf-8")).hexdigest(),
        response_payload=response_payload,
        usage=result.usage,
    )
    # Persist a valid response before deciding whether its usage exceeds the
    # authorization. A sent response must remain replayable even when the
    # graph stops on a budget violation.
    _enforce_usage_budget(state, deps, result, include_result=False)
    if result.usage.cost_status.value == "unknown":
        raise ModelClientError("MODEL_USAGE_UNKNOWN_REQUIRES_REVIEW")
    return result


def _enforce_usage_budget(
    state: RuntimeStateV2,
    deps: _Dependencies,
    result: ModelResult,
    *,
    include_result: bool,
) -> None:
    records = deps.ledger.records_for_run(state.run_id)
    known_cost_minor_units = sum(
        item.usage.cost_minor_units
        for item in records
        if item.status is CallStatus.SUCCEEDED
        and item.usage is not None
        and item.usage.cost_status.value == "known"
        and item.usage.cost_minor_units is not None
    )
    input_tokens = sum(
        (item.usage.input_tokens if item.usage and item.usage.input_tokens is not None else 0)
        for item in records
        if item.status is CallStatus.SUCCEEDED
    )
    output_tokens = sum(
        (item.usage.output_tokens if item.usage and item.usage.output_tokens is not None else 0)
        for item in records
        if item.status is CallStatus.SUCCEEDED
    )
    if include_result:
        input_tokens += result.usage.input_tokens or 0
        output_tokens += result.usage.output_tokens or 0
        if (
            result.usage.cost_status.value == "known"
            and result.usage.cost_minor_units is not None
        ):
            known_cost_minor_units += result.usage.cost_minor_units
    if known_cost_minor_units > deps.budget.max_cost_minor_units:
        raise ModelClientError("MODEL_COST_BUDGET_EXCEEDED")
    if input_tokens > deps.budget.max_input_tokens:
        raise ModelClientError("MODEL_INPUT_TOKEN_BUDGET_EXCEEDED")
    if output_tokens > deps.budget.max_output_tokens:
        raise ModelClientError("MODEL_OUTPUT_TOKEN_BUDGET_EXCEEDED")


def _enforce_worst_case_budget(deps: _Dependencies) -> None:
    """Refuse calls when the authorization's complete token maxima exceed its cost cap."""

    estimate = deps.model.estimate_cost_minor_units(
        input_tokens=deps.budget.max_input_tokens,
        output_tokens=deps.budget.max_output_tokens,
    )
    if estimate is not None and estimate > deps.budget.max_cost_minor_units:
        raise ModelClientError("MODEL_WORST_CASE_COST_EXCEEDS_AUTHORIZATION")


def _failed(state: RuntimeStateV2, code: str) -> dict[str, object]:
    errors = tuple(dict.fromkeys((*state.errors, code)))
    if code in {
        "MODEL_CALL_UNKNOWN_REQUIRES_REVIEW",
        "MODEL_USAGE_UNKNOWN_REQUIRES_REVIEW",
        "MODEL_CALL_STATUS_UNKNOWN_REQUIRES_REVIEW",
        "BUDGET_DISPATCH_ALREADY_RESERVED_REQUIRES_REVIEW",
    }:
        return _validated(state.model_copy(update={
            "status": RunStatus.RECOVERY_REVIEW,
            "current_node": "end",
            "unknown_call_count": state.unknown_call_count + (
                1 if code == "MODEL_CALL_UNKNOWN_REQUIRES_REVIEW" else 0
            ),
            "errors": errors,
        }).model_dump(mode="json"))
    return _validated(state.model_copy(update={
        "status": RunStatus.FAILED,
        "current_node": "end",
        "errors": errors,
    }).model_dump(mode="json"))
