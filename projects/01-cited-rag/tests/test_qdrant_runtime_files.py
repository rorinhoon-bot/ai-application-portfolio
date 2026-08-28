from pathlib import Path

import pytest

from cited_rag.qdrant_runtime_files import create_qdrant_runtime_files

ADMIN_KEY = "a" * 64
READ_KEY = "r" * 64


def token_factory() -> object:
    values = iter((ADMIN_KEY, READ_KEY))
    return lambda _bytes: next(values)


def test_runtime_files_separate_admin_and_read_credentials(
    tmp_path: Path,
) -> None:
    paths = create_qdrant_runtime_files(
        project_root=tmp_path,
        token_factory=token_factory(),
    )
    server = paths.server_env.read_text(encoding="utf-8")
    admin = paths.admin_env.read_text(encoding="utf-8")
    read = paths.read_env.read_text(encoding="utf-8")

    assert ADMIN_KEY in server and READ_KEY in server
    assert ADMIN_KEY in admin and READ_KEY not in admin
    assert READ_KEY in read and ADMIN_KEY not in read
    assert "QDRANT_PROFILE=server" in read
    assert "QDRANT_URL=http://127.0.0.1:6333" in admin
    assert "QDRANT_URL=http://127.0.0.1:6333" in read


def test_runtime_files_never_overwrite_existing_credentials(
    tmp_path: Path,
) -> None:
    existing = tmp_path / ".env.qdrant-admin"
    existing.write_text("keep-this-byte-for-byte\n", encoding="utf-8")
    original = existing.read_bytes()

    with pytest.raises(FileExistsError, match="already exists"):
        create_qdrant_runtime_files(
            project_root=tmp_path,
            token_factory=token_factory(),
        )

    assert existing.read_bytes() == original
    assert not (tmp_path / ".env.qdrant-server").exists()
    assert not (tmp_path / ".env.qdrant-read").exists()


def test_runtime_files_reject_reused_credentials_before_writing(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must differ"):
        create_qdrant_runtime_files(
            project_root=tmp_path,
            token_factory=lambda _bytes: ADMIN_KEY,
        )

    assert list(tmp_path.iterdir()) == []
