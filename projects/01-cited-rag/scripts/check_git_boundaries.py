"""Fail when generated secrets, model assets, or private snapshots enter Git."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
import subprocess


FORBIDDEN_NAMES = {".env", ".env.local", ".env.development", ".env.production"}
FORBIDDEN_SUFFIXES = {
    ".bin",
    ".gguf",
    ".key",
    ".pem",
    ".safetensors",
}
FORBIDDEN_PREFIXES = (
    "data/indexes/",
    "data/server-indexes/",
    "data/sources/html/",
    "data/sources/license/",
    "data/models/",
)


def tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return [item for item in completed.stdout.decode().split("\0") if item]


def main() -> int:
    violations: list[str] = []
    for raw_path in tracked_files():
        path = PurePosixPath(raw_path)
        normalized = path.as_posix().lower()
        name = path.name.lower()
        if name in FORBIDDEN_NAMES or (
            name.startswith(".env.") and name != ".env.example"
        ):
            violations.append(raw_path)
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            violations.append(raw_path)
        if normalized.startswith(FORBIDDEN_PREFIXES):
            violations.append(raw_path)
    if violations:
        print(json.dumps({"status": "failed", "violations": sorted(set(violations))}))
        return 1
    print(
        json.dumps(
            {"status": "passed", "tracked_file_count": len(tracked_files())},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
