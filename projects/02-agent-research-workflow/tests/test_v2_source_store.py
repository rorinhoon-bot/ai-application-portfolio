"""V2 source snapshot and deterministic tool tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_research.v2.contracts import (
    CandidateSpec,
    DimensionSpec,
    ResearchRequestV2,
    SourceEntryV2,
    SourceSnapshotV2,
)
from agent_research.v2.graph import _coverage_query
from agent_research.v2.source_store import SourceStore, SourceStoreError, load_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_SNAPSHOT = PROJECT_ROOT / "tests" / "fixtures" / "official-snapshot"


def _request() -> ResearchRequestV2:
    return ResearchRequestV2(
        research_question="Choose a workflow framework for a small AI team.",
        audience="student engineering team",
        candidates=(
            CandidateSpec(candidate_id="langgraph", name="LangGraph"),
            CandidateSpec(candidate_id="pydantic-ai", name="PydanticAI"),
        ),
        dimensions=(
            DimensionSpec(dimension_id="tool-calling", question="Tools", weight_percent=34),
            DimensionSpec(dimension_id="human-approval", question="Approval", weight_percent=33),
            DimensionSpec(dimension_id="recovery", question="Recovery", weight_percent=33),
        ),
        source_snapshot_id="snapshot-v2-dev",
        model_config_hash="a" * 64,
        budget_authorization_id="budget-dev",
    )


def _fixture(tmp_path: Path) -> tuple[SourceSnapshotV2, dict[str, str]]:
    text = """# LangGraph fixture\n\n## [tool-calling] Tool calling\nThis workflow framework fixture covers tool calling through a graph node.\n\n## [recovery] Recovery\nThis workflow framework fixture covers checkpoint recovery after interruption.\n"""
    path = tmp_path / "langgraph.md"
    path.write_bytes(text.encode("utf-8"))
    raw = text.encode("utf-8")
    entry = SourceEntryV2(
        source_id="langgraph-docs",
        candidate_id="langgraph",
        title="LangGraph fixture",
        canonical_url="https://example.invalid/langgraph",
        version="dev-fixture",
        accessed_at="2026-09-13T00:00:00Z",
        license_id="MIT",
        relative_path="langgraph.md",
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        normalized_sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )
    snapshot = SourceSnapshotV2(snapshot_id="snapshot-v2-dev", entries=(entry,), total_size_bytes=len(raw))
    (tmp_path / "manifest.json").write_text(snapshot.model_dump_json(), encoding="utf-8")
    return snapshot, {"langgraph-docs": text}


def test_snapshot_hash_and_keyword_search_are_deterministic(tmp_path: Path) -> None:
    snapshot, texts = _fixture(tmp_path)
    loaded, loaded_texts = load_snapshot(tmp_path, tmp_path / "manifest.json")
    assert loaded == snapshot
    store = SourceStore(loaded, loaded_texts)
    first = store.search(query="checkpoint recovery", request=_request(), top_k=4)
    second = store.search(query="checkpoint recovery", request=_request(), top_k=4)
    assert first == second
    assert first[0].evidence_id == "langgraph-docs#recovery"


def test_snapshot_rejects_hash_tampering(tmp_path: Path) -> None:
    _fixture(tmp_path)
    raw = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    raw["entries"][0]["raw_sha256"] = "f" * 64
    (tmp_path / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(SourceStoreError, match="HASH_MISMATCH"):
        load_snapshot(tmp_path, tmp_path / "manifest.json")


def test_search_rejects_invalid_query(tmp_path: Path) -> None:
    snapshot, texts = _fixture(tmp_path)
    store = SourceStore(snapshot, texts)
    with pytest.raises(SourceStoreError, match="QUERY_INVALID"):
        store.search(query="", request=_request())


def test_search_candidate_filter_keeps_results_within_requested_candidate(tmp_path: Path) -> None:
    snapshot, texts = _fixture(tmp_path)
    pydantic_text = "# PydanticAI\n\n## [recovery] Recovery\nDurable recovery fixture.\n"
    raw = pydantic_text.encode("utf-8")
    pydantic = SourceEntryV2(
        source_id="pydantic-ai-docs",
        candidate_id="pydantic-ai",
        title="PydanticAI fixture",
        canonical_url="https://example.invalid/pydantic-ai",
        version="dev-fixture",
        accessed_at="2026-09-13T00:00:00Z",
        license_id="MIT",
        relative_path="pydantic-ai.md",
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        normalized_sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )
    store = SourceStore(
        SourceSnapshotV2(
            snapshot_id=snapshot.snapshot_id,
            entries=(*snapshot.entries, pydantic),
            total_size_bytes=snapshot.total_size_bytes + len(raw),
        ),
        texts | {pydantic.source_id: pydantic_text},
    )

    evidence = store.search(
        query="recovery",
        request=_request(),
        top_k=1,
        candidate_ids=frozenset({"pydantic-ai"}),
    )

    assert [item.candidate_id for item in evidence] == ["pydantic-ai"]


def test_search_slugs_unlabeled_markdown_headings(tmp_path: Path) -> None:
    text = "# PydanticAI\n\n## Output functions\nStructured output is validated before returning.\n"
    raw = text.encode("utf-8")
    entry = SourceEntryV2(
        source_id="pydantic-ai-docs",
        candidate_id="pydantic-ai",
        title="PydanticAI fixture",
        canonical_url="https://example.invalid/pydantic-ai",
        version="dev-fixture",
        accessed_at="2026-09-13T00:00:00Z",
        license_id="MIT",
        relative_path="pydantic-ai.md",
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        normalized_sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )
    snapshot = SourceSnapshotV2(
        snapshot_id="snapshot-v2-dev",
        entries=(entry,),
        total_size_bytes=len(raw),
    )
    store = SourceStore(snapshot, {entry.source_id: text})
    evidence = store.search(query="structured output", request=_request())
    assert evidence[0].evidence_id == "pydantic-ai-docs#output-functions"


def test_h1_only_markdown_page_is_readable() -> None:
    text = "# Durable execution\n\nPreserves progress across restarts and transient failures.\n"
    entry = SourceEntryV2(
        source_id="durable-docs",
        candidate_id="pydantic-ai",
        title="Durable execution",
        canonical_url="https://example.invalid/durable",
        version="dev-fixture",
        accessed_at="2026-09-13T00:00:00Z",
        license_id="MIT",
        relative_path="durable.md",
        raw_sha256="a" * 64,
        normalized_sha256="b" * 64,
        size_bytes=len(text.encode("utf-8")),
    )
    store = SourceStore(
        SourceSnapshotV2(snapshot_id="snapshot-v2-dev", entries=(entry,), total_size_bytes=entry.size_bytes),
        {entry.source_id: text},
    )
    evidence = store.search(query="durable restarts", request=_request())
    assert evidence[0].evidence_id == "durable-docs#durable-execution"


@pytest.mark.parametrize(("candidate", "expected"), [
    ("pydantic-ai", "pa-03#durable-execution"),
    ("langgraph", "lg-03#checkpointer-vs-store"),
])
def test_real_snapshot_coverage_search_reads_persistence(candidate, expected) -> None:
    snapshot, texts = load_snapshot(REAL_SNAPSHOT, REAL_SNAPSHOT / "manifest.json")
    request = ResearchRequestV2(
        research_question="Compare two workflow frameworks.",
        audience="student engineering team",
        candidates=(
            CandidateSpec(candidate_id="langgraph", name="LangGraph"),
            CandidateSpec(candidate_id="pydantic-ai", name="PydanticAI"),
        ),
        dimensions=(
            DimensionSpec(
                dimension_id="state-model",
                question="What official evidence describes state or structured-output modeling?",
                weight_percent=33,
            ),
            DimensionSpec(
                dimension_id="human-approval",
                question="What official evidence describes a human approval boundary?",
                weight_percent=33,
            ),
            DimensionSpec(
                dimension_id="recovery",
                question="What official evidence describes persistence, recovery, or durable execution?",
                weight_percent=34,
            ),
        ),
        source_snapshot_id=snapshot.snapshot_id,
        model_config_hash="a" * 64,
        budget_authorization_id="budget-dev",
    )

    evidence = SourceStore(snapshot, texts).search(
        query=_coverage_query(request.dimensions[2]),
        request=request,
        top_k=1,
        candidate_ids=frozenset({candidate}),
    )

    assert [item.evidence_id for item in evidence] == [expected]


def test_repeated_words_and_unreturned_tail_do_not_dominate_search(tmp_path):
    snapshot, texts = _fixture(tmp_path)
    source_id = snapshot.entries[0].source_id
    texts[source_id] = (
        "## [long] General notes\n" + "checkpoint " * 400
        + "\n## [relevant] Recovery checkpoint\nPersist state and resume a checkpoint.\n"
        + "\n## [hidden] Appendix\n" + "x" * 2500 + " hidden-keyword"
    )
    store = SourceStore(snapshot, texts)
    found = store.search(query="recovery checkpoint", request=_request(), top_k=1)
    assert found[0].section_id == "relevant"
    assert "Persist state" in found[0].excerpt
    assert store.search(query="hidden-keyword", request=_request()) == ()


def test_research_question_finds_interrupt_restart_rules():
    snapshot, texts = load_snapshot(REAL_SNAPSHOT, REAL_SNAPSHOT / "manifest.json")
    evidence = SourceStore(snapshot, texts).search(
        query="Report what restart after an interrupt means and what remains unknown.",
        request=_request(), top_k=1, candidate_ids=frozenset({"langgraph"}),
    )
    assert evidence[0].evidence_id == "lg-02#rules-of-interrupts"
    assert "beginning" in evidence[0].excerpt and "restart" in evidence[0].excerpt
