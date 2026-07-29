"""Calibrate a local evidence-score threshold without calling a model API."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ["HF_HUB_OFFLINE"] = "1"

from cited_rag.adapters.fastembed_local import (  # noqa: E402
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.embedding import EmbeddingService  # noqa: E402
from cited_rag.evidence import (  # noqa: E402
    calibrate_evidence_threshold,
    collect_evidence_scores,
    load_evidence_calibration_set,
)
from cited_rag.indexing import load_active_index  # noqa: E402
from cited_rag.model_assets import load_verified_model_assets  # noqa: E402
from cited_rag.retrieval import (  # noqa: E402
    DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    QdrantRetrievalService,
)

CALIBRATION_SET = (
    PROJECT_ROOT / "data" / "evaluation" / "evidence-calibration-v1.json"
)
REPORT_PATH = (
    PROJECT_ROOT / "data" / "evidence-threshold-calibration-report.json"
)
INDEX_ROOT = PROJECT_ROOT / "data" / "indexes"


def main() -> int:
    assets = load_verified_model_assets(
        project_root=PROJECT_ROOT,
        report_path=PROJECT_ROOT / "data" / "model-assets.json",
    )
    _, manifest = load_active_index(index_root=INDEX_ROOT)
    calibration_set = load_evidence_calibration_set(CALIBRATION_SET)
    provider = FastEmbedLocalProvider(
        model_dir=assets.snapshot_path,
        config=assets.config,
    )
    service = EmbeddingService.from_config(
        provider=provider,
        token_counter=FastEmbedNoTruncationTokenCounter(
            model_dir=assets.snapshot_path
        ),
        config=assets.config,
    )
    retrieval_config = DENSE_IDENTIFIER_RETRIEVAL_CONFIG
    retriever = QdrantRetrievalService(
        embedding_service=service,
        index_root=INDEX_ROOT,
        retrieval_config=retrieval_config,
    )
    observations = collect_evidence_scores(
        calibration_set=calibration_set,
        retriever=retriever,
        manifest=manifest,
        retrieval_config=retrieval_config,
    )
    report = calibrate_evidence_threshold(
        calibration_set=calibration_set,
        observations=observations,
        manifest=manifest,
        retrieval_config=retrieval_config,
        generated_at=datetime.now(timezone.utc),
    )
    REPORT_PATH.write_text(
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
                "selected_threshold": report.selected_threshold,
                "answerable_recall": report.answerable_recall,
                "refusal_accuracy": report.refusal_accuracy,
                "balanced_accuracy": report.balanced_accuracy,
                "target_met": report.target_met,
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.target_met else 1


if __name__ == "__main__":
    raise SystemExit(main())
