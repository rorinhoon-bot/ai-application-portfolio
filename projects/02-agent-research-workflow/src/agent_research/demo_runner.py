"""Repeatable offline portfolio demo built from three frozen workflow cases."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from agent_research.data_loader import load_evaluation_bundle
from agent_research.evaluation_runner import (
    EvaluationRunnerError,
    WorkflowCaseResult,
    _run_full_case,
    _run_incomplete_case,
)
from agent_research.models import Identifier, RunStatus, Sha256, StrictModel
from agent_research.observability import (
    DeterministicClock,
    RunObserver,
    RunSummary,
)


DEMO_SCHEMA_VERSION = "offline-demo-v1"
DEMO_CASE_IDS = (
    "missing-candidates",
    "privacy-durable-selection",
    "missing-offline-proof",
)
RUN_SUMMARY_FILE = "evals/results/privacy-durable-run-summary.json"
REPARSE_POINT_FLAG = 0x400


class DemoRunnerError(RuntimeError):
    """Raised when the fixed offline demo cannot be reproduced safely."""


def _has_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & REPARSE_POINT_FLAG)


class DemoScenario(StrictModel):
    """Small presentation view of one real frozen workflow result."""

    schema_version: Literal["demo-scenario-v1"] = "demo-scenario-v1"
    purpose: Literal[
        "requirements-pause",
        "successful-export",
        "evidence-stop",
    ]
    case_id: Identifier
    actual_status: RunStatus
    actual_path: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    tool_attempts: Annotated[int, Field(ge=0, le=3)]
    retrieval_rounds: Annotated[int, Field(ge=0, le=2)]
    human_revision_count: Annotated[int, Field(ge=0, le=2)]
    report_claim_count: Annotated[int, Field(ge=0, le=32)]
    unsupported_claim_count: Annotated[int, Field(ge=0, le=32)]
    artifact_count: Annotated[int, Field(ge=0, le=1)]
    recommendation: Identifier | None = None
    passed: Literal[True] = True


class OfflineDemoBundle(StrictModel):
    """Hashed manifest for committed demo outputs."""

    schema_version: Literal["offline-demo-v1"] = DEMO_SCHEMA_VERSION
    bundle_hash: Sha256
    source_snapshot_id: Sha256
    scenario_count: Literal[3] = 3
    scenarios: Annotated[
        tuple[DemoScenario, ...],
        Field(min_length=3, max_length=3),
    ]
    report_artifact_id: Sha256
    report_file: Annotated[
        str,
        Field(pattern=r"^[0-9a-f]{64}\.md$", max_length=67),
    ]
    report_content_sha256: Sha256
    report_revision: Annotated[int, Field(ge=1, le=32)]
    report_hash: Sha256
    run_summary_file: Literal[
        "evals/results/privacy-durable-run-summary.json"
    ] = RUN_SUMMARY_FILE
    run_summary_hash: Sha256
    node_event_count: Annotated[int, Field(ge=1, le=512)]
    interrupted_node_count: Annotated[int, Field(ge=0, le=512)]
    model_api_used: Literal[False] = False
    network_used: Literal[False] = False
    known_cost_microunits: Literal[0] = 0

    @model_validator(mode="after")
    def validate_bundle_shape(self) -> Self:
        if tuple(item.case_id for item in self.scenarios) != DEMO_CASE_IDS:
            raise ValueError("demo scenarios must use the fixed case order")
        expected_purposes = (
            "requirements-pause",
            "successful-export",
            "evidence-stop",
        )
        if tuple(item.purpose for item in self.scenarios) != expected_purposes:
            raise ValueError("demo scenario purposes do not match fixed cases")
        expected_statuses = (
            RunStatus.NEEDS_HUMAN,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
        )
        if tuple(item.actual_status for item in self.scenarios) != (
            expected_statuses
        ):
            raise ValueError("demo statuses do not show pause/success/failure")
        if tuple(item.artifact_count for item in self.scenarios) != (0, 1, 0):
            raise ValueError("only successful demo scenario may export")
        if self.report_file != f"{self.report_artifact_id}.md":
            raise ValueError("report_file must match report_artifact_id")
        if self.bundle_hash != compute_demo_bundle_hash(self):
            raise ValueError("bundle_hash does not match demo content")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"

    def to_text(self) -> str:
        pause, success, failure = self.scenarios
        return "\n".join(
            (
                "P2 离线演示 v1",
                (
                    f"[1] NEEDS_HUMAN  {pause.case_id}: "
                    "候选缺失；不猜测"
                ),
                (
                    f"[2] COMPLETED    {success.case_id}: "
                    f"{success.report_claim_count} 条带引用声明；"
                    f"推荐 {success.recommendation}"
                ),
                (
                    f"[3] FAILED       {failure.case_id}: "
                    f"{failure.retrieval_rounds} 轮检索后停止；不生成报告"
                ),
                (
                    f"[4] OBSERVED     {self.node_event_count} 个节点事件；"
                    f"{self.interrupted_node_count} 次正常人工中断"
                ),
                f"报告：demo/generated/{self.report_file}",
                f"摘要：{self.run_summary_file}",
                "network=false model_api=false known_cost_microunits=0",
            )
        ) + "\n"


@dataclass(frozen=True)
class OfflineDemoRun:
    """Runtime demo result; report bytes are not duplicated in the manifest."""

    bundle: OfflineDemoBundle
    report_bytes: bytes
    run_summary: RunSummary


def compute_demo_bundle_hash(bundle: OfflineDemoBundle) -> str:
    payload = bundle.model_dump(mode="json")
    payload.pop("bundle_hash")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _scenario(
    result: WorkflowCaseResult,
    purpose: Literal[
        "requirements-pause",
        "successful-export",
        "evidence-stop",
    ],
) -> DemoScenario:
    if not result.passed:
        raise DemoRunnerError(f"DEMO_CASE_FAILED: {result.case_id}")
    return DemoScenario(
        purpose=purpose,
        case_id=result.case_id,
        actual_status=result.actual_status,
        actual_path=result.actual_path,
        tool_attempts=result.actual_tool_attempts,
        retrieval_rounds=result.retrieval_rounds,
        human_revision_count=result.human_revision_count,
        report_claim_count=result.report_claim_count,
        unsupported_claim_count=result.unsupported_claim_count,
        artifact_count=result.artifact_count,
        recommendation=result.actual_recommendation,
    )


def _report_bytes(
    *,
    case_root: Path,
    summary: RunSummary,
) -> bytes:
    if summary.artifact_id is None:
        raise DemoRunnerError("DEMO_SUCCESS_HAS_NO_ARTIFACT_ID")
    artifact_root = case_root / "artifacts"
    files = tuple(artifact_root.glob("*.md"))
    if len(files) != 1:
        raise DemoRunnerError("DEMO_SUCCESS_REQUIRES_ONE_REPORT")
    report_path = files[0]
    if report_path.name != f"{summary.artifact_id}.md":
        raise DemoRunnerError("DEMO_REPORT_NAME_MISMATCH")
    if (
        report_path.is_symlink()
        or _has_reparse_point(report_path)
        or not report_path.is_file()
    ):
        raise DemoRunnerError("DEMO_REPORT_MUST_BE_REGULAR_FILE")
    return report_path.read_bytes()


def run_offline_demo(project_root: Path) -> OfflineDemoRun:
    """Execute fixed pause/success/failure stories without network or models."""

    if os.environ.get("LANGGRAPH_STRICT_MSGPACK") != "true":
        raise DemoRunnerError("LANGGRAPH_STRICT_MSGPACK must equal 'true'")
    root = project_root.resolve(strict=True)
    evaluation_bundle = load_evaluation_bundle(root)
    cases = {
        item.case_id: item for item in evaluation_bundle.evaluation.cases
    }
    if not set(DEMO_CASE_IDS) <= set(cases):
        raise DemoRunnerError("DEMO_CASE_SET_INCOMPLETE")

    scenarios: list[DemoScenario] = []
    success_summary: RunSummary | None = None
    success_report = b""
    purposes = (
        "requirements-pause",
        "successful-export",
        "evidence-stop",
    )
    with TemporaryDirectory(prefix="p2-offline-demo-") as temp_dir:
        temp_root = Path(temp_dir)
        for case_id, purpose in zip(DEMO_CASE_IDS, purposes, strict=True):
            case = cases[case_id]
            case_root = temp_root / case_id
            case_root.mkdir()
            observer = None
            if case_id == "privacy-durable-selection":
                observer = RunObserver(
                    run_id=f"run-{case_id}",
                    thread_id=f"thread-{case_id}",
                    clock=DeterministicClock(),
                )
            try:
                if case_id == "missing-candidates":
                    result, summary = _run_incomplete_case(
                        bundle=evaluation_bundle,
                        case=case,
                        case_root=case_root,
                    )
                else:
                    result, summary = _run_full_case(
                        bundle=evaluation_bundle,
                        case=case,
                        case_root=case_root,
                        observer=observer,
                    )
            except EvaluationRunnerError as exc:
                raise DemoRunnerError("DEMO_WORKFLOW_EXECUTION_FAILED") from exc
            scenarios.append(_scenario(result, purpose))
            if case_id == "privacy-durable-selection":
                if summary is None:
                    raise DemoRunnerError("DEMO_RUN_SUMMARY_NOT_CREATED")
                success_summary = summary
                success_report = _report_bytes(
                    case_root=case_root,
                    summary=summary,
                )

    if success_summary is None or success_summary.report_hash is None:
        raise DemoRunnerError("DEMO_SUCCESS_BINDING_MISSING")
    if success_summary.artifact_id is None:
        raise DemoRunnerError("DEMO_SUCCESS_ARTIFACT_MISSING")
    payload = {
        "bundle_hash": "0" * 64,
        "source_snapshot_id": (
            evaluation_bundle.evaluation.source_snapshot_id
        ),
        "scenarios": tuple(scenarios),
        "report_artifact_id": success_summary.artifact_id,
        "report_file": f"{success_summary.artifact_id}.md",
        "report_content_sha256": hashlib.sha256(success_report).hexdigest(),
        "report_revision": success_summary.report_revision,
        "report_hash": success_summary.report_hash,
        "run_summary_hash": success_summary.summary_hash,
        "node_event_count": success_summary.node_event_count,
        "interrupted_node_count": success_summary.interrupted_node_count,
    }
    draft = OfflineDemoBundle.model_construct(**payload)
    payload["bundle_hash"] = compute_demo_bundle_hash(draft)
    return OfflineDemoRun(
        bundle=OfflineDemoBundle.model_validate(payload),
        report_bytes=success_report,
        run_summary=success_summary,
    )
