"""Run the fixed offline Recall@5 evaluation against the active index."""

from __future__ import annotations

import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Missing local assets must fail; evaluation must never download a model.
os.environ["HF_HUB_OFFLINE"] = "1"

from cited_rag.adapters.fastembed_local import (  # noqa: E402
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.embedding import EmbeddingService  # noqa: E402
from cited_rag.evaluation import (  # noqa: E402
    evaluate_retrieval,
    load_retrieval_evaluation_set,
)
from cited_rag.indexing import load_active_index  # noqa: E402
from cited_rag.model_assets import load_verified_model_assets  # noqa: E402
from cited_rag.retrieval import (  # noqa: E402
    BASELINE_DENSE_RETRIEVAL_CONFIG,
    DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    QdrantRetrievalService,
)

MODEL_REPORT = PROJECT_ROOT / "data" / "model-assets.json"
INDEX_ROOT = PROJECT_ROOT / "data" / "indexes"
EVALUATION_SET = (
    PROJECT_ROOT / "data" / "evaluation" / "retrieval-v1.json"
)
EVALUATION_REPORT = (
    PROJECT_ROOT / "data" / "retrieval-evaluation-report.json"
)
OPTIMIZED_EVALUATION_REPORT = (
    PROJECT_ROOT / "data" / "retrieval-evaluation-optimized-report.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("dense", "dense-plus-identifiers"),
        default="dense",
    )
    arguments = parser.parse_args()
    retrieval_config = (
        BASELINE_DENSE_RETRIEVAL_CONFIG
        if arguments.mode == "dense"
        else DENSE_IDENTIFIER_RETRIEVAL_CONFIG
    )
    report_path = (
        EVALUATION_REPORT
        if arguments.mode == "dense"
        else OPTIMIZED_EVALUATION_REPORT
    )
    assets = load_verified_model_assets(
        project_root=PROJECT_ROOT,
        report_path=MODEL_REPORT,
    )
    _, manifest = load_active_index(index_root=INDEX_ROOT)
    evaluation_set = load_retrieval_evaluation_set(EVALUATION_SET)
    provider = FastEmbedLocalProvider(
        model_dir=assets.snapshot_path,
        config=assets.config,
    )
    token_counter = FastEmbedNoTruncationTokenCounter(
        model_dir=assets.snapshot_path
    )
    embedding_service = EmbeddingService.from_config(
        provider=provider,
        token_counter=token_counter,
        config=assets.config,
    )
    report = evaluate_retrieval(
        evaluation_set=evaluation_set,
        retriever=QdrantRetrievalService(
            embedding_service=embedding_service,
            index_root=INDEX_ROOT,
            retrieval_config=retrieval_config,
        ),
        manifest=manifest,
        retrieval_config=retrieval_config,
        generated_at=datetime.now(timezone.utc),
    )
    report_path.write_text(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "evaluation_set_id": report.evaluation_set_id,
                "case_count": report.case_count,
                "hit_count": report.hit_count,
                "recall_at_5": report.recall_at_5,
                "target_recall_at_5": report.target_recall_at_5,
                "target_met": report.target_met,
                "mode": report.retrieval_config.mode,
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.target_met else 1


if __name__ == "__main__":
    raise SystemExit(main())
