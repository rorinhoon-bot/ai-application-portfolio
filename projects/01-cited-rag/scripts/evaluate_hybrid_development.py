"""Run the frozen 30-case development split before opening locked-test."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["HF_HUB_OFFLINE"] = "1"

from cited_rag.adapters.fastembed_local import (  # noqa: E402
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.embedding import EmbeddingService  # noqa: E402
from cited_rag.evaluation import load_retrieval_evaluation_set_v2  # noqa: E402
from cited_rag.model_assets import load_verified_model_assets  # noqa: E402
from cited_rag.qdrant_connection import (  # noqa: E402
    QdrantReadSettings,
    make_read_client_factory,
)
from cited_rag.retrieval import (  # noqa: E402
    HYBRID_RRF_RETRIEVAL_CONFIG,
    QdrantRetrievalService,
    make_retrieval_query,
)
from scripts.evaluate_retrieval_v2 import _load_hybrid_candidate_manifest  # noqa: E402

MODEL_REPORT = PROJECT_ROOT / "data" / "model-assets.json"
INDEX_ROOT = PROJECT_ROOT / "data" / "server-indexes"
EVALUATION_SET = PROJECT_ROOT / "data" / "evaluation" / "retrieval-v2.json"
REPORT = PROJECT_ROOT / "data" / "retrieval-v2-hybrid-development-report.json"


def main() -> int:
    if REPORT.exists():
        raise FileExistsError("hybrid development report already exists")
    settings = QdrantReadSettings(_env_file=PROJECT_ROOT / ".env.qdrant-read")
    if settings.qdrant_profile != "server":
        raise RuntimeError("Hybrid development requires the server profile")
    assets = load_verified_model_assets(project_root=PROJECT_ROOT, report_path=MODEL_REPORT)
    embedding = EmbeddingService.from_config(
        provider=FastEmbedLocalProvider(model_dir=assets.snapshot_path, config=assets.config),
        token_counter=FastEmbedNoTruncationTokenCounter(model_dir=assets.snapshot_path),
        config=assets.config,
    )
    manifest = _load_hybrid_candidate_manifest()
    retriever = QdrantRetrievalService(
        embedding_service=embedding,
        index_root=INDEX_ROOT,
        retrieval_config=HYBRID_RRF_RETRIEVAL_CONFIG,
        client_factory=make_read_client_factory(settings),
        manifest_override=manifest,
    )
    retriever.check_ready()
    evaluation_set = load_retrieval_evaluation_set_v2(EVALUATION_SET)
    cases = tuple(case for case in evaluation_set.cases if case.split == "development")
    for case in cases[:5]:
        retriever.retrieve(make_retrieval_query(question=case.question, python_version=case.python_version))

    case_results = []
    samples = []
    for case_number, case in enumerate(cases, start=1):
        repetitions = []
        signatures = []
        result = None
        for _ in range(3):
            started = perf_counter_ns()
            result = retriever.retrieve(
                make_retrieval_query(question=case.question, python_version=case.python_version)
            )
            samples.append((perf_counter_ns() - started) / 1_000_000)
            repetitions.append(samples[-1])
            signatures.append(tuple((item.rank, item.score, str(item.payload.chunk_id)) for item in result.results))
        if len(set(signatures)) != 1 or result is None or result.candidates is None:
            raise RuntimeError(
                "Hybrid development ranking changed across repetitions: "
                + json.dumps(signatures, ensure_ascii=False)
            )
        relevant = set(case.relevant_chunk_ids)
        first_rank = next((item.rank for item in result.results if item.payload.chunk_id in relevant), None)
        candidate_rank = next((item.rank for item in result.candidates if item.payload.chunk_id in relevant), None)
        case_results.append({
            "case_id": case.case_id,
            "case_kind": case.case_kind,
            "hit_at_5": first_rank is not None,
            "first_relevant_rank_at_5": first_rank,
            "candidate_hit_at_20": candidate_rank is not None,
            "first_relevant_rank_at_20": candidate_rank,
            "result_chunk_ids": [str(item.payload.chunk_id) for item in result.results],
            "candidate_chunk_ids": [str(item.payload.chunk_id) for item in result.candidates],
            "latency_ms": repetitions,
        })
        if case_number % 5 == 0:
            print(
                json.dumps(
                    {
                        "phase": "development",
                        "completed_cases": case_number,
                        "total_cases": len(cases),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    samples.sort()
    hit_count = sum(item["hit_at_5"] for item in case_results)
    candidate_hits = sum(item["candidate_hit_at_20"] for item in case_results)
    report = {
        "schema_version": "1",
        "slice": "V2-C2-hybrid-development",
        "status": "configuration-frozen",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_set_sha256": "a3b30c755dc2a4036b9d715a9df2bd891bfb850ce2bc2c369b43447c2a8abd13",
        "candidate_manifest": manifest.model_dump(mode="json", exclude_none=True),
        "retrieval_config": HYBRID_RRF_RETRIEVAL_CONFIG.model_dump(mode="json", exclude_none=True),
        "case_count": len(case_results),
        "hit_count": hit_count,
        "recall_at_5": hit_count / len(case_results),
        "candidate_recall_at_20": candidate_hits / len(case_results),
        "sample_count": len(samples),
        "p50_ms": samples[(len(samples) + 1) // 2 - 1],
        "p95_ms": samples[-(-95 * len(samples) // 100) - 1],
        "configuration_changed_after_run": False,
        "external_api_calls": 0,
        "cases": case_results,
    }
    with REPORT.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    print(json.dumps({key: report[key] for key in (
        "status", "case_count", "hit_count", "recall_at_5",
        "candidate_recall_at_20", "p50_ms", "p95_ms",
    )}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
