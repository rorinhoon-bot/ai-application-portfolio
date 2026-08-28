"""Create separate Git-ignored Qdrant credential files once."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
from secrets import token_urlsafe

from cited_rag.qdrant_connection import QdrantContainerSecrets

TokenFactory = Callable[[int], str]


@dataclass(frozen=True, slots=True)
class QdrantRuntimePaths:
    server_env: Path
    admin_env: Path
    read_env: Path


def create_qdrant_runtime_files(
    *,
    project_root: Path,
    token_factory: TokenFactory = token_urlsafe,
) -> QdrantRuntimePaths:
    """Generate distinct credentials without printing or overwriting them."""

    root = project_root.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError("project root is not a directory")
    paths = QdrantRuntimePaths(
        server_env=root / ".env.qdrant-server",
        admin_env=root / ".env.qdrant-admin",
        read_env=root / ".env.qdrant-read",
    )
    targets = (paths.server_env, paths.admin_env, paths.read_env)
    if any(target.exists() or target.is_symlink() for target in targets):
        raise FileExistsError("Qdrant runtime file already exists")

    admin_key = token_factory(48)
    read_only_key = token_factory(48)
    QdrantContainerSecrets(
        _env_file=None,
        qdrant_admin_api_key=admin_key,
        qdrant_read_only_api_key=read_only_key,
    )
    contents = {
        paths.server_env: (
            f"QDRANT_ADMIN_API_KEY={admin_key}\n"
            f"QDRANT_READ_ONLY_API_KEY={read_only_key}\n"
        ),
        paths.admin_env: (
            "QDRANT_URL=http://127.0.0.1:6333\n"
            f"QDRANT_ADMIN_API_KEY={admin_key}\n"
            "QDRANT_TIMEOUT_SECONDS=10\n"
        ),
        paths.read_env: (
            "QDRANT_PROFILE=server\n"
            "QDRANT_URL=http://127.0.0.1:6333\n"
            f"QDRANT_READ_ONLY_API_KEY={read_only_key}\n"
            "QDRANT_TIMEOUT_SECONDS=10\n"
        ),
    }

    created: list[Path] = []
    try:
        for target, content in contents.items():
            with target.open("x", encoding="utf-8", newline="\n") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.chmod(target, 0o600)
            created.append(target)
    except Exception:
        for target in created:
            target.unlink(missing_ok=True)
        raise
    return paths
