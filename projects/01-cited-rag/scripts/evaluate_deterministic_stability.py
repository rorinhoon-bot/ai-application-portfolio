"""Verify the client-RRF candidate against retrieval-v2 without quality scoring."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import perf_counter_ns

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ["HF_HUB_OFFLINE"] = "1"

from cited_rag.adapters.fastembed_local import (  # noqa: E402
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.embedding import EmbeddingService  # noqa: E402
from cited_rag.evaluation import (  # noqa: E402
    load_retrieval_evaluation_set_v2,
    make_retrieval_evaluation_set_v2_sha256,
)
from cited_rag.model_assets import load_verified_model_assets  # noqa: E402
from cited_rag.qdrant_connection import (  # noqa: E402
    QdrantReadSettings,
    make_read_client_factory,
)
from cited_rag.retrieval import (  # noqa: E402
    HYBRID_CLIENT_RRF_RETRIEVAL_CONFIG,
    QdrantRetrievalService,
    make_retrieval_query,
)
from scripts.evaluate_retrieval_v2 import _load_hybrid_candidate_manifest  # noqa: E402

MODEL_REPORT = PROJECT_ROOT / "data" / "model-assets.json"
INDEX_ROOT = PROJECT_ROOT / "data" / "server-indexes"
EVALUATION_SET = PROJECT_ROOT / "data" / "evaluation" / "retrieval-v2.json"
REPORT = PROJECT_ROOT / "data" / "retrieval-v2-client-rrf-stability-report.json"


def main() -> int:
    if REPORT.exists():
        raise SystemExit(f"refusing to overwrite existing report: {REPORT}")
    settings = QdrantReadSettings(_env_file=PROJECT_ROOT / ".env.qdrant-read")
    if settings.qdrant_profile != "server":
        raise SystemExit("stability evaluation requires the read-only server profile")
    evaluation_set = load_retrieval_evaluation_set_v2(EVALUATION_SET)
    manifest = _load_hybrid_candidate_manifest()
    assets = load_verified_model_assets(
        project_root=PROJECT_ROOT,
        report_path=MODEL_REPORT,
    )
    embedding_service = EmbeddingService.from_config(
        provider=FastEmbedLocalProvider(
            model_dir=assets.snapshot_path,
            config=assets.config,
        ),
        token_counter=FastEmbedNoTruncationTokenCounter(
            model_dir=assets.snapshot_path
        ),
        config=assets.config,
    )
    retriever = QdrantRetrievalService(
        embedding_service=embedding_service,
        index_root=INDEX_ROOT,
        retrieval_config=HYBRID_CLIENT_RRF_RETRIEVAL_CONFIG,
        client_factory=make_read_client_factory(settings),
        manifest_override=manifest,
    )
    retriever.check_ready()
    for case in evaluation_set.cases[:5]:
        retriever.retrieve(
            make_retrieval_query(
                question=case.question,
                python_version=case.python_version,
            )
        )

    cases = []
    for number, case in enumerate(evaluation_set.cases, start=1):
        signatures = []
        latency_ms = []
        diagnostics = []
        for _ in range(3):
            started_ns = perf_counter_ns()
            result = retriever.retrieve(
                make_retrieval_query(
                    question=case.question,
                    python_version=case.python_version,
                )
            )
            latency_ms.append((perf_counter_ns() - started_ns) / 1_000_000)
            signatures.append(_signature(result))
            diagnostics.append(
                {
                    "dense_fetch_limit": result.dense_fetch_limit,
                    "sparse_fetch_limit": result.sparse_fetch_limit,
                    "dense_fetch_rounds": result.dense_fetch_rounds,
                    "sparse_fetch_rounds": result.sparse_fetch_rounds,
                }
            )
        if len(set(signatures)) != 1 or any(
            item != diagnostics[0] for item in diagnostics[1:]
        ):
            raise RuntimeError(
                f"deterministic retrieval changed for case {case.case_id}"
            )
        cases.append(
            {
                "case_id": case.case_id,
                "ranking_signature_sha256": signatures[0],
                "diagnostics": diagnostics[0],
                "latency_ms": latency_ms,
                "stable": True,
            }
        )
        print(f"stability {number}/{len(evaluation_set.cases)}", flush=True)

    report = {
        "schema_version": "1",
        "report_id": "retrieval-v2-client-rrf-stability",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_set_id": evaluation_set.evaluation_set_id,
        "evaluation_set_sha256": make_retrieval_evaluation_set_v2_sha256(
            evaluation_set
        ),
        "index_id": str(manifest.index_id),
        "build_id": str(manifest.build_id),
        "collection_name": manifest.collection_name,
        "retrieval_config": HYBRID_CLIENT_RRF_RETRIEVAL_CONFIG.model_dump(
            mode="json",
            exclude_none=True,
        ),
        "warm_up_count": 5,
        "case_count": len(cases),
        "repetitions_per_case": 3,
        "stable_case_count": len(cases),
        "passed": True,
        "quality_metrics_used_for_release": False,
        "external_api_calls": 0,
        "cases": cases,
    }
    with REPORT.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(json.dumps({"passed": True, "report": str(REPORT)}, ensure_ascii=False))
    return 0


def _signature(result) -> str:
    payload = {
        "results": [
            [item.rank, item.score, str(item.payload.chunk_id)]
            for item in result.results
        ],
        "candidates": [
            [
                item.rank,
                item.score,
                str(item.payload.chunk_id),
                item.dense_rank,
                item.sparse_rank,
            ]
            for item in (result.candidates or ())
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
