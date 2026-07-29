"""Run or verify the committed deterministic workflow-v1 baseline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
BASELINE_PATH = PROJECT_ROOT / "evals" / "results" / "workflow-v1-baseline.json"
sys.path.insert(0, str(SOURCE_ROOT))

from agent_research.evaluation_runner import run_workflow_evaluation  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen workflow-v1 evaluation offline.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the actual result with the committed baseline",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    actual = run_workflow_evaluation(PROJECT_ROOT).to_json()
    if not args.check:
        print(actual, end="")
        return

    expected = BASELINE_PATH.read_text(encoding="utf-8")
    if actual != expected:
        raise SystemExit("WORKFLOW_BASELINE_MISMATCH")
    print("workflow-v1 baseline: passed")


if __name__ == "__main__":
    main()
