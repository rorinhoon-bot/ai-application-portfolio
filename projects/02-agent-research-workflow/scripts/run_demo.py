"""Run or verify the fixed offline portfolio demonstration."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
GENERATED_ROOT = PROJECT_ROOT / "demo" / "generated"
MANIFEST_PATH = GENERATED_ROOT / "offline-demo-v1.json"
REVIEW_REPORT_PATH = GENERATED_ROOT / "report-v2.md"
REVIEW_REPORT_HASH_PATH = GENERATED_ROOT / "report-v2.md.sha256"
SUMMARY_PATH = (
    PROJECT_ROOT
    / "evals"
    / "results"
    / "privacy-durable-run-summary.json"
)
REPARSE_POINT_FLAG = 0x400
sys.path.insert(0, str(SOURCE_ROOT))

from agent_research.demo_runner import run_offline_demo  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run fixed pause, success, failure, and trace stories.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--json",
        action="store_true",
        help="print the machine-readable demo manifest",
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="compare runtime outputs with committed demo files",
    )
    return parser.parse_args()


def _check_regular_file(path: Path, expected_parent: Path) -> None:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    resolved = path.resolve(strict=True)
    if resolved.parent != expected_parent:
        raise SystemExit("DEMO_FILE_ESCAPES_GENERATED_ROOT")
    if (
        path.is_symlink()
        or bool(attributes & REPARSE_POINT_FLAG)
        or not path.is_file()
    ):
        raise SystemExit("DEMO_FILE_MUST_BE_REGULAR")


def _check_path_chain(root: Path, path: Path) -> None:
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        attributes = getattr(current.lstat(), "st_file_attributes", 0)
        if current.is_symlink() or bool(attributes & REPARSE_POINT_FLAG):
            raise SystemExit("DEMO_COMMITTED_PATH_MUST_NOT_BE_LINK")


def check_committed_outputs(
    manifest: str,
    report_name: str,
    report: bytes,
    summary: str,
) -> None:
    project_root = PROJECT_ROOT.resolve(strict=True)
    _check_path_chain(project_root, GENERATED_ROOT)
    _check_path_chain(project_root, SUMMARY_PATH)
    root_attributes = getattr(
        GENERATED_ROOT.lstat(),
        "st_file_attributes",
        0,
    )
    generated_root = GENERATED_ROOT.resolve(strict=True)
    if (
        GENERATED_ROOT.is_symlink()
        or bool(root_attributes & REPARSE_POINT_FLAG)
        or not GENERATED_ROOT.is_dir()
    ):
        raise SystemExit("DEMO_GENERATED_ROOT_MUST_BE_REGULAR_DIRECTORY")
    manifest_path = GENERATED_ROOT / MANIFEST_PATH.name
    report_path = GENERATED_ROOT / report_name
    expected_names = {
        manifest_path.name,
        report_path.name,
        REVIEW_REPORT_PATH.name,
        REVIEW_REPORT_HASH_PATH.name,
    }
    actual_names = {item.name for item in GENERATED_ROOT.iterdir()}
    if actual_names != expected_names:
        raise SystemExit("DEMO_GENERATED_FILE_SET_MISMATCH")
    _check_regular_file(manifest_path, generated_root)
    _check_regular_file(report_path, generated_root)
    _check_regular_file(REVIEW_REPORT_PATH, generated_root)
    _check_regular_file(REVIEW_REPORT_HASH_PATH, generated_root)
    if manifest_path.read_text(encoding="utf-8") != manifest:
        raise SystemExit("DEMO_MANIFEST_MISMATCH")
    if report_path.read_bytes() != report:
        raise SystemExit("DEMO_REPORT_MISMATCH")
    report_v2_hash = hashlib.sha256(REVIEW_REPORT_PATH.read_bytes()).hexdigest()
    expected_v2_hash_file = f"{report_v2_hash} *{REVIEW_REPORT_PATH.name}\n"
    if REVIEW_REPORT_HASH_PATH.read_text(encoding="utf-8") != expected_v2_hash_file:
        raise SystemExit("DEMO_V2_REPORT_HASH_MISMATCH")
    _check_regular_file(SUMMARY_PATH, SUMMARY_PATH.parent.resolve(strict=True))
    if SUMMARY_PATH.read_text(encoding="utf-8") != summary:
        raise SystemExit("DEMO_RUN_SUMMARY_MISMATCH")


def main() -> None:
    args = parse_args()
    run = run_offline_demo(PROJECT_ROOT)
    if args.check:
        check_committed_outputs(
            run.bundle.to_json(),
            run.bundle.report_file,
            run.report_bytes,
            run.run_summary.to_json(),
        )
        print("offline-demo-v1: passed")
    elif args.json:
        print(run.bundle.to_json(), end="")
    else:
        print(run.bundle.to_text(), end="")


if __name__ == "__main__":
    main()
