from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cited_rag.evidence import (
    EXPERIMENTAL_SCORE_ONLY_POLICY,
    calibrate_evidence_threshold,
    load_evidence_calibration_set,
    load_evidence_evaluation_set,
)
from cited_rag.models import EvidenceScoreObservation, IndexManifest
from cited_rag.retrieval import DENSE_IDENTIFIER_RETRIEVAL_CONFIG

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXED_TIME = datetime(2026, 7, 29, 2, 0, tzinfo=timezone.utc)


def load_manifest() -> IndexManifest:
    report = json.loads(
        (PROJECT_ROOT / "data" / "index-build-report.json").read_text(
            encoding="utf-8"
        )
    )
    return IndexManifest.model_validate(report["index_manifest"])


def observation(case, score: float) -> EvidenceScoreObservation:
    return EvidenceScoreObservation(
        case_id=case.case_id,
        expected_decision=case.expected_decision,
        case_kind=case.case_kind,
        max_score=score,
        max_score_rank=1,
        max_score_chunk_id="00000000-0000-0000-0000-000000000001",
        max_score_source_id=(
            case.expected_source_ids[0]
            if case.expected_source_ids
            else "synthetic-source"
        ),
        max_score_retrieval_reason="dense",
        result_count=5,
    )


def test_threshold_selection_separates_balanced_fixture() -> None:
    calibration_set = load_evidence_calibration_set(
        PROJECT_ROOT
        / "data"
        / "evaluation"
        / "evidence-calibration-v1.json"
    )
    observations = tuple(
        observation(
            case,
            0.8 if case.expected_decision == "answer" else 0.4,
        )
        for case in calibration_set.cases
    )

    report = calibrate_evidence_threshold(
        calibration_set=calibration_set,
        observations=observations,
        manifest=load_manifest(),
        retrieval_config=DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
        generated_at=FIXED_TIME,
    )

    assert 0.4 < report.selected_threshold < 0.8
    assert report.answerable_recall == 1
    assert report.refusal_accuracy == 1
    assert report.target_met


def test_held_out_evaluation_is_separate_and_policy_bound() -> None:
    evaluation_set = load_evidence_evaluation_set(
        PROJECT_ROOT
        / "data"
        / "evaluation"
        / "evidence-evaluation-v1.json"
    )

    assert len(evaluation_set.cases) == 20
    assert evaluation_set.policy_id == EXPERIMENTAL_SCORE_ONLY_POLICY.policy_id
    assert (
        evaluation_set.index_fingerprint
        == load_manifest().index_fingerprint
    )
    assert sum(
        case.expected_decision == "answer"
        for case in evaluation_set.cases
    ) == 10
