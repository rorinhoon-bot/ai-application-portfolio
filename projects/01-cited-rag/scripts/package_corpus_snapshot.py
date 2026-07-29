"""Create the approved deterministic corpus archive."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.corpus_snapshot import package_corpus_snapshot  # noqa: E402


def main() -> int:
    report = package_corpus_snapshot(
        source_root=PROJECT_ROOT / "data" / "sources",
        acquisition_report_path=(
            PROJECT_ROOT / "data" / "sources" / "acquisition-report.json"
        ),
        archive_path=PROJECT_ROOT / "data" / "corpus-snapshot.zip",
        snapshot_report_path=(
            PROJECT_ROOT / "data" / "corpus-snapshot.json"
        ),
    )
    print(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
