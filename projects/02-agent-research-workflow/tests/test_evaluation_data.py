"""Tests for fixed workflow evaluation and gold contracts."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import pytest

from agent_research.data_loader import DataContractError, load_evaluation_bundle
from agent_research.models import CaseCategory


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _copy_bundle_files(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    shutil.copytree(
        PROJECT_ROOT / "data" / "synthetic-sources",
        project / "data" / "synthetic-sources",
    )
    shutil.copytree(PROJECT_ROOT / "evals", project / "evals")
    return project


def test_fixed_bundle_loads_and_has_exact_case_mix() -> None:
    bundle = load_evaluation_bundle(PROJECT_ROOT)

    assert len(bundle.evaluation.cases) == 12
    assert Counter(case.category for case in bundle.evaluation.cases) == Counter(
        {
            CaseCategory.SUCCESS: 4,
            CaseCategory.REQUIREMENTS_INCOMPLETE: 2,
            CaseCategory.EVIDENCE_INSUFFICIENT: 2,
            CaseCategory.TOOL_FAILURE: 2,
            CaseCategory.HUMAN_REVISION: 1,
            CaseCategory.RECOVERY_IDEMPOTENCY: 1,
        }
    )


def test_gold_rules_match_case_expected_recommendations() -> None:
    bundle = load_evaluation_bundle(PROJECT_ROOT)
    expected = {
        case.case_id: case.expected.allowed_recommendations
        for case in bundle.evaluation.cases
    }
    gold = {
        rule.case_id: rule.allowed_candidates
        for rule in bundle.gold.recommendation_rules
    }

    assert gold == expected


def test_all_referenced_evidence_is_in_verified_snapshot() -> None:
    bundle = load_evaluation_bundle(PROJECT_ROOT)
    known = {
        evidence_id
        for source in bundle.sources
        for evidence_id in source.evidence_ids
    }
    referenced = {
        evidence_id
        for case in bundle.evaluation.cases
        for evidence_id in (
            *case.expected.required_evidence_ids,
            *case.expected.forbidden_evidence_ids,
            *(
                item
                for outcome in case.tool_outcomes
                for item in outcome.evidence_ids
            ),
        )
    }
    referenced.update(
        evidence_id
        for claim in bundle.gold.claims
        for evidence_id in claim.evidence_ids
    )

    assert referenced <= known


def test_snapshot_mismatch_is_rejected(tmp_path: Path) -> None:
    project = _copy_bundle_files(tmp_path)
    evaluation_path = project / "evals" / "workflow-v1.json"
    payload = json.loads(evaluation_path.read_text(encoding="utf-8"))
    payload["source_snapshot_id"] = "f" * 64
    evaluation_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(DataContractError, match="EVALUATION_SNAPSHOT_ERROR"):
        load_evaluation_bundle(project)


def test_unknown_evidence_id_is_rejected(tmp_path: Path) -> None:
    project = _copy_bundle_files(tmp_path)
    evaluation_path = project / "evals" / "workflow-v1.json"
    payload = json.loads(evaluation_path.read_text(encoding="utf-8"))
    payload["cases"][0]["expected"]["required_evidence_ids"].append(
        "unknown-source-v1#unknown-section"
    )
    evaluation_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(DataContractError, match="EVALUATION_EVIDENCE_ERROR"):
        load_evaluation_bundle(project)


def test_unknown_case_field_is_rejected(tmp_path: Path) -> None:
    project = _copy_bundle_files(tmp_path)
    evaluation_path = project / "evals" / "workflow-v1.json"
    payload = json.loads(evaluation_path.read_text(encoding="utf-8"))
    payload["cases"][0]["unsafe_command"] = "do-not-run"
    evaluation_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(DataContractError, match="EVALUATION_SCHEMA_ERROR"):
        load_evaluation_bundle(project)
