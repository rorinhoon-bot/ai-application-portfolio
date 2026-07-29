"""Offline loaders with path, hash, and cross-file validation."""

from __future__ import annotations

import hashlib
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from agent_research.models import (
    SourceManifest,
    SourceManifestEntry,
    WorkflowEvaluationSuite,
    WorkflowGoldSuite,
    compute_source_snapshot_id,
)


SECTION_PATTERN = re.compile(r"^## \[([a-z][a-z0-9-]*)\] ", re.MULTILINE)
REPARSE_POINT_FLAG = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class DataContractError(ValueError):
    """Raised when a fixed local data artifact fails validation."""


@dataclass(frozen=True)
class VerifiedSource:
    entry: SourceManifestEntry
    text: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationBundle:
    sources: tuple[VerifiedSource, ...]
    evaluation: WorkflowEvaluationSuite
    gold: WorkflowGoldSuite


def _has_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & REPARSE_POINT_FLAG)


def _resolve_safe_file(root: Path, relative_path: str) -> Path:
    if "\\" in relative_path:
        raise DataContractError("DATA_PATH_ERROR: POSIX separators required")

    lexical = PurePosixPath(relative_path)
    if lexical.is_absolute() or ".." in lexical.parts or "." in lexical.parts:
        raise DataContractError("DATA_PATH_ERROR: unsafe relative path")

    root_resolved = root.resolve(strict=True)
    candidate = root_resolved.joinpath(*lexical.parts)

    current = root_resolved
    for part in lexical.parts:
        current = current / part
        if current.exists() and (current.is_symlink() or _has_reparse_point(current)):
            raise DataContractError("DATA_PATH_ERROR: reparse point rejected")

    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root_resolved):
        raise DataContractError("DATA_PATH_ERROR: path escaped source root")
    if not resolved.is_file():
        raise DataContractError("DATA_PATH_ERROR: regular file required")
    return resolved


def _read_utf8(path: Path) -> tuple[bytes, str]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DataContractError("DATA_ENCODING_ERROR: UTF-8 required") from exc
    return raw, text


def _verify_source(root: Path, entry: SourceManifestEntry) -> VerifiedSource:
    path = _resolve_safe_file(root, entry.relative_path)
    raw, text = _read_utf8(path)

    if len(raw) != entry.size_bytes:
        raise DataContractError(
            f"DATA_SIZE_ERROR: {entry.source_id} size does not match manifest"
        )
    digest = hashlib.sha256(raw).hexdigest()
    if digest != entry.sha256:
        raise DataContractError(
            f"DATA_HASH_ERROR: {entry.source_id} hash does not match manifest"
        )
    if "synthetic test fixture" not in text:
        raise DataContractError(
            f"DATA_MARKER_ERROR: {entry.source_id} lacks synthetic marker"
        )
    if f"source_id: {entry.source_id}" not in text:
        raise DataContractError(
            f"DATA_ID_ERROR: {entry.source_id} lacks matching source marker"
        )

    section_ids = SECTION_PATTERN.findall(text)
    if not section_ids or len(section_ids) != len(set(section_ids)):
        raise DataContractError(
            f"DATA_SECTION_ERROR: {entry.source_id} sections missing or duplicated"
        )
    evidence_ids = tuple(
        f"{entry.source_id}#{section_id}" for section_id in section_ids
    )
    return VerifiedSource(entry=entry, text=text, evidence_ids=evidence_ids)


def load_source_snapshot(
    source_root: Path,
    manifest_name: str = "manifest.json",
) -> tuple[VerifiedSource, ...]:
    source_root = source_root.resolve(strict=True)
    manifest_path = _resolve_safe_file(source_root, manifest_name)
    _, manifest_text = _read_utf8(manifest_path)
    try:
        manifest = SourceManifest.model_validate_json(manifest_text)
    except ValueError as exc:
        raise DataContractError("DATA_MANIFEST_ERROR: invalid manifest") from exc

    expected_snapshot_id = compute_source_snapshot_id(
        manifest.schema_version,
        manifest.sources,
    )
    if manifest.snapshot_id != expected_snapshot_id:
        raise DataContractError("DATA_SNAPSHOT_ERROR: manifest fingerprint mismatch")

    verified = tuple(
        _verify_source(source_root, entry) for entry in manifest.sources
    )
    actual_markdown = {
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*.md")
        if path.is_file()
    }
    expected_markdown = {entry.relative_path for entry in manifest.sources}
    if actual_markdown != expected_markdown:
        raise DataContractError("DATA_MEMBERS_ERROR: source member set mismatch")
    return verified


def load_evaluation_bundle(project_root: Path) -> EvaluationBundle:
    sources = load_source_snapshot(project_root / "data" / "synthetic-sources")
    evaluation_path = _resolve_safe_file(
        project_root,
        "evals/workflow-v1.json",
    )
    gold_path = _resolve_safe_file(
        project_root,
        "evals/gold/workflow-v1-gold.json",
    )
    _, evaluation_text = _read_utf8(evaluation_path)
    _, gold_text = _read_utf8(gold_path)

    try:
        evaluation = WorkflowEvaluationSuite.model_validate_json(evaluation_text)
        gold = WorkflowGoldSuite.model_validate_json(gold_text)
    except ValueError as exc:
        raise DataContractError("EVALUATION_SCHEMA_ERROR: invalid evaluation data") from exc

    manifest_path = _resolve_safe_file(
        project_root,
        "data/synthetic-sources/manifest.json",
    )
    _, manifest_text = _read_utf8(manifest_path)
    manifest = SourceManifest.model_validate_json(manifest_text)
    if (
        evaluation.source_snapshot_id != manifest.snapshot_id
        or gold.source_snapshot_id != manifest.snapshot_id
    ):
        raise DataContractError(
            "EVALUATION_SNAPSHOT_ERROR: source fingerprints differ"
        )

    evidence_ids = {
        evidence_id
        for source in sources
        for evidence_id in source.evidence_ids
    }
    candidate_ids = {
        source.entry.candidate_id
        for source in sources
        if source.entry.candidate_id is not None
    }
    case_ids = {case.case_id for case in evaluation.cases}

    for case in evaluation.cases:
        referenced = (
            set(case.expected.required_evidence_ids)
            | set(case.expected.forbidden_evidence_ids)
            | {
                evidence_id
                for outcome in case.tool_outcomes
                for evidence_id in outcome.evidence_ids
            }
        )
        if not referenced <= evidence_ids:
            raise DataContractError(
                f"EVALUATION_EVIDENCE_ERROR: unknown ID in {case.case_id}"
            )
        if not set(case.expected.allowed_recommendations) <= candidate_ids:
            raise DataContractError(
                f"EVALUATION_CANDIDATE_ERROR: unknown candidate in {case.case_id}"
            )

    for claim in gold.claims:
        if not set(claim.evidence_ids) <= evidence_ids:
            raise DataContractError(
                f"GOLD_EVIDENCE_ERROR: unknown ID in {claim.claim_id}"
            )
        if claim.candidate_id not in candidate_ids:
            raise DataContractError(
                f"GOLD_CANDIDATE_ERROR: unknown candidate in {claim.claim_id}"
            )

    rule_ids = {rule.case_id for rule in gold.recommendation_rules}
    if rule_ids != case_ids:
        raise DataContractError("GOLD_CASE_ERROR: recommendation cases differ")
    for rule in gold.recommendation_rules:
        if not set(rule.allowed_candidates) <= candidate_ids:
            raise DataContractError(
                f"GOLD_CANDIDATE_ERROR: unknown rule candidate in {rule.case_id}"
            )

    return EvaluationBundle(
        sources=sources,
        evaluation=evaluation,
        gold=gold,
    )
