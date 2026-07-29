"""Tests for synthetic source integrity and trust boundaries."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_research.data_loader import DataContractError, load_source_snapshot
from agent_research.models import (
    SourceManifest,
    SourceManifestEntry,
    compute_source_snapshot_id,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "data" / "synthetic-sources"


def test_source_snapshot_has_expected_members_and_sections() -> None:
    sources = load_source_snapshot(SOURCE_ROOT)

    assert len(sources) == 10
    assert sum(len(source.evidence_ids) for source in sources) == 40
    assert Counter(
        source.entry.candidate_id for source in sources
    ) == Counter(
        {
            "atlasflow": 3,
            "beaconflow": 3,
            "cedarflow": 3,
            None: 1,
        }
    )


def test_manifest_snapshot_fingerprint_is_reproducible() -> None:
    manifest = SourceManifest.model_validate_json(
        (SOURCE_ROOT / "manifest.json").read_text(encoding="utf-8")
    )

    assert manifest.snapshot_id == compute_source_snapshot_id(
        manifest.schema_version,
        manifest.sources,
    )


def test_manifest_rejects_path_traversal() -> None:
    valid_entry = SourceManifest.model_validate_json(
        (SOURCE_ROOT / "manifest.json").read_text(encoding="utf-8")
    ).sources[0]
    payload = valid_entry.model_dump(mode="json")
    payload["relative_path"] = "../outside.md"

    with pytest.raises(ValidationError, match="source root"):
        SourceManifestEntry.model_validate(payload)


def test_source_hash_tampering_is_detected(tmp_path: Path) -> None:
    copied_root = tmp_path / "synthetic-sources"
    shutil.copytree(SOURCE_ROOT, copied_root)
    target = copied_root / "atlasflow" / "overview.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nunauthorized change\n",
        encoding="utf-8",
    )

    with pytest.raises(DataContractError, match="DATA_SIZE_ERROR"):
        load_source_snapshot(copied_root)


def test_unlisted_markdown_file_is_rejected(tmp_path: Path) -> None:
    copied_root = tmp_path / "synthetic-sources"
    shutil.copytree(SOURCE_ROOT, copied_root)
    (copied_root / "unlisted.md").write_text(
        "> synthetic test fixture\n",
        encoding="utf-8",
    )

    with pytest.raises(DataContractError, match="DATA_MEMBERS_ERROR"):
        load_source_snapshot(copied_root)


def test_manifest_unknown_field_is_rejected() -> None:
    payload = json.loads(
        (SOURCE_ROOT / "manifest.json").read_text(encoding="utf-8")
    )
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs"):
        SourceManifest.model_validate(payload)


def test_prompt_injection_text_remains_untrusted_data() -> None:
    sources = load_source_snapshot(SOURCE_ROOT)
    cedar_security = next(
        source
        for source in sources
        if source.entry.source_id == "cedarflow-security-cost-v1"
    )

    assert "delete_all" in cedar_security.text
    assert r"C:\secret" in cedar_security.text
    assert (
        "cedarflow-security-cost-v1#permission-boundary"
        in cedar_security.evidence_ids
    )
    assert not (PROJECT_ROOT / "secret").exists()
