"""Offline evidence-score calibration without answer generation."""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from math import nextafter
from pathlib import Path

from pydantic import ValidationError

from cited_rag.errors import (
    CitedRagError,
    EvaluationError,
    IndexVersionMismatchError,
)
from cited_rag.evaluation import Retriever
from cited_rag.models import (
    EvidenceCalibrationSet,
    EvidenceAssessment,
    EvidenceEvaluationSet,
    EvidencePolicy,
    EvidencePolicyEvaluationReport,
    EvidenceScoreObservation,
    EvidenceThresholdCalibrationReport,
    EvidenceThresholdCaseResult,
    IndexManifest,
    RetrievalConfig,
    RetrievalResult,
)
from cited_rag.retrieval import make_retrieval_query

EXPERIMENTAL_SCORE_ONLY_POLICY = EvidencePolicy(
    schema_version="1",
    policy_id="evidence-score-v1",
    index_id="614f6c23-7c35-5832-8086-c29651d60866",
    retrieval_config={
        "schema_version": "1",
        "mode": "dense-plus-identifiers",
        "top_k": 5,
        "remove_filtered_version_terms": True,
        "identifier_result_limit": 2,
    },
    calibration_set_id="evidence-calibration-v1",
    calibration_set_sha256=(
        "41dd7713f86ed1e3a1b51ab20e9e405e1da07cb0778ada83e404f29c25ff5099"
    ),
    score_definition="maximum-cosine-among-returned-results",
    threshold=0.6187245534246643,
)


def load_evidence_calibration_set(path: Path) -> EvidenceCalibrationSet:
    """Load one strict UTF-8 score-calibration fixture."""

    try:
        return EvidenceCalibrationSet.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise EvaluationError("evidence calibration set is invalid") from error


def load_evidence_evaluation_set(path: Path) -> EvidenceEvaluationSet:
    """Load the held-out policy evaluation set."""

    try:
        return EvidenceEvaluationSet.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise EvaluationError("evidence evaluation set is invalid") from error


def make_evidence_calibration_set_sha256(
    calibration_set: EvidenceCalibrationSet,
) -> str:
    canonical = json.dumps(
        calibration_set.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def collect_evidence_scores(
    *,
    calibration_set: EvidenceCalibrationSet,
    retriever: Retriever,
    manifest: IndexManifest,
    retrieval_config: RetrievalConfig,
) -> tuple[EvidenceScoreObservation, ...]:
    """Retrieve every calibration question and retain its maximum score."""

    if calibration_set.index_fingerprint != manifest.index_fingerprint:
        raise IndexVersionMismatchError(
            "calibration set does not match active index fingerprint"
        )
    if calibration_set.retrieval_config != retrieval_config:
        raise IndexVersionMismatchError(
            "calibration set does not match retrieval configuration"
        )

    observations: list[EvidenceScoreObservation] = []
    for case in calibration_set.cases:
        query = make_retrieval_query(
            question=case.question,
            python_version=case.python_version,
            top_k=retrieval_config.top_k,
        )
        try:
            result = retriever.retrieve(query)
        except CitedRagError as error:
            observations.append(
                EvidenceScoreObservation(
                    case_id=case.case_id,
                    expected_decision=case.expected_decision,
                    case_kind=case.case_kind,
                    max_score=None,
                    max_score_rank=None,
                    max_score_chunk_id=None,
                    max_score_source_id=None,
                    max_score_retrieval_reason=None,
                    result_count=0,
                    error_code=error.code,
                )
            )
            continue

        if (
            result.index_id != manifest.index_id
            or result.build_id != manifest.build_id
            or result.retrieval_config != retrieval_config
        ):
            raise IndexVersionMismatchError(
                "score result does not match calibration runtime"
            )
        maximum = max(
            result.results,
            key=lambda item: (item.score, -item.rank),
            default=None,
        )
        observations.append(
            EvidenceScoreObservation(
                case_id=case.case_id,
                expected_decision=case.expected_decision,
                case_kind=case.case_kind,
                max_score=maximum.score if maximum else None,
                max_score_rank=maximum.rank if maximum else None,
                max_score_chunk_id=(
                    maximum.payload.chunk_id if maximum else None
                ),
                max_score_source_id=(
                    maximum.payload.source_id if maximum else None
                ),
                max_score_retrieval_reason=(
                    maximum.retrieval_reason if maximum else None
                ),
                result_count=len(result.results),
            )
        )
    return tuple(observations)


def calibrate_evidence_threshold(
    *,
    calibration_set: EvidenceCalibrationSet,
    observations: tuple[EvidenceScoreObservation, ...],
    manifest: IndexManifest,
    retrieval_config: RetrievalConfig,
    generated_at: datetime,
) -> EvidenceThresholdCalibrationReport:
    """Choose the strongest balanced threshold without hiding failure."""

    expected_ids = [case.case_id for case in calibration_set.cases]
    observed_ids = [item.case_id for item in observations]
    if observed_ids != expected_ids:
        raise EvaluationError(
            "score observations do not match calibration case order"
        )
    scores = sorted(
        {
            observation.max_score
            for observation in observations
            if observation.max_score is not None
        }
    )
    if not scores:
        raise EvaluationError("calibration produced no retrieval scores")
    candidates = [nextafter(scores[0], float("-inf"))]
    candidates.extend(
        (left + right) / 2
        for left, right in zip(scores, scores[1:])
    )
    candidates.append(nextafter(scores[-1], float("inf")))

    evaluated = [
        _evaluate_threshold(
            threshold=threshold,
            observations=observations,
        )
        for threshold in candidates
    ]
    selected = max(
        evaluated,
        key=lambda item: (
            item["answerable_recall"] >= 0.8
            and item["refusal_accuracy"] >= 0.8,
            item["balanced_accuracy"],
            min(
                item["answerable_recall"],
                item["refusal_accuracy"],
            ),
            item["answerable_recall"],
            -item["threshold"],
        ),
    )
    return EvidenceThresholdCalibrationReport(
        schema_version="1",
        calibration_set_id=calibration_set.calibration_set_id,
        calibration_set_sha256=make_evidence_calibration_set_sha256(
            calibration_set
        ),
        generated_at=generated_at,
        index_id=manifest.index_id,
        build_id=manifest.build_id,
        index_fingerprint=manifest.index_fingerprint,
        retrieval_config=retrieval_config,
        score_definition="maximum-cosine-among-returned-results",
        decision_rule="answer-if-score-gte-threshold",
        selected_threshold=selected["threshold"],
        answerable_count=selected["answerable_count"],
        refusal_count=selected["refusal_count"],
        answerable_recall=selected["answerable_recall"],
        refusal_accuracy=selected["refusal_accuracy"],
        balanced_accuracy=selected["balanced_accuracy"],
        minimum_class_target=0.8,
        target_met=(
            selected["answerable_recall"] >= 0.8
            and selected["refusal_accuracy"] >= 0.8
        ),
        cases=selected["cases"],
    )


def _evaluate_threshold(
    *,
    threshold: float,
    observations: tuple[EvidenceScoreObservation, ...],
) -> dict:
    cases: list[EvidenceThresholdCaseResult] = []
    for observation in observations:
        predicted = (
            "answer"
            if observation.max_score is not None
            and observation.max_score >= threshold
            else "refuse"
        )
        cases.append(
            EvidenceThresholdCaseResult(
                observation=observation,
                predicted_decision=predicted,
                correct=predicted == observation.expected_decision,
            )
        )
    answer_cases = [
        case
        for case in cases
        if case.observation.expected_decision == "answer"
    ]
    refusal_cases = [
        case
        for case in cases
        if case.observation.expected_decision == "refuse"
    ]
    answerable_recall = (
        sum(case.correct for case in answer_cases) / len(answer_cases)
    )
    refusal_accuracy = (
        sum(case.correct for case in refusal_cases) / len(refusal_cases)
    )
    return {
        "threshold": threshold,
        "answerable_count": len(answer_cases),
        "refusal_count": len(refusal_cases),
        "answerable_recall": answerable_recall,
        "refusal_accuracy": refusal_accuracy,
        "balanced_accuracy": (
            answerable_recall + refusal_accuracy
        )
        / 2,
        "cases": tuple(cases),
    }


def assess_evidence(
    *,
    retrieval: RetrievalResult,
    policy: EvidencePolicy,
) -> EvidenceAssessment:
    """Apply the pinned score rule to already validated retrieval output."""

    maximum = max(
        retrieval.results,
        key=lambda item: (item.score, -item.rank),
        default=None,
    )
    if maximum is None:
        decision = "insufficient"
        reason = "no-results"
    elif maximum.score >= policy.threshold:
        decision = "sufficient"
        reason = "score-at-or-above-threshold"
    else:
        decision = "insufficient"
        reason = "score-below-threshold"
    return EvidenceAssessment(
        policy=policy,
        retrieval=retrieval,
        decision=decision,
        reason=reason,
        max_score=maximum.score if maximum else None,
        max_score_rank=maximum.rank if maximum else None,
        max_score_chunk_id=(
            maximum.payload.chunk_id if maximum else None
        ),
    )


def evaluate_evidence_policy(
    *,
    evaluation_set: EvidenceEvaluationSet,
    retriever: Retriever,
    manifest: IndexManifest,
    policy: EvidencePolicy,
    generated_at: datetime,
) -> EvidencePolicyEvaluationReport:
    """Evaluate a pinned policy once without selecting a new threshold."""

    if evaluation_set.index_fingerprint != manifest.index_fingerprint:
        raise IndexVersionMismatchError(
            "evidence evaluation set does not match active index"
        )
    if evaluation_set.policy_id != policy.policy_id:
        raise IndexVersionMismatchError(
            "evidence evaluation set does not match policy"
        )
    results: list[EvidenceThresholdCaseResult] = []
    for case in evaluation_set.cases:
        query = make_retrieval_query(
            question=case.question,
            python_version=case.python_version,
            top_k=policy.retrieval_config.top_k,
        )
        retrieval = retriever.retrieve(query)
        assessment = assess_evidence(
            retrieval=retrieval,
            policy=policy,
        )
        maximum = max(
            retrieval.results,
            key=lambda item: (item.score, -item.rank),
            default=None,
        )
        observation = EvidenceScoreObservation(
            case_id=case.case_id,
            expected_decision=case.expected_decision,
            case_kind=case.case_kind,
            max_score=maximum.score if maximum else None,
            max_score_rank=maximum.rank if maximum else None,
            max_score_chunk_id=(
                maximum.payload.chunk_id if maximum else None
            ),
            max_score_source_id=(
                maximum.payload.source_id if maximum else None
            ),
            max_score_retrieval_reason=(
                maximum.retrieval_reason if maximum else None
            ),
            result_count=len(retrieval.results),
        )
        predicted = (
            "answer"
            if assessment.decision == "sufficient"
            else "refuse"
        )
        results.append(
            EvidenceThresholdCaseResult(
                observation=observation,
                predicted_decision=predicted,
                correct=predicted == case.expected_decision,
            )
        )

    answer_cases = [
        case
        for case in results
        if case.observation.expected_decision == "answer"
    ]
    refusal_cases = [
        case
        for case in results
        if case.observation.expected_decision == "refuse"
    ]
    answer_recall = sum(case.correct for case in answer_cases) / len(
        answer_cases
    )
    refusal_accuracy = sum(case.correct for case in refusal_cases) / len(
        refusal_cases
    )
    canonical = json.dumps(
        evaluation_set.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return EvidencePolicyEvaluationReport(
        schema_version="1",
        evaluation_set_id=evaluation_set.evaluation_set_id,
        evaluation_set_sha256=sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
        generated_at=generated_at,
        policy=policy,
        index_fingerprint=manifest.index_fingerprint,
        answerable_count=len(answer_cases),
        refusal_count=len(refusal_cases),
        answerable_recall=answer_recall,
        refusal_accuracy=refusal_accuracy,
        balanced_accuracy=(answer_recall + refusal_accuracy) / 2,
        minimum_class_target=0.8,
        target_met=answer_recall >= 0.8 and refusal_accuracy >= 0.8,
        cases=tuple(results),
    )
