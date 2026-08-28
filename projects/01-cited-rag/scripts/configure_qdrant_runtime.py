"""Generate Qdrant runtime credentials without exposing their values."""

from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.qdrant_runtime_files import (  # noqa: E402
    create_qdrant_runtime_files,
)


def main() -> int:
    paths = create_qdrant_runtime_files(project_root=PROJECT_ROOT)
    print(
        json.dumps(
            {
                "status": "created",
                "files": [
                    path.relative_to(PROJECT_ROOT).as_posix()
                    for path in (
                        paths.server_env,
                        paths.admin_env,
                        paths.read_env,
                    )
                ],
                "secrets_printed": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
