"""Inspect relevant evidence ranks beyond top five without changing the index."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ["HF_HUB_OFFLINE"] = "1"

from cited_rag.adapters.fastembed_local import (  # noqa: E402
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.embedding import EmbeddingService  # noqa: E402
from cited_rag.evaluation import (  # noqa: E402
    load_retrieval_evaluation_set,
)
from cited_rag.indexing import load_active_index  # noqa: E402
from cited_rag.model_assets import load_verified_model_assets  # noqa: E402

VERSION_WORDS = re.compile(r"Python 3\.(?:13|14)(?: 中| 的)?\s*")


def main() -> int:
    assets = load_verified_model_assets(
        project_root=PROJECT_ROOT,
        report_path=PROJECT_ROOT / "data" / "model-assets.json",
    )
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
    evaluation_set = load_retrieval_evaluation_set(
        PROJECT_ROOT / "data" / "evaluation" / "retrieval-v1.json"
    )
    _, manifest = load_active_index(
        index_root=PROJECT_ROOT / "data" / "indexes"
    )
    client = QdrantClient(
        path=str(
            (
                PROJECT_ROOT / "data" / "indexes" / "qdrant"
            ).resolve()
        )
    )
    try:
        analyses = []
        for case in evaluation_set.cases:
            query_filter = None
            if case.python_version is not None:
                query_filter = Filter(
                    must=[
                        FieldCondition(
                            key="python_version",
                            match=MatchValue(
                                value=case.python_version,
                            ),
                        )
                    ]
                )
            variants = {
                "raw": case.question,
                "without_redundant_version": VERSION_WORDS.sub(
                    "",
                    case.question,
                ),
            }
            variant_results = {}
            for name, text in variants.items():
                points = client.query_points(
                    collection_name=manifest.collection_name,
                    query=list(service.embed_query(text)),
                    query_filter=query_filter,
                    limit=50,
                    with_payload=True,
                    with_vectors=False,
                ).points
                relevant = set(case.relevant_chunk_ids)
                rank = next(
                    (
                        index
                        for index, point in enumerate(points, start=1)
                        if point.id in relevant
                        or str(point.id)
                        in {str(value) for value in relevant}
                    ),
                    None,
                )
                variant_results[name] = {
                    "query_text": text,
                    "first_relevant_rank": rank,
                    "top_5": [
                        {
                            "rank": index,
                            "chunk_id": str(point.id),
                            "source_id": point.payload["source_id"],
                            "section_anchor": point.payload[
                                "section_anchor"
                            ],
                            "score": float(point.score),
                        }
                        for index, point in enumerate(points[:5], start=1)
                    ],
                }
            raw_rank = variant_results["raw"]["first_relevant_rank"]
            if raw_rank is None or raw_rank > evaluation_set.top_k:
                analyses.append(
                    {
                        "case_id": case.case_id,
                        "relevant_chunk_ids": [
                            str(value) for value in case.relevant_chunk_ids
                        ],
                        "variants": variant_results,
                    }
                )
    finally:
        client.close()

    print(
        json.dumps(
            {
                "schema_version": "1",
                "candidate_limit": 50,
                "cases": analyses,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
