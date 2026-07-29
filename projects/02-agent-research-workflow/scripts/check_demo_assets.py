"""Rebuild and verify committed offline demo SVG assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
ASSET_ROOT = PROJECT_ROOT / "demo" / "assets"
TERMINAL_PATH = ASSET_ROOT / "offline-demo-terminal.svg"
WORKFLOW_PATH = ASSET_ROOT / "workflow-overview.svg"
sys.path.insert(0, str(SOURCE_ROOT))

from agent_research.demo_assets import (  # noqa: E402
    render_terminal_demo_svg,
    render_workflow_overview_svg,
)
from agent_research.demo_runner import run_offline_demo  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild deterministic P2 demo SVGs in memory.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare rebuilt SVGs with committed files",
    )
    return parser.parse_args()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> None:
    args = parse_args()
    run = run_offline_demo(PROJECT_ROOT)
    terminal = render_terminal_demo_svg(run.bundle.to_text())
    workflow = render_workflow_overview_svg()
    if args.check:
        if TERMINAL_PATH.read_text(encoding="utf-8") != terminal:
            raise SystemExit("DEMO_TERMINAL_SVG_MISMATCH")
        if WORKFLOW_PATH.read_text(encoding="utf-8") != workflow:
            raise SystemExit("DEMO_WORKFLOW_SVG_MISMATCH")
        print("demo SVG assets: passed")
        return
    print(
        json.dumps(
            {
                "offline-demo-terminal.svg": _digest(terminal),
                "workflow-overview.svg": _digest(workflow),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
