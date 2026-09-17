"""CLI for the P2 V2 workflow.

The default mode is fully offline and uses the checked-in scripted model plus
the explicitly synthetic demo snapshot. ``--mode live`` only selects the
DeepSeek adapter; it does not bypass the human and budget gates.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from agent_research.v2.contracts import (  # noqa: E402
    BudgetAuthorization,
    HumanAction,
    ResearchRequestV2,
    RunStatus,
)
from agent_research.v2.exporter import V2Exporter  # noqa: E402
from agent_research.v2.graph import (  # noqa: E402
    build_v2_graph,
    create_initial_state,
    graph_config,
)
from agent_research.v2.ledger import OperationLedger  # noqa: E402
from agent_research.v2.model_client import (  # noqa: E402
    DeepSeekV4FlashClient,
    DeepSeekV4FlashPriceCard,
    ScriptedModelClient,
)
from agent_research.v2.source_store import SourceStore, load_snapshot  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    # Redirected Windows stdout otherwise defaults to GBK, which cannot encode
    # arbitrary source/model text. The CLI's JSON wire format is always UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        _load_optional_p2_env(_path(args.env_file))
        return _run(args)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


def _run(args: argparse.Namespace) -> int:
    if args.command == "live-preflight":
        if args.mode != "live":
            raise ValueError("LIVE_PREFLIGHT_REQUIRES_LIVE_MODE")
        price_card = _price_card(args)
        model = DeepSeekV4FlashClient(live=True, price_card=price_card)
        _print_state(
            {
                "mode": "live",
                "provider": model.provider,
                "model_id": model.model_id,
                "model_config_hash": model.config_hash,
                "api_key_present": True,
                "price_card_hash": price_card.content_hash(),
                "network_accessed": False,
            }
        )
        return 0
    if args.command == "model-config":
        price_card = _price_card(args, required=False)
        model = (
            ScriptedModelClient()
            if args.mode == "offline"
            else DeepSeekV4FlashClient(live=False, price_card=price_card)
        )
        _print_state(
            {
                "mode": args.mode,
                "provider": model.provider,
                "model_id": model.model_id,
                "model_config_hash": model.config_hash,
                "network_accessed": False,
            }
        )
        return 0
    runtime = _path(args.runtime_root)
    source_root = _path(args.sources_root)
    manifest = _path(args.manifest)
    snapshot, texts = load_snapshot(source_root, manifest)
    budget = _budget(args)
    total_budget = _total_budget(args)
    request_arg = getattr(args, "request", None)
    request_path = _path(request_arg) if request_arg else None
    request = _load_request(request_path) if request_path else None
    if request is not None and request.source_snapshot_id != snapshot.snapshot_id:
        raise ValueError("REQUEST_SOURCE_SNAPSHOT_MISMATCH")
    runtime.mkdir(parents=True, exist_ok=True)
    ledger = OperationLedger(runtime / "operations.sqlite3")
    total_budget_ledger = (
        OperationLedger(_path(args.total_budget_ledger), single_authorization=True)
        if total_budget is not None
        else None
    )
    connection = sqlite3.connect(runtime / "checkpoints.sqlite3", check_same_thread=False)
    saver = SqliteSaver(connection)
    saver.setup()
    model = (
        ScriptedModelClient()
        if args.mode == "offline"
        else DeepSeekV4FlashClient(live=True, price_card=_price_card(args))
    )
    graph = build_v2_graph(
        checkpointer=saver,
        model=model,
        source_store=SourceStore(snapshot, texts),
        ledger=ledger,
        budget=budget,
        exporter=V2Exporter(runtime / "artifacts"),
        total_budget_ledger=total_budget_ledger,
        total_budget=total_budget,
    )
    try:
        if args.command == "start":
            if request is None:
                raise ValueError("REQUEST_REQUIRED")
            run_id = args.run_id or _new_id("run")
            thread_id = args.thread_id or run_id
            config = graph_config(thread_id)
            graph.invoke(
                create_initial_state(run_id=run_id, thread_id=thread_id, request=request),
                config, durability="sync",
            )
            _print_state(graph.get_state(config).values)
            return 0
        if not args.thread_id:
            raise ValueError("THREAD_ID_REQUIRED")
        config = graph_config(args.thread_id)
        state = graph.get_state(config).values
        if not state:
            raise ValueError("THREAD_NOT_FOUND")
        if args.command == "status":
            _print_state(state)
            return 0
        if args.command == "recover":
            snapshot = graph.get_state(config)
            state = snapshot.values
            approved_export = (
                state.get("status") == RunStatus.EXPORT_READY.value
                and state.get("report_hash") is not None
                and state.get("approved_report_hash") == state.get("report_hash")
                and state.get("approved_report_revision") == state.get("report_revision")
            )
            if any(task.interrupts for task in snapshot.tasks) and not approved_export:
                # A process can exit before the next checkpoint, after the
                # already-approved gate's resume value was saved as a write.
                saved = saver.get_tuple(config)
                expected = _decision(state, action=HumanAction.APPROVE.value, edit_request=None)
                persisted_approval = any(
                    channel == "__resume__" and (
                        value == expected or (isinstance(value, list) and expected in value)
                    )
                    for _, channel, value in (saved.pending_writes if saved else ())
                )
                if not persisted_approval:
                    raise ValueError("RECOVER_REQUIRES_HUMAN_DECISION")
            if approved_export and "export_report" not in snapshot.next:
                # Legacy async checkpoints may expose the completed gate's
                # state but lose its scheduled next task. Re-materialize only
                # that already-approved transition, never a new approval.
                graph.update_state(config, state, as_node="report_gate")
                snapshot = graph.get_state(config)
            if not snapshot.next:
                _print_state(state)
                return 0
            # Resume pending work without fabricating a human approval. The
            # operation ledger still rejects DISPATCHED/UNKNOWN model calls.
            graph.invoke(None, config, durability="sync")
            _print_state(graph.get_state(config).values)
            return 0
        if args.command in {"resume", "cancel"}:
            if args.command == "cancel":
                action = HumanAction.CANCEL.value
            else:
                action = args.action
            decision = _decision(state, action=action, edit_request=request,
                                 feedback=getattr(args, "feedback", None))
            graph.invoke(Command(resume=decision), config, durability="sync")
            _print_state(graph.get_state(config).values)
            return 0
        raise ValueError("COMMAND_UNSUPPORTED")
    finally:
        ledger.close()
        if total_budget_ledger is not None:
            total_budget_ledger.close()
        connection.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the P2 LangGraph V2 workflow")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--runtime-root", default=str(PROJECT_ROOT / ".runtime" / "p2-v2"))
    parser.add_argument("--sources-root", default=str(PROJECT_ROOT / "demo" / "v2" / "sources"))
    parser.add_argument("--manifest", default=str(PROJECT_ROOT / "demo" / "v2" / "manifest.json"))
    parser.add_argument("--budget-file", help="JSON BudgetAuthorization; required for live mode")
    parser.add_argument(
        "--total-budget-file",
        help="P2-wide JSON BudgetAuthorization; required for live calls and shared across runtime directories",
    )
    parser.add_argument(
        "--total-budget-ledger",
        help="shared SQLite path for --total-budget-file; required for live calls",
    )
    parser.add_argument("--price-card-file", help="reviewed DeepSeek price card; required for live calls")
    parser.add_argument(
        "--env-file",
        default=str(PROJECT_ROOT / ".env"),
        help="optional P2 .env file; existing environment variables take precedence",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "model-config",
        help="print non-secret model configuration hash; never opens network",
    )
    sub.add_parser(
        "live-preflight",
        help="validate local key and price card without opening a network connection",
    )

    start = sub.add_parser("start", help="start a new run and pause at requirements approval")
    start.add_argument("--request", default=str(PROJECT_ROOT / "demo" / "v2" / "request.json"))
    start.add_argument("--run-id")
    start.add_argument("--thread-id")

    for name in ("status", "cancel", "recover"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--thread-id", required=True)

    resume = sub.add_parser("resume", help="resume the current human gate")
    resume.add_argument("--thread-id", required=True)
    resume.add_argument(
        "--action",
        choices=tuple(item.value for item in HumanAction),
        required=True,
    )
    resume.add_argument("--request", help="edited request JSON for --action edit")
    resume.add_argument("--feedback", help="public review feedback, at most 900 characters; request-changes only")
    return parser


def _budget(args: argparse.Namespace) -> BudgetAuthorization:
    if args.mode == "live":
        if not args.budget_file:
            raise ValueError("LIVE_BUDGET_FILE_REQUIRED")
        return BudgetAuthorization.model_validate_json(_path(args.budget_file).read_text(encoding="utf-8"))
    return BudgetAuthorization(
        authorization_id="budget-offline",
        max_cost_minor_units=0,
        max_model_calls=12,
        max_input_tokens=48_000,
        max_output_tokens=12_000,
        expires_at="2099-01-01T00:00:00Z",
        approved=True,
    )


def _total_budget(args: argparse.Namespace) -> BudgetAuthorization | None:
    if args.mode != "live":
        return None
    if not args.total_budget_file:
        raise ValueError("LIVE_TOTAL_BUDGET_FILE_REQUIRED")
    if not args.total_budget_ledger:
        raise ValueError("LIVE_TOTAL_BUDGET_LEDGER_REQUIRED")
    if args.command in {"resume", "recover"}:
        canonical_root = PROJECT_ROOT / ".runtime" / "p2-budget"
        if (_path(args.total_budget_ledger) != (canonical_root / "total.sqlite3").resolve()
                or _path(args.total_budget_file) != (canonical_root / "authorization.json").resolve()):
            raise ValueError("LIVE_TOTAL_BUDGET_PATH_MISMATCH")
        if not (canonical_root / "total.sqlite3").is_file():
            raise ValueError("LIVE_TOTAL_BUDGET_INITIALIZATION_REQUIRED")
    return BudgetAuthorization.model_validate_json(
        _path(args.total_budget_file).read_text(encoding="utf-8")
    )


def _price_card(
    args: argparse.Namespace,
    *,
    required: bool = True,
) -> DeepSeekV4FlashPriceCard | None:
    if not args.price_card_file:
        if required:
            raise ValueError("LIVE_PRICE_CARD_FILE_REQUIRED")
        return None
    return DeepSeekV4FlashPriceCard.model_validate_json(
        _path(args.price_card_file).read_text(encoding="utf-8")
    )


def _load_request(path: Path | None) -> ResearchRequestV2 | None:
    if path is None:
        return None
    return ResearchRequestV2.model_validate_json(path.read_text(encoding="utf-8"))


def _decision(
    state: dict[str, Any],
    *,
    action: str,
    edit_request: ResearchRequestV2 | None,
    feedback: str | None = None,
) -> dict[str, Any]:
    if feedback is not None and (
        action != HumanAction.REQUEST_CHANGES.value
        or state.get("status") != RunStatus.REPORT_NEEDS_HUMAN.value
        or not feedback.strip() or len(feedback) > 900
    ):
        raise ValueError("REPORT_FEEDBACK_INVALID")
    decision: dict[str, Any] = {
        "run_id": state["run_id"],
        "thread_id": state["thread_id"],
        "action": action,
    }
    status = state.get("status")
    if status == RunStatus.NEEDS_HUMAN.value:
        decision["expected_request_hash"] = state["request_hash"]
        if action == HumanAction.EDIT.value:
            if edit_request is None:
                raise ValueError("EDIT_REQUEST_REQUIRED")
            decision["request"] = edit_request.model_dump(mode="json")
    elif status == RunStatus.REPORT_NEEDS_HUMAN.value:
        decision["report_revision"] = state["report_revision"]
        decision["report_hash"] = state["report_hash"]
        if feedback is not None:
            decision["feedback"] = feedback.strip()
    else:
        raise ValueError(f"NO_HUMAN_GATE:{status}")
    return decision


def _new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6)}"


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _load_optional_p2_env(path: Path) -> None:
    """Load only approved P2 runtime variables without printing their values."""

    if not path.exists():
        return
    if not path.is_file() or path.is_symlink():
        raise ValueError("ENV_FILE_INVALID")
    allowed = {
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "LANGGRAPH_STRICT_MSGPACK",
        "LANGSMITH_TRACING",
        "LANGCHAIN_TRACING_V2",
    }
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"ENV_FILE_LINE_INVALID:{line_number}")
        name, value = line.split("=", maxsplit=1)
        name = name.strip()
        if name not in allowed:
            raise ValueError(f"ENV_VARIABLE_NOT_ALLOWED:{name}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def _print_state(state: dict[str, Any]) -> None:
    print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
