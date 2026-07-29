"""Checkpoint-safe final report approval contracts and fake revision."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from agent_research.models import (
    HumanActionKind,
    Identifier,
    Sha256,
    StrictModel,
)
from agent_research.report_drafting import (
    DraftProposal,
    hash_report_draft,
    MAX_REPORT_REVISIONS,
    ReportDraft,
)
from agent_research.report_review import ReviewResult


MAX_REPORT_CONFIRMATION_REVISIONS = 32
MAX_HUMAN_REPORT_REVISIONS = 2


class ReportPause(StrictModel):
    """Serializable report and review shown at the final human gate."""

    schema_version: Literal["report-pause-v1"] = "report-pause-v1"
    run_id: Identifier
    thread_id: Identifier
    confirmation_revision: Annotated[
        int,
        Field(ge=1, le=MAX_REPORT_CONFIRMATION_REVISIONS),
    ]
    report_revision: Annotated[
        int,
        Field(ge=1, le=MAX_REPORT_REVISIONS),
    ]
    report_hash: Sha256
    report: ReportDraft
    review_result: ReviewResult

    @model_validator(mode="after")
    def validate_bound_report(self) -> Self:
        if self.report.revision != self.report_revision:
            raise ValueError("report pause revision mismatch")
        if hash_report_draft(self.report) != self.report_hash:
            raise ValueError("report pause content hash mismatch")
        if self.review_result.report_revision != self.report_revision:
            raise ValueError("report pause review revision mismatch")
        if self.review_result.report_hash != self.report_hash:
            raise ValueError("report pause review hash mismatch")
        return self


class ReportDecision(StrictModel):
    """Human response bound to exactly one displayed report revision."""

    schema_version: Literal["report-decision-v1"] = "report-decision-v1"
    run_id: Identifier
    thread_id: Identifier
    expected_confirmation_revision: Annotated[
        int,
        Field(ge=1, le=MAX_REPORT_CONFIRMATION_REVISIONS),
    ]
    expected_report_revision: Annotated[
        int,
        Field(ge=1, le=MAX_REPORT_REVISIONS),
    ]
    expected_report_hash: Sha256
    action: HumanActionKind

    @model_validator(mode="after")
    def validate_report_action(self) -> Self:
        allowed = {
            HumanActionKind.APPROVE,
            HumanActionKind.REQUEST_CHANGES,
            HumanActionKind.REJECT,
            HumanActionKind.CANCEL,
        }
        if self.action not in allowed:
            raise ValueError("unsupported report action")
        return self


class DeterministicHumanReportReviser:
    """Select scripted human-requested replacement by persisted count."""

    def __init__(self, proposals: tuple[DraftProposal, ...]) -> None:
        if not 1 <= len(proposals) <= MAX_HUMAN_REPORT_REVISIONS:
            raise ValueError(
                "HUMAN_REVISION_SCRIPT_REQUIRES_ONE_OR_TWO_PROPOSALS"
            )
        self._proposals = proposals
        self.revision_count = 0

    def revise(self, *, next_human_revision: int) -> DraftProposal:
        if not 1 <= next_human_revision <= len(self._proposals):
            raise ValueError("HUMAN_REVISION_SCRIPT_HAS_NO_MATCHING_ROUND")
        self.revision_count += 1
        return self._proposals[next_human_revision - 1]
