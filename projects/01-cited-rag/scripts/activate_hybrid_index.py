"""Activate a passed Hybrid candidate or roll back to its dense source build."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.indexing import (  # noqa: E402
    activate_index,
    load_active_index,
    make_active_pointer,
    validate_index_manifest,
)
from cited_rag.models import IndexManifest  # noqa: E402

INDEX_ROOT = PROJECT_ROOT / "data" / "server-indexes"
BUILD_REPORT = PROJECT_ROOT / "data" / "hybrid-index-build-report.json"
GATE_REPORT = PROJECT_ROOT / "data" / "hybrid-release-gate.json"


def require_passed_release_gate(
    *,
    gate: dict[str, object],
    candidate_build_id: UUID,
) -> None:
    """Fail before pointer writes unless this exact candidate passed."""

    if (
        gate.get("passed") is not True
        or gate.get("candidate_build_id") != str(candidate_build_id)
    ):
        raise RuntimeError("Hybrid release gate did not pass for candidate")


def main(*, rollback: bool = False) -> int:
    build = json.loads(BUILD_REPORT.read_text(encoding="utf-8"))
    candidate = IndexManifest.model_validate(build["candidate_manifest"])
    source = IndexManifest.model_validate(build["source_manifest"])
    target = source if rollback else candidate
    validate_index_manifest(target)
    stored = IndexManifest.model_validate_json(
        (INDEX_ROOT / "manifests" / f"{target.build_id}.json").read_text(encoding="utf-8")
    )
    if stored != target:
        raise RuntimeError("activation target does not match immutable manifest")
    _, active = load_active_index(index_root=INDEX_ROOT)
    if rollback:
        if active.build_id not in {candidate.build_id, source.build_id}:
            raise RuntimeError("rollback active build is outside approved pair")
    else:
        gate = json.loads(GATE_REPORT.read_text(encoding="utf-8"))
        require_passed_release_gate(
            gate=gate,
            candidate_build_id=candidate.build_id,
        )
        if active.build_id != source.build_id:
            raise RuntimeError("activation source build changed")
    activate_index(
        index_root=INDEX_ROOT,
        pointer=make_active_pointer(target),
        manifest=target,
    )
    _, verified = load_active_index(index_root=INDEX_ROOT)
    if verified != target:
        raise RuntimeError("active pointer verification failed")
    print(json.dumps({
        "status": "rolled-back" if rollback else "activated",
        "index_id": str(target.index_id),
        "build_id": str(target.build_id),
        "collection_name": target.collection_name,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", action="store_true")
    arguments = parser.parse_args()
    raise SystemExit(main(rollback=arguments.rollback))
