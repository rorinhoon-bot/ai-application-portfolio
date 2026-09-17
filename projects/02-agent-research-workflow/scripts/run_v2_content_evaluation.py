"""Run frozen V2 content inputs; rubric remains outside production workflow."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER = PROJECT_ROOT / "scripts" / "run_research_v2.py"
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_research.v2.contracts import BudgetAuthorization, ResearchRequestV2
from agent_research.v2.model_client import (
    DeepSeekV4FlashClient,
    DeepSeekV4FlashPriceCard,
    ScriptedModelClient,
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("EVALUATION_JSON_OBJECT_REQUIRED")
    return value


def _request_for_case(
    *,
    case: dict[str, Any],
    defaults: dict[str, Any],
    snapshot_id: str,
    model_config_hash: str,
    budget_authorization_id: str,
) -> ResearchRequestV2:
    if not isinstance(case.get("research_question"), str):
        raise ValueError("EVALUATION_CASE_QUESTION_REQUIRED")
    dimensions = list(defaults["dimensions"])
    if case.get("case_id") == "dev-weight-change":
        dimensions = [
            {**dimensions[0], "weight_percent": 20},
            {**dimensions[1], "weight_percent": 60},
            {**dimensions[2], "weight_percent": 20},
        ]
    return ResearchRequestV2.model_validate(
        {
            "research_question": case["research_question"],
            "audience": defaults["audience"],
            "candidates": defaults["candidates"],
            "dimensions": dimensions,
            "hard_constraints": defaults["hard_constraints"],
            "source_snapshot_id": snapshot_id,
            "model_config_hash": model_config_hash,
            "budget_authorization_id": budget_authorization_id,
            "allow_insufficient_evidence": True,
        }
    )


def _run_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode:
        return {"status": "CLI_ERROR", "errors": ["EVALUATION_CLI_FAILED"]}
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("EVALUATION_CLI_OBJECT_REQUIRED")
    return value


def _summary(case: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    evidence = {item["evidence_id"] for item in state.get("evidence", []) if isinstance(item, dict)}
    report = state.get("report") if isinstance(state.get("report"), dict) else {}
    cells = report.get("evidence_cells", [])
    cited = [
        evidence_id for cell in cells if isinstance(cell, dict)
        for evidence_id in cell.get("evidence_ids", [])
    ]
    return {
        "case_id": case["case_id"],
        "split": case["split"],
        "status": state.get("status"),
        "errors": state.get("errors", []),
        "review_findings": state.get("review_findings", []),
        "artifact_id": state.get("artifact_id"),
        "model_call_count": state.get("model_call_count", 0),
        "tool_call_count": state.get("tool_call_count", 0),
        "decision_status": report.get("decision_status"),
        "citation_identity_valid": bool(cited) and set(cited) <= evidence,
        "semantic_support": "N/A_REQUIRES_HUMAN_REVIEW",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run frozen V2 evaluation inputs")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--inputs", default=str(PROJECT_ROOT / "evals" / "v2" / "content-inputs-v1.json"))
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--sources-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--budget-file")
    parser.add_argument("--total-budget-file")
    parser.add_argument("--total-budget-ledger")
    parser.add_argument("--price-card-file")
    parser.add_argument("--env-file", default=str(PROJECT_ROOT / ".env"))
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--start-index", type=int, default=1, help="one-based frozen case index")
    parser.add_argument(
        "--case-ids",
        help="comma-separated frozen case IDs; preserves source-file order and stops on first recovery",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 12 or not 1 <= args.start_index <= 12:
        raise ValueError("EVALUATION_LIMIT_INVALID")
    inputs = _load_json(Path(args.inputs))
    if inputs.get("schema_version") != "v2-content-inputs-v1":
        raise ValueError("EVALUATION_INPUT_VERSION_INVALID")
    cases = inputs.get("cases")
    defaults = inputs.get("request_defaults")
    if not isinstance(cases, list) or not isinstance(defaults, dict) or not 1 <= len(cases) <= 12:
        raise ValueError("EVALUATION_INPUTS_INVALID")
    runtime = Path(args.runtime_root).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    if args.mode == "live":
        if not args.budget_file or not args.price_card_file or not args.total_budget_file or not args.total_budget_ledger:
            raise ValueError("EVALUATION_LIVE_BUDGET_PRICE_CARD_AND_TOTAL_REQUIRED")
        budget = BudgetAuthorization.model_validate_json(Path(args.budget_file).read_text(encoding="utf-8"))
        card = DeepSeekV4FlashPriceCard.model_validate_json(Path(args.price_card_file).read_text(encoding="utf-8"))
        model_hash = DeepSeekV4FlashClient(live=False, price_card=card).config_hash
    else:
        budget = BudgetAuthorization(
            authorization_id="budget-offline", max_cost_minor_units=0, max_model_calls=12,
            max_input_tokens=48_000, max_output_tokens=12_000, expires_at="2099-01-01T00:00:00Z", approved=True,
        )
        model_hash = ScriptedModelClient().config_hash
    base = [sys.executable, str(RUNNER), "--mode", args.mode, "--runtime-root", str(runtime),
            "--sources-root", args.sources_root, "--manifest", args.manifest, "--env-file", args.env_file]
    if args.mode == "live":
        base += [
            "--budget-file", args.budget_file,
            "--price-card-file", args.price_card_file,
            "--total-budget-file", args.total_budget_file,
            "--total-budget-ledger", args.total_budget_ledger,
        ]
    summaries: list[dict[str, Any]] = []
    index_by_case_id = {case.get("case_id"): index for index, case in enumerate(cases, start=1)}
    if args.case_ids:
        if args.limit != 12 or args.start_index != 1:
            raise ValueError("EVALUATION_CASE_SELECTION_CONFLICT")
        requested_ids = [item.strip() for item in args.case_ids.split(",") if item.strip()]
        if not requested_ids or len(set(requested_ids)) != len(requested_ids):
            raise ValueError("EVALUATION_CASE_IDS_INVALID")
        if any(case_id not in index_by_case_id for case_id in requested_ids):
            raise ValueError("EVALUATION_CASE_IDS_INVALID")
        selected_cases = [case for case in cases if case["case_id"] in set(requested_ids)]
    else:
        selected_cases = cases[args.start_index - 1:args.start_index - 1 + args.limit]
    for case in selected_cases:
        index = index_by_case_id[case["case_id"]]
        request = _request_for_case(case=case, defaults=defaults, snapshot_id=inputs["source_snapshot_id"],
                                    model_config_hash=model_hash, budget_authorization_id=budget.authorization_id)
        request_path = runtime / "requests" / f"{case['case_id']}.json"
        request_path.parent.mkdir(exist_ok=True)
        request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")
        thread_id = f"eval-{index:02d}-{case['case_id']}"
        state = _run_command(base + ["start", "--request", str(request_path), "--run-id", thread_id, "--thread-id", thread_id])
        if state.get("status") == "NEEDS_HUMAN":
            state = _run_command(base + ["resume", "--thread-id", thread_id, "--action", "approve"])
        if state.get("status") == "REPORT_NEEDS_HUMAN" and state.get("review_findings") == []:
            state = _run_command(base + ["resume", "--thread-id", thread_id, "--action", "approve"])
        summaries.append(_summary(case, state))
        if state.get("status") in {"RECOVERY_REVIEW", "CLI_ERROR", "FAILED", "REPORT_NEEDS_HUMAN"}:
            break
    manifest = {
        "schema_version": "v2-content-evaluation-result-v1",
        "input_schema_version": inputs["schema_version"],
        "snapshot_id": inputs["source_snapshot_id"],
        "mode": args.mode,
        "cases_attempted": len(summaries),
        "cases_completed": sum(item["status"] == "COMPLETED" for item in summaries),
        "results": summaries,
        "semantic_quality": "N/A_REQUIRES_HUMAN_REVIEW",
    }
    output = runtime / "evaluation-manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
