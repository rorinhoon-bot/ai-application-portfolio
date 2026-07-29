"""Run one explicitly authorized, bounded MiMo answer smoke test."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Retrieval must never cause a model-asset download.
os.environ["HF_HUB_OFFLINE"] = "1"

from cited_rag.adapters import create_answer_model_client  # noqa: E402
from cited_rag.adapters.fastembed_local import (  # noqa: E402
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.adapters.mimo import MAX_COMPLETION_TOKENS  # noqa: E402
from cited_rag.answering import (  # noqa: E402
    AnsweringService,
    make_answer_model_request,
)
from cited_rag.config import Settings  # noqa: E402
from cited_rag.embedding import EmbeddingService  # noqa: E402
from cited_rag.model_assets import load_verified_model_assets  # noqa: E402
from cited_rag.retrieval import (  # noqa: E402
    DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    QdrantRetrievalService,
    make_retrieval_query,
)

MODEL_REPORT = PROJECT_ROOT / "data" / "model-assets.json"
INDEX_ROOT = PROJECT_ROOT / "data" / "indexes"
REPORT_PATH = PROJECT_ROOT / "data" / "mimo-smoke-report.json"
QUESTION = "Python 3.14 中，使用 venv 创建虚拟环境应运行什么命令？"
PYTHON_VERSION = "3.14"
AUTHORIZED_CNY_LIMIT = 5


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform exactly one real MiMo request",
    )
    arguments = parser.parse_args()

    assets = load_verified_model_assets(
        project_root=PROJECT_ROOT,
        report_path=MODEL_REPORT,
    )
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
    retrieval = QdrantRetrievalService(
        embedding_service=embedding_service,
        index_root=INDEX_ROOT,
        retrieval_config=DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    ).retrieve(
        make_retrieval_query(
            question=QUESTION,
            python_version=PYTHON_VERSION,
        )
    )
    request = make_answer_model_request(retrieval)
    request_characters = len(
        json.dumps(
            request.user_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    summary = {
        "mode": "execute" if arguments.execute else "dry-run",
        "question": QUESTION,
        "python_version": PYTHON_VERSION,
        "retrieved_count": len(retrieval.results),
        "retrieved_chunk_ids": [
            str(item.payload.chunk_id) for item in retrieval.results
        ],
        "request_payload_characters": request_characters,
        "maximum_completion_tokens": MAX_COMPLETION_TOKENS,
        "maximum_api_calls": 1,
        "automatic_retries": 0,
        "authorized_cny_limit": AUTHORIZED_CNY_LIMIT,
    }
    if not arguments.execute:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    settings = Settings(_env_file=PROJECT_ROOT / ".env")
    answer = AnsweringService(
        model_client=create_answer_model_client(settings)
    ).answer(retrieval)
    report = {
        "schema_version": "1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": settings.model_provider,
        "model": settings.model_name,
        "call_count": 1,
        "automatic_retries": 0,
        "authorized_cny_limit": AUTHORIZED_CNY_LIMIT,
        "maximum_completion_tokens": MAX_COMPLETION_TOKENS,
        "request_payload_characters": request_characters,
        "answer": answer.model_dump(mode="json"),
    }
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
