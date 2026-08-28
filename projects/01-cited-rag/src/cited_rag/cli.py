"""Local JSON CLI for the cited knowledge base."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import json
import os
from pathlib import Path
import sys
from typing import Protocol, TextIO

from pydantic import ValidationError

from cited_rag.adapters import create_answer_model_client
from cited_rag.adapters.fastembed_local import (
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.answering import AnsweringService
from cited_rag.config import Settings
from cited_rag.embedding import EmbeddingService
from cited_rag.errors import CitedRagError
from cited_rag.model_assets import load_verified_model_assets
from cited_rag.indexing import load_active_index
from cited_rag.models import AnswerResult, PythonVersion
from cited_rag.qdrant_connection import (
    QdrantReadSettings,
    make_read_client_factory,
)
from cited_rag.retrieval import (
    DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    HYBRID_CLIENT_RRF_RETRIEVAL_CONFIG,
    QdrantRetrievalService,
)
from cited_rag.service import CitedRagService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_REPORT = PROJECT_ROOT / "data" / "model-assets.json"
LOCAL_INDEX_ROOT = PROJECT_ROOT / "data" / "indexes"
SERVER_INDEX_ROOT = PROJECT_ROOT / "data" / "server-indexes"


class Application(Protocol):
    def answer(
        self,
        *,
        question: str,
        python_version: PythonVersion | None = None,
    ) -> AnswerResult:
        ...


ApplicationFactory = Callable[[], Application]


def build_local_application() -> CitedRagService:
    """Build from verified local assets and selected Qdrant profile."""

    os.environ["HF_HUB_OFFLINE"] = "1"
    settings = Settings(_env_file=PROJECT_ROOT / ".env")
    qdrant_settings = QdrantReadSettings(
        _env_file=PROJECT_ROOT / ".env.qdrant-read"
    )
    index_root = _index_root_for_profile(qdrant_settings.qdrant_profile)
    _, active_manifest = load_active_index(index_root=index_root)
    retrieval_config = (
        HYBRID_CLIENT_RRF_RETRIEVAL_CONFIG
        if active_manifest.specification.schema_version == "2"
        else DENSE_IDENTIFIER_RETRIEVAL_CONFIG
    )
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
    return CitedRagService(
        retriever=QdrantRetrievalService(
            embedding_service=embedding_service,
            index_root=index_root,
            retrieval_config=retrieval_config,
            client_factory=make_read_client_factory(qdrant_settings),
        ),
        answerer=AnsweringService(
            model_client=create_answer_model_client(settings)
        ),
    )


def _index_root_for_profile(profile: str) -> Path:
    return LOCAL_INDEX_ROOT if profile == "local" else SERVER_INDEX_ROOT


def main(
    argv: Sequence[str] | None = None,
    *,
    application_factory: ApplicationFactory = build_local_application,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = argparse.ArgumentParser(
        prog="cited-rag",
        description="用本地 Python 官方文档回答并绑定真实引用。",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ask_parser = commands.add_parser("ask")
    ask_parser.add_argument("--question", required=True)
    ask_parser.add_argument(
        "--python-version",
        choices=("3.13", "3.14"),
    )
    arguments = parser.parse_args(argv)

    try:
        result = application_factory().answer(
            question=arguments.question,
            python_version=arguments.python_version,
        )
    except CitedRagError as error:
        _write_json(
            stderr,
            {"error": {"code": error.code, "reason": error.reason}},
        )
        return 1
    except (OSError, ValidationError):
        _write_json(
            stderr,
            {
                "error": {
                    "code": "CONFIG_ERROR",
                    "reason": "local runtime configuration is invalid",
                }
            },
        )
        return 1
    except Exception:
        _write_json(
            stderr,
            {
                "error": {
                    "code": "INTERNAL_ERROR",
                    "reason": "unexpected local application failure",
                }
            },
        )
        return 1

    _write_json(stdout, result.model_dump(mode="json"))
    return 0


def _write_json(stream: TextIO, value: object) -> None:
    stream.write(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    )
