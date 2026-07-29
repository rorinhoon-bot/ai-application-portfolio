"""Offline LangGraph tests for the safe report draft slice."""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import ValidationError

from agent_research.data_loader import EvaluationBundle, load_evaluation_bundle
from agent_research.evidence_assessment import (
    DeterministicEvidenceAssessor,
    EvidencePolicy,
    EvidenceRequirement,
)
from agent_research.fake_tools import DeterministicFakeToolExecutor
from agent_research.models import (
    GoldClaim,
    HumanActionKind,
    WorkflowCase,
)
from agent_research.report_drafting import (
    DeterministicFakeWriter,
    DraftClaim,
    DraftPolicy,
    DraftProposal,
    EvidenceCitationBinder,
    hash_report_draft,
)
from agent_research.report_approval import (
    DeterministicHumanReportReviser,
    ReportDecision,
)
from agent_research.report_review import (
    DeterministicDraftReviser,
    DeterministicReportReviewer,
    ReviewOutcome,
    ReviewPolicy,
)
from agent_research.runtime_state import RuntimeState, RuntimeStatus
from agent_research.tool_contracts import (
    SearchSourcesArgs,
    ToolCall,
    ToolName,
)
from agent_research.workflow import (
    _validate_report_decision_binding,
    build_draft_report_graph,
    build_report_confirmation_graph,
    build_report_review_graph,
    create_initial_state,
    HumanDecisionError,
    workflow_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIVACY_EVIDENCE = (
    "atlasflow-security-cost-v1#data-boundary",
    "atlasflow-reliability-v1#checkpointing",
    "procurement-constraints-v1#privacy-policy",
)
PRIVACY_CLAIM_IDS = (
    "atlas-local-data",
    "atlas-durable-checkpoint",
)


def _bundle() -> EvaluationBundle:
    return load_evaluation_bundle(PROJECT_ROOT)


def _case(case_id: str) -> WorkflowCase:
    return next(
        case
        for case in _bundle().evaluation.cases
        if case.case_id == case_id
    )


def _gold_claims(*claim_ids: str) -> tuple[GoldClaim, ...]:
    wanted = set(claim_ids)
    return tuple(
        claim for claim in _bundle().gold.claims if claim.claim_id in wanted
    )


def _proposal() -> DraftProposal:
    return DraftProposal(
        writer_id="deterministic-writer-v1",
        executive_summary=(
            "AtlasFlow matches local data handling and durable recovery needs."
        ),
        claims=tuple(
            DraftClaim.model_validate(claim.model_dump(mode="json"))
            for claim in _gold_claims(*PRIVACY_CLAIM_IDS)
        ),
        recommendation_candidate_id="atlasflow",
        limitations=("Only the fixed synthetic snapshot was evaluated.",),
    )


def _writer(
    proposal: DraftProposal | None = None,
) -> DeterministicFakeWriter:
    return DeterministicFakeWriter(proposal or _proposal())


def _binder() -> EvidenceCitationBinder:
    recommendation_rule = next(
        rule
        for rule in _bundle().gold.recommendation_rules
        if rule.case_id == "privacy-durable-selection"
    )
    return EvidenceCitationBinder(
        sources=_bundle().sources,
        policy=DraftPolicy(
            policy_id="privacy-draft-policy",
            allowed_claims=_gold_claims(*PRIVACY_CLAIM_IDS),
            allowed_recommendations=recommendation_rule.allowed_candidates,
        ),
    )


def _privacy_assessor() -> DeterministicEvidenceAssessor:
    return DeterministicEvidenceAssessor(
        sources=_bundle().sources,
        policy=EvidencePolicy(
            policy_id="privacy-durable-policy",
            requirements=tuple(
                EvidenceRequirement(
                    requirement_id=f"required-proof-{index}",
                    description=f"Required fixed proof number {index}.",
                    acceptable_evidence_sets=((evidence_id,),),
                )
                for index, evidence_id in enumerate(
                    PRIVACY_EVIDENCE,
                    start=1,
                )
            ),
        ),
    )


def _offline_assessor() -> DeterministicEvidenceAssessor:
    return DeterministicEvidenceAssessor(
        sources=_bundle().sources,
        policy=EvidencePolicy(
            policy_id="offline-proof-policy",
            requirements=(
                EvidenceRequirement(
                    requirement_id="deployment-model",
                    description="Deployment model must be present.",
                    acceptable_evidence_sets=(
                        ("cedarflow-overview-v1#deployment-model",),
                    ),
                ),
                EvidenceRequirement(
                    requirement_id="complete-offline-proof",
                    description="Complete offline operation must be explicit.",
                    acceptable_evidence_sets=(),
                ),
            ),
        ),
    )


def _search_call(
    *,
    call_id: str,
    case: WorkflowCase,
    query: str,
    source_types: tuple[str, ...],
    top_k: int,
) -> ToolCall:
    return ToolCall(
        call_id=call_id,
        tool_name=ToolName.SEARCH_SOURCES,
        arguments=SearchSourcesArgs(
            query=query,
            candidate_ids=case.input.candidates,
            source_types=source_types,
            top_k=top_k,
        ),
    )


def _privacy_calls(case: WorkflowCase) -> tuple[ToolCall, ToolCall]:
    first = _search_call(
        call_id="privacy-search",
        case=case,
        query="local data boundary checkpoint recovery privacy policy",
        source_types=(
            "security-and-cost",
            "reliability",
            "constraints",
        ),
        top_k=3,
    )
    return (
        first,
        first.model_copy(update={"call_id": "unused-second-search"}),
    )


def _offline_calls(case: WorkflowCase) -> tuple[ToolCall, ToolCall]:
    return (
        _search_call(
            call_id="offline-search-one",
            case=case,
            query="CedarFlow deployment model offline operation",
            source_types=("overview",),
            top_k=1,
        ),
        _search_call(
            call_id="offline-search-two",
            case=case,
            query="CedarFlow data boundary offline operation",
            source_types=("security-and-cost",),
            top_k=1,
        ),
    )


def _approval(state: RuntimeState) -> dict[str, object]:
    return {
        "schema_version": "requirements-decision-v1",
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "expected_revision": state.human_confirmation_revision,
        "expected_request_hash": state.confirmation_request_hash,
        "action": HumanActionKind.APPROVE.value,
    }


def _snapshot(graph: object, config: dict[str, object]) -> RuntimeState:
    state = graph.get_state(config)  # type: ignore[attr-defined]
    return RuntimeState.model_validate(state.values)


def _run(
    *,
    checkpoint: Path,
    case: WorkflowCase,
    calls: tuple[ToolCall, ToolCall],
    assessor: DeterministicEvidenceAssessor,
    writer: DeterministicFakeWriter,
    binder: EvidenceCitationBinder,
) -> RuntimeState:
    config = workflow_config(f"thread-{case.case_id}")
    executor = DeterministicFakeToolExecutor(
        sources=_bundle().sources,
        outcomes=case.tool_outcomes,
    )
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_draft_report_graph(
            checkpointer=saver,
            tool_calls=calls,
            executor=executor,
            assessor=assessor,
            writer=writer,
            binder=binder,
        )
        graph.invoke(
            create_initial_state(
                run_id=f"run-{case.case_id}",
                thread_id=f"thread-{case.case_id}",
                request=case.input,
            ),
            config,
        )
        waiting = _snapshot(graph, config)
        graph.invoke(Command(resume=_approval(waiting)), config)
        final = _snapshot(graph, config)
        assert graph.get_state(config).next == ()
        return final


def _review_policy() -> ReviewPolicy:
    return ReviewPolicy(
        policy_id="privacy-review-policy",
        required_candidate_ids=("atlasflow",),
        required_dimension_ids=("privacy", "reliability"),
        forbidden_statements=_bundle().gold.forbidden_claims,
    )


def _revision_evidence() -> tuple[str, str]:
    return (
        "atlasflow-overview-v1#deployment-model",
        "atlasflow-security-cost-v1#operations-limit",
    )


def _revision_proposal(
    summary: str = "AtlasFlow fits local control needs.",
) -> DraftProposal:
    return DraftProposal(
        writer_id="deterministic-writer-v1",
        executive_summary=summary,
        claims=tuple(
            DraftClaim.model_validate(claim.model_dump(mode="json"))
            for claim in _gold_claims("atlas-ops-cost")
        ),
        recommendation_candidate_id="atlasflow",
        limitations=(
            "The fixed evidence does not compare every control capability.",
        ),
    )


def _revision_binder() -> EvidenceCitationBinder:
    return EvidenceCitationBinder(
        sources=_bundle().sources,
        policy=DraftPolicy(
            policy_id="revision-draft-policy",
            allowed_claims=_gold_claims("atlas-ops-cost"),
            allowed_recommendations=("atlasflow",),
        ),
    )


def _revision_assessor() -> DeterministicEvidenceAssessor:
    return DeterministicEvidenceAssessor(
        sources=_bundle().sources,
        policy=EvidencePolicy(
            policy_id="revision-evidence-policy",
            requirements=tuple(
                EvidenceRequirement(
                    requirement_id=f"revision-proof-{index}",
                    description=f"Required revision proof {index}.",
                    acceptable_evidence_sets=((evidence_id,),),
                )
                for index, evidence_id in enumerate(
                    _revision_evidence(),
                    start=1,
                )
            ),
        ),
    )


def _revision_calls(case: WorkflowCase) -> tuple[ToolCall, ToolCall]:
    first = _search_call(
        call_id="revision-search",
        case=case,
        query="AtlasFlow local deployment operations cost",
        source_types=("overview", "security-and-cost"),
        top_k=2,
    )
    return (
        first,
        first.model_copy(update={"call_id": "unused-revision-search"}),
    )


def _revision_review_policy() -> ReviewPolicy:
    return ReviewPolicy(
        policy_id="revision-review-policy",
        required_candidate_ids=("atlasflow",),
        required_dimension_ids=("operations",),
        forbidden_statements=_bundle().gold.forbidden_claims,
    )


def _report_decision(
    state: RuntimeState,
    action: HumanActionKind,
) -> dict[str, object]:
    return {
        "schema_version": "report-decision-v1",
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "expected_confirmation_revision": (
            state.report_confirmation_revision
        ),
        "expected_report_revision": state.report_revision,
        "expected_report_hash": state.report_hash,
        "action": action.value,
    }


def _build_revision_confirmation_graph(
    *,
    saver: SqliteSaver,
    human_reviser: DeterministicHumanReportReviser,
    reviewer: DeterministicReportReviewer | None = None,
):
    case = _case("report-revision-approved")
    return build_report_confirmation_graph(
        checkpointer=saver,
        tool_calls=_revision_calls(case),
        executor=DeterministicFakeToolExecutor(
            sources=_bundle().sources,
            outcomes=case.tool_outcomes,
        ),
        assessor=_revision_assessor(),
        writer=_writer(_revision_proposal()),
        binder=_revision_binder(),
        reviewer=reviewer
        or DeterministicReportReviewer(_revision_review_policy()),
        reviser=DeterministicDraftReviser((_revision_proposal(),)),
        human_reviser=human_reviser,
    )


def _run_review(
    *,
    checkpoint: Path,
    writer: DeterministicFakeWriter,
    reviewer: DeterministicReportReviewer,
    reviser: DeterministicDraftReviser,
) -> RuntimeState:
    case = _case("privacy-durable-selection")
    config = workflow_config("thread-privacy-review")
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_report_review_graph(
            checkpointer=saver,
            tool_calls=_privacy_calls(case),
            executor=DeterministicFakeToolExecutor(
                sources=_bundle().sources,
                outcomes=case.tool_outcomes,
            ),
            assessor=_privacy_assessor(),
            writer=writer,
            binder=_binder(),
            reviewer=reviewer,
            reviser=reviser,
        )
        graph.invoke(
            create_initial_state(
                run_id="run-privacy-review",
                thread_id="thread-privacy-review",
                request=case.input,
            ),
            config,
        )
        waiting = _snapshot(graph, config)
        graph.invoke(Command(resume=_approval(waiting)), config)
        final = _snapshot(graph, config)
        assert graph.get_state(config).next == ()
        return final


def test_sufficient_evidence_creates_bound_structured_draft(
    tmp_path: Path,
) -> None:
    case = _case("privacy-durable-selection")
    writer = _writer()

    final = _run(
        checkpoint=tmp_path / "draft.sqlite3",
        case=case,
        calls=_privacy_calls(case),
        assessor=_privacy_assessor(),
        writer=writer,
        binder=_binder(),
    )

    assert final.status is RuntimeStatus.DRAFTED
    assert final.graph_version == "draft-report-v1"
    assert final.report_revision == 1
    assert final.report_draft is not None
    assert final.report_hash == hash_report_draft(final.report_draft)
    assert final.report_draft.recommendation_candidate_id == "atlasflow"
    assert {
        citation.evidence_id
        for citation in final.report_draft.citations
    } <= set(final.evidence_ids)
    assert final.artifact_id is None
    assert final.review_rounds == 0
    assert writer.write_count == 1

    tampered = final.model_dump(mode="json")
    tampered["report_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="report draft hash mismatch"):
        RuntimeState.model_validate(tampered)


def test_invalid_draft_proposal_fails_without_report(
    tmp_path: Path,
) -> None:
    case = _case("privacy-durable-selection")
    proposal = _proposal()
    invalid_claim = proposal.claims[0].model_copy(
        update={
            "evidence_ids": (
                "atlasflow-overview-v1#workflow-control",
            )
        }
    )
    invalid = proposal.model_copy(
        update={"claims": (invalid_claim, proposal.claims[1])}
    )
    writer = _writer(invalid)

    final = _run(
        checkpoint=tmp_path / "invalid-draft.sqlite3",
        case=case,
        calls=_privacy_calls(case),
        assessor=_privacy_assessor(),
        writer=writer,
        binder=_binder(),
    )

    assert final.status is RuntimeStatus.FAILED
    assert final.errors[-1].code == "invalid-draft-proposal"
    assert final.errors[-1].node.value == "draft_report"
    assert final.report_draft is None
    assert final.report_revision == 0
    assert final.report_hash is None
    assert writer.write_count == 1


def test_insufficient_evidence_never_calls_writer(
    tmp_path: Path,
) -> None:
    case = _case("missing-offline-proof")
    writer = _writer()

    final = _run(
        checkpoint=tmp_path / "insufficient.sqlite3",
        case=case,
        calls=_offline_calls(case),
        assessor=_offline_assessor(),
        writer=writer,
        binder=_binder(),
    )

    assert final.status is RuntimeStatus.FAILED
    assert final.errors[-1].code == "evidence-insufficient"
    assert final.report_draft is None
    assert final.report_hash is None
    assert final.artifact_id is None
    assert writer.write_count == 0


def test_checkpoint_restores_draft_without_runtime_writer_or_binder(
    tmp_path: Path,
) -> None:
    case = _case("privacy-durable-selection")
    checkpoint = tmp_path / "draft-checkpoint.sqlite3"
    calls = _privacy_calls(case)
    final = _run(
        checkpoint=checkpoint,
        case=case,
        calls=calls,
        assessor=_privacy_assessor(),
        writer=_writer(),
        binder=_binder(),
    )
    raw = checkpoint.read_bytes()

    assert b"DeterministicFakeWriter" not in raw
    assert b"EvidenceCitationBinder" not in raw
    assert b"private-vendor-response-body" not in raw

    restored_writer = _writer()
    config = workflow_config(f"thread-{case.case_id}")
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        restored_graph = build_draft_report_graph(
            checkpointer=saver,
            tool_calls=calls,
            executor=DeterministicFakeToolExecutor(
                sources=_bundle().sources,
                outcomes=case.tool_outcomes,
            ),
            assessor=_privacy_assessor(),
            writer=restored_writer,
            binder=_binder(),
        )
        restored = _snapshot(restored_graph, config)

    assert restored == final
    assert restored_writer.write_count == 0


def test_clean_draft_passes_review_without_revision(
    tmp_path: Path,
) -> None:
    writer = _writer()
    reviewer = DeterministicReportReviewer(_review_policy())
    reviser = DeterministicDraftReviser((_proposal(),))

    final = _run_review(
        checkpoint=tmp_path / "review-pass.sqlite3",
        writer=writer,
        reviewer=reviewer,
        reviser=reviser,
    )

    assert final.status is RuntimeStatus.REVIEWED
    assert final.graph_version == "report-review-v1"
    assert final.report_revision == 1
    assert final.review_rounds == 0
    assert final.last_review_result is not None
    assert final.last_review_result.outcome is ReviewOutcome.PASS
    assert writer.write_count == 1
    assert reviewer.review_count == 1
    assert reviser.revision_count == 0
    assert final.artifact_id is None

    mismatched = final.model_dump(mode="json")
    mismatched["review_policy_id"] = "another-review-policy"
    with pytest.raises(ValidationError, match="review result policy ID mismatch"):
        RuntimeState.model_validate(mismatched)


def test_forbidden_assertion_is_revised_then_passes(
    tmp_path: Path,
) -> None:
    forbidden = _bundle().gold.forbidden_claims[1]
    flawed = _proposal().model_copy(
        update={"executive_summary": f"错误初稿声称：{forbidden}。"}
    )
    reviewer = DeterministicReportReviewer(_review_policy())
    reviser = DeterministicDraftReviser((_proposal(),))

    final = _run_review(
        checkpoint=tmp_path / "review-revise.sqlite3",
        writer=_writer(flawed),
        reviewer=reviewer,
        reviser=reviser,
    )

    assert final.status is RuntimeStatus.REVIEWED
    assert final.report_revision == 2
    assert final.review_rounds == 1
    assert final.last_review_result is not None
    assert final.last_review_result.outcome is ReviewOutcome.PASS
    assert forbidden not in final.report_draft.executive_summary  # type: ignore[union-attr]
    assert reviewer.review_count == 2
    assert reviser.revision_count == 1


def test_review_stops_after_two_unsuccessful_revisions(
    tmp_path: Path,
) -> None:
    forbidden = _bundle().gold.forbidden_claims[1]
    initial = _proposal().model_copy(
        update={"executive_summary": f"初稿错误：{forbidden}。"}
    )
    revision_one = _proposal().model_copy(
        update={"executive_summary": f"第一次修改仍错误：{forbidden}。"}
    )
    revision_two = _proposal().model_copy(
        update={"executive_summary": f"第二次修改仍错误：{forbidden}。"}
    )
    reviewer = DeterministicReportReviewer(_review_policy())
    reviser = DeterministicDraftReviser((revision_one, revision_two))

    final = _run_review(
        checkpoint=tmp_path / "review-limit.sqlite3",
        writer=_writer(initial),
        reviewer=reviewer,
        reviser=reviser,
    )

    assert final.status is RuntimeStatus.FAILED
    assert final.report_revision == 3
    assert final.review_rounds == 2
    assert final.last_review_result is not None
    assert final.last_review_result.outcome is ReviewOutcome.FAIL
    assert final.errors[-1].code == "review-limit-exhausted"
    assert reviewer.review_count == 3
    assert reviser.revision_count == 2
    assert final.artifact_id is None


def test_checkpoint_restores_reviewed_report_without_runtime_reviewers(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "review-checkpoint.sqlite3"
    final = _run_review(
        checkpoint=checkpoint,
        writer=_writer(),
        reviewer=DeterministicReportReviewer(_review_policy()),
        reviser=DeterministicDraftReviser((_proposal(),)),
    )
    raw = checkpoint.read_bytes()

    assert b"DeterministicReportReviewer" not in raw
    assert b"DeterministicDraftReviser" not in raw

    case = _case("privacy-durable-selection")
    restored_reviewer = DeterministicReportReviewer(_review_policy())
    restored_reviser = DeterministicDraftReviser((_proposal(),))
    config = workflow_config("thread-privacy-review")
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = build_report_review_graph(
            checkpointer=saver,
            tool_calls=_privacy_calls(case),
            executor=DeterministicFakeToolExecutor(
                sources=_bundle().sources,
                outcomes=case.tool_outcomes,
            ),
            assessor=_privacy_assessor(),
            writer=_writer(),
            binder=_binder(),
            reviewer=restored_reviewer,
            reviser=restored_reviser,
        )
        restored = _snapshot(graph, config)

    assert restored == final
    assert restored_reviewer.review_count == 0
    assert restored_reviser.revision_count == 0


def test_report_decision_contract_rejects_unsupported_and_unknown_fields() -> None:
    payload = {
        "run_id": "run-report-contract",
        "thread_id": "thread-report-contract",
        "expected_confirmation_revision": 1,
        "expected_report_revision": 1,
        "expected_report_hash": "a" * 64,
        "action": HumanActionKind.EDIT.value,
    }
    with pytest.raises(ValidationError, match="unsupported report action"):
        ReportDecision.model_validate(payload)

    payload["action"] = HumanActionKind.APPROVE.value
    payload["authorization"] = "must-not-enter-contract"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReportDecision.model_validate(payload)


def test_reviewed_report_pauses_and_bound_approval_stops_without_export(
    tmp_path: Path,
) -> None:
    case = _case("report-revision-approved")
    config = workflow_config("thread-report-approve")
    human_reviser = DeterministicHumanReportReviser(
        (_revision_proposal("Human revision one."),)
    )
    with SqliteSaver.from_conn_string(
        str(tmp_path / "report-approve.sqlite3")
    ) as saver:
        graph = _build_revision_confirmation_graph(
            saver=saver,
            human_reviser=human_reviser,
        )
        graph.invoke(
            create_initial_state(
                run_id="run-report-approve",
                thread_id="thread-report-approve",
                request=case.input,
            ),
            config,
        )
        requirements_wait = _snapshot(graph, config)
        interrupted = graph.invoke(
            Command(resume=_approval(requirements_wait)),
            config,
        )
        report_wait = _snapshot(graph, config)

        assert report_wait.status is RuntimeStatus.REPORT_NEEDS_HUMAN
        assert report_wait.graph_version == "report-confirmation-v1"
        assert report_wait.report_confirmation_revision == 1
        assert report_wait.report_revision == 1
        assert report_wait.last_review_result is not None
        assert report_wait.last_review_result.outcome is ReviewOutcome.PASS
        pause = interrupted["__interrupt__"][0].value
        assert pause["confirmation_revision"] == 1
        assert pause["report_revision"] == report_wait.report_revision
        assert pause["report_hash"] == report_wait.report_hash
        assert pause["report"]["revision"] == report_wait.report_revision

        graph.invoke(
            Command(
                resume=_report_decision(
                    report_wait,
                    HumanActionKind.APPROVE,
                )
            ),
            config,
        )
        final = _snapshot(graph, config)

    assert final.status is RuntimeStatus.REPORT_APPROVED
    assert final.approved_report_revision == final.report_revision
    assert final.approved_report_hash == final.report_hash
    assert final.artifact_id is None
    assert final.idempotency_key is None
    assert human_reviser.revision_count == 0

    tampered = final.model_dump(mode="json")
    tampered["approved_report_hash"] = "f" * 64
    with pytest.raises(
        ValidationError,
        match="report approval must bind current revision and hash",
    ):
        RuntimeState.model_validate(tampered)

    unreviewed = final.model_dump(mode="json")
    unreviewed["last_review_result"] = None
    with pytest.raises(
        ValidationError,
        match="REPORT_APPROVED requires reviewed human confirmation",
    ):
        RuntimeState.model_validate(unreviewed)


def test_change_request_creates_new_revision_and_invalidates_old_approval(
    tmp_path: Path,
) -> None:
    case = _case("report-revision-approved")
    config = workflow_config("thread-report-revision")
    human_reviser = DeterministicHumanReportReviser(
        (_revision_proposal("Rewritten after human request."),)
    )
    reviewer = DeterministicReportReviewer(_revision_review_policy())
    with SqliteSaver.from_conn_string(
        str(tmp_path / "report-revision.sqlite3")
    ) as saver:
        graph = _build_revision_confirmation_graph(
            saver=saver,
            human_reviser=human_reviser,
            reviewer=reviewer,
        )
        graph.invoke(
            create_initial_state(
                run_id="run-report-revision",
                thread_id="thread-report-revision",
                request=case.input,
            ),
            config,
        )
        requirements_wait = _snapshot(graph, config)
        graph.invoke(
            Command(resume=_approval(requirements_wait)),
            config,
        )
        first_wait = _snapshot(graph, config)
        stale_approval = _report_decision(
            first_wait,
            HumanActionKind.APPROVE,
        )

        graph.invoke(
            Command(
                resume=_report_decision(
                    first_wait,
                    HumanActionKind.REQUEST_CHANGES,
                )
            ),
            config,
        )
        second_wait = _snapshot(graph, config)

        assert second_wait.status is RuntimeStatus.REPORT_NEEDS_HUMAN
        assert second_wait.report_confirmation_revision == 2
        assert second_wait.report_revision == 2
        assert second_wait.report_hash != first_wait.report_hash
        assert second_wait.human_revision_count == 1
        assert second_wait.review_rounds == 0
        assert human_reviser.revision_count == 1
        assert reviewer.review_count == 2

        stale_revision = ReportDecision.model_validate(
            _report_decision(second_wait, HumanActionKind.APPROVE)
        ).model_copy(
            update={"expected_report_revision": first_wait.report_revision}
        )
        with pytest.raises(
            HumanDecisionError,
            match="REPORT_DECISION_STALE_REPORT_REVISION",
        ):
            _validate_report_decision_binding(second_wait, stale_revision)

        stale_hash = ReportDecision.model_validate(
            _report_decision(second_wait, HumanActionKind.APPROVE)
        ).model_copy(update={"expected_report_hash": first_wait.report_hash})
        with pytest.raises(
            HumanDecisionError,
            match="REPORT_DECISION_STALE_REPORT_HASH",
        ):
            _validate_report_decision_binding(second_wait, stale_hash)

        wrong_run = ReportDecision.model_validate(
            _report_decision(second_wait, HumanActionKind.APPROVE)
        ).model_copy(update={"run_id": "run-wrong-binding"})
        with pytest.raises(
            HumanDecisionError,
            match="REPORT_DECISION_RUN_ID_MISMATCH",
        ):
            _validate_report_decision_binding(second_wait, wrong_run)

        wrong_thread = ReportDecision.model_validate(
            _report_decision(second_wait, HumanActionKind.APPROVE)
        ).model_copy(update={"thread_id": "thread-wrong-binding"})
        with pytest.raises(
            HumanDecisionError,
            match="REPORT_DECISION_THREAD_ID_MISMATCH",
        ):
            _validate_report_decision_binding(second_wait, wrong_thread)

        with pytest.raises(
            HumanDecisionError,
            match="REPORT_DECISION_STALE_CONFIRMATION_REVISION",
        ):
            graph.invoke(Command(resume=stale_approval), config)


@pytest.mark.parametrize(
    ("action", "expected_status"),
    (
        (HumanActionKind.REJECT, RuntimeStatus.REPORT_REJECTED),
        (HumanActionKind.CANCEL, RuntimeStatus.REPORT_CANCELLED),
    ),
)
def test_report_reject_or_cancel_is_a_stable_terminal(
    tmp_path: Path,
    action: HumanActionKind,
    expected_status: RuntimeStatus,
) -> None:
    case = _case("report-revision-approved")
    thread_id = f"thread-report-{action.value}"
    config = workflow_config(thread_id)
    with SqliteSaver.from_conn_string(
        str(tmp_path / f"report-{action.value}.sqlite3")
    ) as saver:
        graph = _build_revision_confirmation_graph(
            saver=saver,
            human_reviser=DeterministicHumanReportReviser(
                (_revision_proposal(),)
            ),
        )
        graph.invoke(
            create_initial_state(
                run_id=f"run-report-{action.value}",
                thread_id=thread_id,
                request=case.input,
            ),
            config,
        )
        requirements_wait = _snapshot(graph, config)
        graph.invoke(Command(resume=_approval(requirements_wait)), config)
        report_wait = _snapshot(graph, config)
        graph.invoke(
            Command(resume=_report_decision(report_wait, action)),
            config,
        )
        final = _snapshot(graph, config)

        assert final.status is expected_status
        assert graph.get_state(config).next == ()
        assert final.artifact_id is None


def test_third_human_change_request_hits_fixed_limit(
    tmp_path: Path,
) -> None:
    case = _case("report-revision-approved")
    config = workflow_config("thread-human-limit")
    human_reviser = DeterministicHumanReportReviser(
        (
            _revision_proposal("First human-requested revision."),
            _revision_proposal("Second human-requested revision."),
        )
    )
    with SqliteSaver.from_conn_string(
        str(tmp_path / "human-limit.sqlite3")
    ) as saver:
        graph = _build_revision_confirmation_graph(
            saver=saver,
            human_reviser=human_reviser,
        )
        graph.invoke(
            create_initial_state(
                run_id="run-human-limit",
                thread_id="thread-human-limit",
                request=case.input,
            ),
            config,
        )
        waiting = _snapshot(graph, config)
        graph.invoke(Command(resume=_approval(waiting)), config)

        for _ in range(3):
            waiting = _snapshot(graph, config)
            graph.invoke(
                Command(
                    resume=_report_decision(
                        waiting,
                        HumanActionKind.REQUEST_CHANGES,
                    )
                ),
                config,
            )

        final = _snapshot(graph, config)

    assert final.status is RuntimeStatus.FAILED
    assert final.human_revision_count == 2
    assert final.report_confirmation_revision == 3
    assert final.errors[-1].code == "human-revision-limit-exhausted"
    assert final.artifact_id is None
    assert human_reviser.revision_count == 2


def test_report_pause_recovers_with_fresh_runtime_objects_and_no_secrets(
    tmp_path: Path,
) -> None:
    case = _case("report-revision-approved")
    checkpoint = tmp_path / "report-recovery.sqlite3"
    config = workflow_config("thread-report-recovery")
    first_reviser = DeterministicHumanReportReviser(
        (_revision_proposal("Recovered report revision."),)
    )
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        graph = _build_revision_confirmation_graph(
            saver=saver,
            human_reviser=first_reviser,
        )
        graph.invoke(
            create_initial_state(
                run_id="run-report-recovery",
                thread_id="thread-report-recovery",
                request=case.input,
            ),
            config,
        )
        waiting = _snapshot(graph, config)
        graph.invoke(Command(resume=_approval(waiting)), config)
        first_report_wait = _snapshot(graph, config)
        graph.invoke(
            Command(
                resume=_report_decision(
                    first_report_wait,
                    HumanActionKind.REQUEST_CHANGES,
                )
            ),
            config,
        )
        second_report_wait = _snapshot(graph, config)

    raw = checkpoint.read_bytes().lower()
    for forbidden in (
        b"deterministichumanreportreviser",
        b"authorization: bearer",
        b"api_key=",
        b"cookie:",
        b"private-vendor-response-body",
    ):
        assert forbidden not in raw

    fresh_reviser = DeterministicHumanReportReviser(
        (_revision_proposal("Recovered report revision."),)
    )
    fresh_reviewer = DeterministicReportReviewer(_revision_review_policy())
    with SqliteSaver.from_conn_string(str(checkpoint)) as saver:
        restored_graph = _build_revision_confirmation_graph(
            saver=saver,
            human_reviser=fresh_reviser,
            reviewer=fresh_reviewer,
        )
        restored = _snapshot(restored_graph, config)
        assert restored == second_report_wait
        restored_graph.invoke(
            Command(
                resume=_report_decision(
                    restored,
                    HumanActionKind.APPROVE,
                )
            ),
            config,
        )
        final = _snapshot(restored_graph, config)

    assert final.status is RuntimeStatus.REPORT_APPROVED
    assert fresh_reviser.revision_count == 0
    assert fresh_reviewer.review_count == 0


def test_report_confirmation_state_rejects_unknown_and_bounded_values() -> None:
    case = _case("report-revision-approved")
    state = create_initial_state(
        run_id="run-state-bounds",
        thread_id="thread-state-bounds",
        request=case.input,
    )
    state["report_confirmation_revision"] = 33
    with pytest.raises(ValidationError, match="less than or equal to 32"):
        RuntimeState.model_validate(state)

    state["report_confirmation_revision"] = 0
    state["unknown_checkpoint_object"] = {"api_key": "forbidden"}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RuntimeState.model_validate(state)
