"""Validate or execute the explicitly frozen P2 V2 source plan.

The default ``check`` command is offline. ``collect`` refuses proposed plans
and requires an exact plan id, so source downloads cannot happen implicitly.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent_research.v2.source_collector import (  # noqa: E402
    SourceCollectionError,
    collect_snapshot,
    load_source_plan,
    write_snapshot_manifest,
)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        plan = load_source_plan(_path(args.plan), require_frozen=args.command == "collect")
        if args.command == "check":
            _print(
                {
                    "plan_id": plan.plan_id,
                    "status": plan.status,
                    "source_count": len(plan.items),
                    "max_pages": plan.max_pages,
                    "max_total_bytes": plan.policy.max_total_bytes,
                    "allowed_hosts": sorted(plan.policy.allowed_hosts),
                }
            )
            return 0
        if args.confirm_plan_id != plan.plan_id:
            raise SourceCollectionError("SOURCE_PLAN_CONFIRMATION_MISMATCH")
        if args.output_root is None or args.manifest is None:
            raise SourceCollectionError("SOURCE_OUTPUT_REQUIRED")
        output_root = _path(args.output_root)
        if args.allow_local_proxy:
            plan = replace(plan, policy=replace(plan.policy, allow_local_proxy=True))
        snapshot = collect_snapshot(
            plan=plan.items,
            policy=plan.policy,
            output_root=output_root,
        )
        manifest = _path(args.manifest)
        write_snapshot_manifest(snapshot, manifest)
        _print(
            {
                "plan_id": plan.plan_id,
                "status": plan.status,
                "snapshot_id": snapshot.snapshot_id,
                "source_count": len(snapshot.entries),
                "total_size_bytes": snapshot.total_size_bytes,
                "manifest": str(manifest),
            }
        )
        return 0
    except (OSError, SourceCollectionError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check or collect P2 V2 official sources")
    parser.add_argument(
        "--plan",
        default=str(PROJECT_ROOT / "docs" / "v2" / "source-plan-v1.json"),
        help="versioned source-plan-v1.json",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="validate plan only; never performs network I/O")
    collect = sub.add_parser("collect", help="download a frozen plan")
    collect.add_argument("--confirm-plan-id", required=True)
    collect.add_argument("--output-root", required=True)
    collect.add_argument("--manifest", required=True)
    collect.add_argument(
        "--allow-local-proxy",
        action="store_true",
        help="explicitly allow configured localhost HTTP(S) proxy; target URL checks remain active",
    )
    return parser


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _print(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
