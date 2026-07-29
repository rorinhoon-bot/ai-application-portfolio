"""Deterministic offline tool executor for workflow and retry tests."""

from __future__ import annotations

from agent_research.data_loader import VerifiedSource
from agent_research.models import (
    ResearchInput,
    ScriptedToolOutcome,
    ToolOutcomeKind,
)
from agent_research.tool_contracts import (
    CalculateComparisonArgs,
    ReadSourceArgs,
    SearchSourcesArgs,
    ToolCall,
    ToolResult,
    compute_tool_call_key,
)


class DeterministicFakeToolExecutor:
    """Validate scope, then select a scripted result by persisted attempt number."""

    def __init__(
        self,
        *,
        sources: tuple[VerifiedSource, ...],
        outcomes: tuple[ScriptedToolOutcome, ...],
    ) -> None:
        self._sources = {source.entry.source_id: source for source in sources}
        self._known_evidence_ids = {
            evidence_id
            for source in sources
            for evidence_id in source.evidence_ids
        }
        self._outcomes = outcomes
        self.execution_count = 0

    def _scope_error(
        self,
        call: ToolCall,
        confirmed: ResearchInput,
    ) -> str | None:
        arguments = call.arguments
        approved_candidates = set(confirmed.candidates)
        approved_dimensions = {
            item.dimension_id: item.weight_percent
            for item in confirmed.dimensions
        }

        if isinstance(arguments, SearchSourcesArgs):
            if not set(arguments.candidate_ids) <= approved_candidates:
                return "candidate-outside-approved-scope"
            return None

        if isinstance(arguments, ReadSourceArgs):
            source = self._sources.get(arguments.source_id)
            if source is None:
                return "unknown-source"
            evidence_id = f"{arguments.source_id}#{arguments.section_id}"
            if evidence_id not in self._known_evidence_ids:
                return "unknown-section"
            candidate_id = source.entry.candidate_id
            if (
                candidate_id is not None
                and candidate_id not in approved_candidates
            ):
                return "source-outside-approved-scope"
            return None

        if isinstance(arguments, CalculateComparisonArgs):
            actual_weights = {
                item.dimension_id: item.weight_percent
                for item in arguments.weights
            }
            if actual_weights != approved_dimensions:
                return "weights-differ-from-approved-requirements"
            if not {
                item.candidate_id for item in arguments.candidates
            } <= approved_candidates:
                return "candidate-outside-approved-scope"
            referenced = {
                evidence_id
                for candidate in arguments.candidates
                for dimension in candidate.dimensions
                for evidence_id in dimension.evidence_ids
            }
            if not referenced <= self._known_evidence_ids:
                return "unknown-evidence"
            return None

        return "unsupported-tool-arguments"

    def _result(
        self,
        *,
        call: ToolCall,
        source_snapshot_id: str,
        attempt: int,
        outcome: ToolOutcomeKind,
        evidence_ids: tuple[str, ...] = (),
        error_code: str | None = None,
        safe_summary: str | None = None,
    ) -> ToolResult:
        return ToolResult(
            logical_call_key=compute_tool_call_key(
                call,
                source_snapshot_id,
            ),
            call_id=call.call_id,
            tool_name=call.tool_name,
            outcome=outcome,
            attempt=attempt,
            evidence_ids=evidence_ids,
            error_code=error_code,
            safe_summary=safe_summary,
        )

    def _evidence_allowed_for_call(
        self,
        *,
        call: ToolCall,
        confirmed: ResearchInput,
        evidence_ids: tuple[str, ...],
    ) -> bool:
        if not set(evidence_ids) <= self._known_evidence_ids:
            return False

        arguments = call.arguments
        approved_candidates = set(confirmed.candidates)
        for evidence_id in evidence_ids:
            source_id, _ = evidence_id.split("#", maxsplit=1)
            source = self._sources[source_id]
            candidate_id = source.entry.candidate_id
            if (
                candidate_id is not None
                and candidate_id not in approved_candidates
            ):
                return False

            if isinstance(arguments, SearchSourcesArgs):
                if (
                    candidate_id is not None
                    and candidate_id not in arguments.candidate_ids
                ):
                    return False
                if source.entry.source_type not in arguments.source_types:
                    return False
            elif isinstance(arguments, ReadSourceArgs):
                expected = f"{arguments.source_id}#{arguments.section_id}"
                if evidence_id != expected:
                    return False
            elif isinstance(arguments, CalculateComparisonArgs):
                referenced = {
                    item
                    for candidate in arguments.candidates
                    for dimension in candidate.dimensions
                    for item in dimension.evidence_ids
                }
                if evidence_id not in referenced:
                    return False
        return True

    def execute(
        self,
        *,
        call: ToolCall,
        confirmed: ResearchInput,
        source_snapshot_id: str,
        attempt: int,
    ) -> ToolResult:
        """Return only normalized safe data; never expose raw tool responses."""

        scope_error = self._scope_error(call, confirmed)
        if scope_error is not None:
            return self._result(
                call=call,
                source_snapshot_id=source_snapshot_id,
                attempt=attempt,
                outcome=ToolOutcomeKind.DETERMINISTIC_ERROR,
                error_code="invalid-arguments",
                safe_summary=(
                    "tool arguments exceed approved source or research scope"
                ),
            )

        self.execution_count += 1
        if attempt > len(self._outcomes):
            return self._result(
                call=call,
                source_snapshot_id=source_snapshot_id,
                attempt=attempt,
                outcome=ToolOutcomeKind.DETERMINISTIC_ERROR,
                error_code="script-exhausted",
                safe_summary="deterministic tool script has no matching attempt",
            )

        scripted = self._outcomes[attempt - 1]
        if scripted.tool_name != call.tool_name.value:
            return self._result(
                call=call,
                source_snapshot_id=source_snapshot_id,
                attempt=attempt,
                outcome=ToolOutcomeKind.DETERMINISTIC_ERROR,
                error_code="script-mismatch",
                safe_summary="deterministic tool script uses another tool",
            )

        if scripted.outcome is ToolOutcomeKind.SUCCESS:
            if not self._evidence_allowed_for_call(
                call=call,
                confirmed=confirmed,
                evidence_ids=scripted.evidence_ids,
            ):
                return self._result(
                    call=call,
                    source_snapshot_id=source_snapshot_id,
                    attempt=attempt,
                    outcome=ToolOutcomeKind.DETERMINISTIC_ERROR,
                    error_code="invalid-script",
                    safe_summary=(
                        "deterministic tool script returned out-of-scope evidence"
                    ),
                )
            return self._result(
                call=call,
                source_snapshot_id=source_snapshot_id,
                attempt=attempt,
                outcome=ToolOutcomeKind.SUCCESS,
                evidence_ids=tuple(dict.fromkeys(scripted.evidence_ids)),
            )

        safe_summary = {
            ToolOutcomeKind.TRANSIENT_ERROR: (
                "read-only source tool returned a transient error"
            ),
            ToolOutcomeKind.DETERMINISTIC_ERROR: (
                "read-only source tool returned a deterministic error"
            ),
        }[scripted.outcome]
        return self._result(
            call=call,
            source_snapshot_id=source_snapshot_id,
            attempt=attempt,
            outcome=scripted.outcome,
            error_code=scripted.error_code,
            safe_summary=safe_summary,
        )
