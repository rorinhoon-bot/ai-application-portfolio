"""Freeze retrieval-v3 semantics and verify evidence without retrieval queries."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)]

from cited_rag.evaluation import (  # noqa: E402
    load_retrieval_evaluation_set_v2,
    load_retrieval_evaluation_set_v3,
    make_retrieval_evaluation_set_v2_sha256,
    make_retrieval_evaluation_set_v3_sha256,
)
from cited_rag.indexing import load_active_index  # noqa: E402
from cited_rag.models import ChunkPayload  # noqa: E402
from cited_rag.qdrant_connection import (  # noqa: E402
    QdrantReadSettings,
    make_read_client_factory,
)
from scripts.evaluate_retrieval_v2 import _load_hybrid_candidate_manifest  # noqa: E402

V2_SET = PROJECT_ROOT / "data" / "evaluation" / "retrieval-v2.json"
V3_SET = PROJECT_ROOT / "data" / "evaluation" / "retrieval-v3.json"
AUDIT = PROJECT_ROOT / "data" / "retrieval-v3-evidence-audit.json"
INDEX_ROOT = PROJECT_ROOT / "data" / "server-indexes"
V3_REPORTS = tuple(
    PROJECT_ROOT / "data" / f"retrieval-v3-{mode}-report.json"
    for mode in ("dense", "dense-plus-identifiers", "hybrid-client-rrf-v1")
)


def main() -> int:
    if AUDIT.exists():
        raise SystemExit(f"refusing to overwrite existing audit: {AUDIT}")
    if any(path.exists() for path in V3_REPORTS):
        raise SystemExit("V3 report exists before evidence freeze")
    v2 = load_retrieval_evaluation_set_v2(V2_SET)
    v3 = load_retrieval_evaluation_set_v3(V3_SET)
    candidate = _load_hybrid_candidate_manifest()
    _, production = load_active_index(index_root=INDEX_ROOT)
    if v3.source_index_fingerprint != candidate.index_fingerprint:
        raise SystemExit("V3 source fingerprint does not match candidate index")
    v2_questions = {case.question for case in v2.cases}
    v3_questions = {case.question for case in v3.cases}
    question_overlap = sorted(v2_questions & v3_questions)
    v2_chunks = {
        chunk_id for case in v2.cases for chunk_id in case.relevant_chunk_ids
    }
    v3_chunks = [
        chunk_id for case in v3.cases for chunk_id in case.relevant_chunk_ids
    ]
    chunk_overlap = sorted(str(item) for item in v2_chunks & set(v3_chunks))
    if question_overlap or chunk_overlap:
        raise SystemExit("V3 overlaps retrieval-v2")

    settings = QdrantReadSettings(_env_file=PROJECT_ROOT / ".env.qdrant-read")
    if settings.qdrant_profile != "server":
        raise SystemExit("V3 audit requires the read-only server profile")
    client = make_read_client_factory(settings)(Path("."))
    try:
        candidate_records = client.retrieve(
            collection_name=candidate.collection_name,
            ids=v3_chunks,
            with_payload=True,
            with_vectors=False,
        )
        production_records = client.retrieve(
            collection_name=production.collection_name,
            ids=v3_chunks,
            with_payload=True,
            with_vectors=False,
        )
    finally:
        client.close()
    candidate_payloads = _validated_payloads(candidate_records, v3_chunks)
    production_payloads = _validated_payloads(production_records, v3_chunks)
    if candidate_payloads != production_payloads:
        raise SystemExit("candidate and production payloads differ")
    version_mismatches = []
    for case in v3.cases:
        for chunk_id in case.relevant_chunk_ids:
            payload = candidate_payloads[str(chunk_id)]
            if (
                case.python_version is not None
                and payload.python_version != case.python_version
            ):
                version_mismatches.append(case.case_id)
    if version_mismatches:
        raise SystemExit("V3 evidence version mismatch")

    report = {
        "schema_version": "1",
        "audit_id": "retrieval-v3-evidence-audit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_set_id": v3.evaluation_set_id,
        "evaluation_set_sha256": make_retrieval_evaluation_set_v3_sha256(v3),
        "previous_evaluation_set_id": v2.evaluation_set_id,
        "previous_evaluation_set_sha256": make_retrieval_evaluation_set_v2_sha256(v2),
        "source_index_fingerprint": v3.source_index_fingerprint,
        "source_build_id": str(candidate.build_id),
        "source_collection_name": candidate.collection_name,
        "production_build_id": str(production.build_id),
        "production_collection_name": production.collection_name,
        "case_count": len(v3.cases),
        "verified_payload_count": len(candidate_payloads),
        "case_kind_counts": {
            kind: sum(case.case_kind == kind for case in v3.cases)
            for kind in (
                "semantic-paraphrase",
                "exact-identifier",
                "mixed-semantic-identifier",
                "version-specific",
                "known-hard",
            )
        },
        "question_overlap_with_v2_count": 0,
        "relevant_chunk_overlap_with_v2_count": 0,
        "payload_identity_mismatch_count": 0,
        "version_mismatch_count": 0,
        "query_runs_before_freeze": 0,
        "authoring_used_retrieval_top_k": False,
        "external_api_calls": 0,
        "passed": True,
    }
    with AUDIT.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _validated_payloads(records, expected_ids) -> dict[str, ChunkPayload]:
    expected = {str(item) for item in expected_ids}
    by_id = {str(record.id): record for record in records}
    if len(by_id) != len(records) or set(by_id) != expected:
        raise SystemExit("V3 payload lookup returned wrong IDs")
    payloads = {}
    for point_id, record in by_id.items():
        payload = ChunkPayload.model_validate(record.payload)
        if str(payload.chunk_id) != point_id:
            raise SystemExit("V3 payload chunk ID mismatch")
        payloads[point_id] = payload
    return payloads


if __name__ == "__main__":
    raise SystemExit(main())
