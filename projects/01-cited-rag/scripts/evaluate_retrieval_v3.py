"""Run one release-locked retrieval-v3 mode in the frozen order."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
from math import ceil, log2
import os
from pathlib import Path
import platform
import sys
from time import perf_counter_ns

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT_ROOT / "src"), str(PROJECT_ROOT)]
os.environ["HF_HUB_OFFLINE"] = "1"

from cited_rag.adapters.fastembed_local import (  # noqa: E402
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.embedding import EmbeddingService  # noqa: E402
from cited_rag.evaluation import (  # noqa: E402
    load_retrieval_evaluation_set_v3,
    make_retrieval_evaluation_set_v3_sha256,
)
from cited_rag.indexing import load_active_index  # noqa: E402
from cited_rag.model_assets import load_verified_model_assets  # noqa: E402
from cited_rag.qdrant_connection import (  # noqa: E402
    QdrantReadSettings,
    make_read_client_factory,
)
from cited_rag.retrieval import (  # noqa: E402
    BASELINE_DENSE_RETRIEVAL_CONFIG,
    DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    HYBRID_CLIENT_RRF_RETRIEVAL_CONFIG,
    QdrantRetrievalService,
    make_retrieval_query,
)
from scripts.evaluate_retrieval_v2 import _load_hybrid_candidate_manifest  # noqa: E402

MODEL_REPORT = PROJECT_ROOT / "data" / "model-assets.json"
INDEX_ROOT = PROJECT_ROOT / "data" / "server-indexes"
EVALUATION_SET = PROJECT_ROOT / "data" / "evaluation" / "retrieval-v3.json"
AUDIT = PROJECT_ROOT / "data" / "retrieval-v3-evidence-audit.json"
MODES = ("dense", "dense-plus-identifiers", "hybrid-client-rrf-v1")
REPORTS = {
    mode: PROJECT_ROOT / "data" / f"retrieval-v3-{mode}-report.json"
    for mode in MODES
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=MODES)
    arguments = parser.parse_args()
    _enforce_frozen_order(arguments.mode)
    evaluation_set = load_retrieval_evaluation_set_v3(EVALUATION_SET)
    evaluation_hash = make_retrieval_evaluation_set_v3_sha256(evaluation_set)
    audit = _load_audit(evaluation_hash)
    settings = QdrantReadSettings(_env_file=PROJECT_ROOT / ".env.qdrant-read")
    if settings.qdrant_profile != "server":
        raise SystemExit("V3 evaluation requires the read-only server profile")
    _, production = load_active_index(index_root=INDEX_ROOT)
    candidate = _load_hybrid_candidate_manifest()
    manifest = candidate if arguments.mode == "hybrid-client-rrf-v1" else production
    config = {
        "dense": BASELINE_DENSE_RETRIEVAL_CONFIG,
        "dense-plus-identifiers": DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
        "hybrid-client-rrf-v1": HYBRID_CLIENT_RRF_RETRIEVAL_CONFIG,
    }[arguments.mode]
    assets = load_verified_model_assets(
        project_root=PROJECT_ROOT,
        report_path=MODEL_REPORT,
    )
    retriever = QdrantRetrievalService(
        embedding_service=EmbeddingService.from_config(
            provider=FastEmbedLocalProvider(
                model_dir=assets.snapshot_path,
                config=assets.config,
            ),
            token_counter=FastEmbedNoTruncationTokenCounter(
                model_dir=assets.snapshot_path
            ),
            config=assets.config,
        ),
        index_root=INDEX_ROOT,
        retrieval_config=config,
        client_factory=make_read_client_factory(settings),
        manifest_override=(candidate if manifest == candidate else None),
    )
    retriever.check_ready()
    for case in evaluation_set.cases[:5]:
        result = retriever.retrieve(_query(case))
        _validate_identity(result, manifest, config)

    case_reports = []
    for number, case in enumerate(evaluation_set.cases, start=1):
        results = []
        latency_ms = []
        for _ in range(3):
            started_ns = perf_counter_ns()
            result = retriever.retrieve(_query(case))
            latency_ms.append((perf_counter_ns() - started_ns) / 1_000_000)
            _validate_identity(result, manifest, config)
            results.append(result)
        signatures = [_signature(result) for result in results]
        if any(signature != signatures[0] for signature in signatures[1:]):
            raise RuntimeError(f"V3 repeated ranking changed for {case.case_id}")
        first = results[0]
        relevant = set(case.relevant_chunk_ids)
        first_rank = next(
            (
                item.rank
                for item in first.results
                if item.payload.chunk_id in relevant
            ),
            None,
        )
        candidate_rank = (
            next(
                (
                    item.rank
                    for item in first.candidates
                    if item.payload.chunk_id in relevant
                ),
                None,
            )
            if first.candidates is not None
            else None
        )
        case_reports.append(
            {
                "case_id": case.case_id,
                "question": case.question,
                "python_version": case.python_version,
                "case_kind": case.case_kind,
                "relevant_chunk_ids": [str(item) for item in case.relevant_chunk_ids],
                "retrieved": [_observation(item) for item in first.results],
                "candidates": (
                    [_candidate_observation(item) for item in first.candidates]
                    if first.candidates is not None
                    else None
                ),
                "hit_at_5": first_rank is not None,
                "first_relevant_rank_at_5": first_rank,
                "reciprocal_rank_at_5": 0 if first_rank is None else 1 / first_rank,
                "ndcg_at_5": _ndcg(first.results, relevant),
                "candidate_hit_at_20": (
                    candidate_rank is not None
                    if first.candidates is not None
                    else None
                ),
                "first_relevant_rank_at_20": candidate_rank,
                "latency_ms": latency_ms,
                "ranking_signature": signatures[0],
                "dense_fetch_limit": first.dense_fetch_limit,
                "sparse_fetch_limit": first.sparse_fetch_limit,
                "dense_fetch_rounds": first.dense_fetch_rounds,
                "sparse_fetch_rounds": first.sparse_fetch_rounds,
                "repeat_stable": True,
            }
        )
        print(f"{arguments.mode} {number}/{len(evaluation_set.cases)}", flush=True)

    samples = sorted(
        sample for case in case_reports for sample in case["latency_ms"]
    )
    report = {
        "schema_version": "3",
        "report_id": f"retrieval-v3-{arguments.mode}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_set_id": evaluation_set.evaluation_set_id,
        "evaluation_set_sha256": evaluation_hash,
        "evidence_audit_id": audit["audit_id"],
        "release_locked": True,
        "quality_metrics_used_for_release": True,
        "mode": arguments.mode,
        "index_id": str(manifest.index_id),
        "build_id": str(manifest.build_id),
        "index_fingerprint": manifest.index_fingerprint,
        "collection_name": manifest.collection_name,
        "retrieval_config": config.model_dump(mode="json", exclude_none=True),
        "case_count": len(case_reports),
        "overall": _aggregate(case_reports),
        "by_case_kind": {
            kind: _aggregate(
                [case for case in case_reports if case["case_kind"] == kind]
            )
            for kind in (
                "semantic-paraphrase",
                "exact-identifier",
                "mixed-semantic-identifier",
                "version-specific",
                "known-hard",
            )
        },
        "candidate_metric_status": (
            "available" if arguments.mode == "hybrid-client-rrf-v1" else "unavailable"
        ),
        "latency": {
            "warm_up_count": 5,
            "repetitions_per_case": 3,
            "sample_count": len(samples),
            "percentile_method": "nearest-rank",
            "minimum_ms": samples[0],
            "p50_ms": _percentile(samples, 0.50),
            "p95_ms": _percentile(samples, 0.95),
            "maximum_ms": samples[-1],
        },
        "runtime": {
            "python_version": platform.python_version(),
            "qdrant_client_version": version("qdrant-client"),
            "fastembed_version": version("fastembed"),
            "model_revision": assets.config.model_revision,
            "model_asset_bytes": assets.total_bytes,
            "external_api_calls": 0,
        },
        "repeat_stable_case_count": len(case_reports),
        "payload_validation_rate": 1.0,
        "cases": case_reports,
    }
    path = REPORTS[arguments.mode]
    with path.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(
        json.dumps(
            {
                "mode": arguments.mode,
                "overall": report["overall"],
                "p95_ms": report["latency"]["p95_ms"],
                "report": str(path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _enforce_frozen_order(mode: str) -> None:
    position = MODES.index(mode)
    if REPORTS[mode].exists():
        raise SystemExit(f"refusing to overwrite existing report: {REPORTS[mode]}")
    if any(REPORTS[item].exists() for item in MODES[position + 1 :]):
        raise SystemExit("a later V3 mode report already exists")
    missing = [item for item in MODES[:position] if not REPORTS[item].exists()]
    if missing:
        raise SystemExit(f"V3 modes must run in order; missing: {', '.join(missing)}")


def _load_audit(evaluation_hash: str) -> dict[str, object]:
    try:
        audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit("V3 evidence audit is unavailable") from error
    if (
        audit.get("passed") is not True
        or audit.get("query_runs_before_freeze") != 0
        or audit.get("authoring_used_retrieval_top_k") is not False
        or audit.get("evaluation_set_sha256") != evaluation_hash
    ):
        raise SystemExit("V3 evidence audit does not authorize evaluation")
    return audit


def _query(case):
    return make_retrieval_query(
        question=case.question,
        python_version=case.python_version,
    )


def _validate_identity(result, manifest, config) -> None:
    if (
        result.index_id != manifest.index_id
        or result.build_id != manifest.build_id
        or result.collection_name != manifest.collection_name
        or result.retrieval_config != config
    ):
        raise RuntimeError("V3 retrieval identity changed")


def _signature(result) -> str:
    values = [
        [item.rank, item.score, str(item.payload.chunk_id), item.retrieval_reason]
        for item in result.results
    ]
    values.extend(
        [
            item.rank,
            item.score,
            str(item.payload.chunk_id),
            item.dense_rank,
            item.sparse_rank,
        ]
        for item in (result.candidates or ())
    )
    values.append(
        [
            result.dense_fetch_limit,
            result.sparse_fetch_limit,
            result.dense_fetch_rounds,
            result.sparse_fetch_rounds,
        ]
    )
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _observation(item) -> dict[str, object]:
    return {
        "rank": item.rank,
        "score": item.score,
        "chunk_id": str(item.payload.chunk_id),
        "source_id": item.payload.source_id,
        "python_version": item.payload.python_version,
        "section_anchor": item.payload.section_anchor,
        "retrieval_reason": item.retrieval_reason,
    }


def _candidate_observation(item) -> dict[str, object]:
    return {
        **_observation(item),
        "dense_rank": item.dense_rank,
        "sparse_rank": item.sparse_rank,
    }


def _ndcg(results, relevant) -> float:
    dcg = sum(
        1 / log2(item.rank + 1)
        for item in results
        if item.payload.chunk_id in relevant
    )
    ideal = sum(
        1 / log2(rank + 1)
        for rank in range(1, min(len(relevant), 5) + 1)
    )
    return 0 if ideal == 0 else dcg / ideal


def _aggregate(cases) -> dict[str, object]:
    count = len(cases)
    candidate_available = all(case["candidates"] is not None for case in cases)
    return {
        "case_count": count,
        "hit_count": sum(case["hit_at_5"] for case in cases),
        "recall_at_5": sum(case["hit_at_5"] for case in cases) / count,
        "mrr_at_5": sum(case["reciprocal_rank_at_5"] for case in cases) / count,
        "ndcg_at_5": sum(case["ndcg_at_5"] for case in cases) / count,
        "candidate_recall_at_20": (
            sum(case["candidate_hit_at_20"] for case in cases) / count
            if candidate_available
            else None
        ),
    }


def _percentile(samples: list[float], fraction: float) -> float:
    return samples[ceil(fraction * len(samples)) - 1]


if __name__ == "__main__":
    raise SystemExit(main())
