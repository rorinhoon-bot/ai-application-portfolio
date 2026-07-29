"""Run or verify one deterministic machine-readable workflow summary."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
SUMMARY_PATH = (
    PROJECT_ROOT
    / "evals"
    / "results"
    / "privacy-durable-run-summary.json"
)
sys.path.insert(0, str(SOURCE_ROOT))

from agent_research.evaluation_runner import run_case_observability  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen privacy case with deterministic tracing.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the actual summary with the committed sample",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    actual = run_case_observability(PROJECT_ROOT).to_json()
    if not args.check:
        print(actual, end="")
        return

    expected = SUMMARY_PATH.read_text(encoding="utf-8")
    if actual != expected:
        raise SystemExit("OBSERVABILITY_SUMMARY_MISMATCH")
    print("run-summary-v1 sample: passed")


if __name__ == "__main__":
    main()
