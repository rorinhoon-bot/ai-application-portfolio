"""Run the fixed V2 retrieval protocol against read-only Qdrant Server."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from time import perf_counter_ns

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

os.environ["HF_HUB_OFFLINE"] = "1"

from cited_rag.adapters.fastembed_local import (  # noqa: E402
    FastEmbedLocalProvider,
    FastEmbedNoTruncationTokenCounter,
)
from cited_rag.embedding import EmbeddingService  # noqa: E402
from cited_rag.evaluation import (  # noqa: E402
    evaluate_retrieval_v2,
    load_retrieval_evaluation_set_v2,
)
from cited_rag.indexing import load_active_index  # noqa: E402
from cited_rag.indexing import validate_index_manifest  # noqa: E402
from cited_rag.models import IndexManifest  # noqa: E402
from cited_rag.model_assets import load_verified_model_assets  # noqa: E402
from cited_rag.models import RetrievalRuntimeMetadataV2  # noqa: E402
from cited_rag.qdrant_connection import (  # noqa: E402
    QdrantReadSettings,
    make_read_client_factory,
)
from cited_rag.retrieval import (  # noqa: E402
    BASELINE_DENSE_RETRIEVAL_CONFIG,
    DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
    HYBRID_RRF_RETRIEVAL_CONFIG,
    QdrantRetrievalService,
)

MODEL_REPORT = PROJECT_ROOT / "data" / "model-assets.json"
SERVER_INDEX_ROOT = PROJECT_ROOT / "data" / "server-indexes"
EVALUATION_SET = PROJECT_ROOT / "data" / "evaluation" / "retrieval-v2.json"
REPORTS = {
    "dense": PROJECT_ROOT / "data" / "retrieval-v2-dense-report.json",
    "dense-plus-identifiers": (
        PROJECT_ROOT
        / "data"
        / "retrieval-v2-dense-plus-identifiers-report.json"
    ),
    "hybrid-rrf": PROJECT_ROOT / "data" / "retrieval-v2-hybrid-rrf-report.json",
}
HYBRID_BUILD_REPORT = PROJECT_ROOT / "data" / "hybrid-index-build-report.json"
QDRANT_CONTAINER = "cited-rag-qdrant-qdrant-1"
_MEMORY_VALUE = re.compile(r"^(?P<value>[0-9]+(?:\.[0-9]+)?)(?P<unit>KiB|MiB|GiB)$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=tuple(REPORTS),
        required=True,
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="new .json path inside the project; existing files are never overwritten",
    )
    arguments = parser.parse_args()
    try:
        report_path = _resolve_report_path(
            mode=arguments.mode,
            requested=arguments.output,
        )
    except ValueError as error:
        parser.error(str(error))
    if report_path.exists():
        raise SystemExit(f"refusing to overwrite existing report: {report_path}")

    started_ns = perf_counter_ns()
    qdrant_settings = QdrantReadSettings(
        _env_file=PROJECT_ROOT / ".env.qdrant-read"
    )
    if qdrant_settings.qdrant_profile != "server":
        raise SystemExit("V2 evaluation requires the read-only server profile")
    assets = load_verified_model_assets(
        project_root=PROJECT_ROOT,
        report_path=MODEL_REPORT,
    )
    _, active_manifest = load_active_index(index_root=SERVER_INDEX_ROOT)
    manifest = (
        _load_hybrid_candidate_manifest()
        if arguments.mode == "hybrid-rrf"
        else active_manifest
    )
    evaluation_set = load_retrieval_evaluation_set_v2(EVALUATION_SET)
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
    retrieval_config = {
        "dense": BASELINE_DENSE_RETRIEVAL_CONFIG,
        "dense-plus-identifiers": DENSE_IDENTIFIER_RETRIEVAL_CONFIG,
        "hybrid-rrf": HYBRID_RRF_RETRIEVAL_CONFIG,
    }[arguments.mode]
    client_factory = make_read_client_factory(qdrant_settings)
    retriever = QdrantRetrievalService(
        embedding_service=embedding_service,
        index_root=SERVER_INDEX_ROOT,
        retrieval_config=retrieval_config,
        client_factory=client_factory,
        manifest_override=(manifest if arguments.mode == "hybrid-rrf" else None),
    )
    retriever.check_ready()
    cold_start_ms = (perf_counter_ns() - started_ns) / 1_000_000

    client = client_factory(Path("."))
    try:
        qdrant_server_version = client.info().version
    finally:
        client.close()
    runtime = RetrievalRuntimeMetadataV2(
        qdrant_profile="server",
        python_version=platform.python_version(),
        qdrant_server_version=qdrant_server_version,
        qdrant_client_version=version("qdrant-client"),
        fastembed_version=version("fastembed"),
        model_revision=assets.config.model_revision,
        model_asset_bytes=assets.total_bytes,
        collection_storage_bytes=_collection_storage_bytes(
            manifest.collection_name
        ),
        docker_memory_bytes=_docker_memory_bytes(),
        logical_cpu_count=os.cpu_count() or 1,
        process_thread_count=_process_thread_count(),
        cold_start_ms=cold_start_ms,
        candidate_count=evaluation_set.candidate_k,
        external_api_calls=0,
    )
    report = evaluate_retrieval_v2(
        evaluation_set=evaluation_set,
        retriever=retriever,
        manifest=manifest,
        retrieval_config=retrieval_config,
        generated_at=datetime.now(timezone.utc),
        runtime=runtime,
    )
    with report_path.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(
            report.model_dump(mode="json"),
            file,
            ensure_ascii=False,
            indent=2,
        )
        file.write("\n")
    print(
        json.dumps(
            {
                "mode": arguments.mode,
                "evaluation_set_id": report.evaluation_set_id,
                "case_count": report.overall.case_count,
                "recall_at_5": report.overall.recall_at_5,
                "mrr_at_5": report.overall.mrr_at_5,
                "ndcg_at_5": report.overall.ndcg_at_5,
                "candidate_recall_at_20": (
                    report.overall.candidate_recall_at_20
                ),
                "p50_ms": report.latency.p50_ms,
                "p95_ms": report.latency.p95_ms,
                "report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _resolve_report_path(*, mode: str, requested: Path | None) -> Path:
    if requested is None:
        return REPORTS[mode]
    candidate = (
        requested if requested.is_absolute() else PROJECT_ROOT / requested
    ).resolve()
    try:
        candidate.relative_to(PROJECT_ROOT.resolve())
    except ValueError as error:
        raise ValueError("evaluation output must stay inside project root") from error
    if candidate.suffix != ".json" or not candidate.parent.is_dir():
        raise ValueError("evaluation output must use an existing directory and .json suffix")
    return candidate


def _collection_storage_bytes(collection_name: str) -> int:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            QDRANT_CONTAINER,
            "du",
            "-sb",
            f"/qdrant/storage/collections/{collection_name}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return int(completed.stdout.split()[0])


def _docker_memory_bytes() -> int:
    completed = subprocess.run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{.MemUsage}}",
            QDRANT_CONTAINER,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    used = completed.stdout.strip().split("/", maxsplit=1)[0].strip()
    match = _MEMORY_VALUE.fullmatch(used)
    if match is None:
        raise RuntimeError("Docker memory output has an unexpected format")
    factors = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
    return round(float(match.group("value")) * factors[match.group("unit")])


def _process_thread_count() -> int:
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-Process -Id {os.getpid()}).Threads.Count",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return int(completed.stdout.strip())


def _load_hybrid_candidate_manifest() -> IndexManifest:
    try:
        report = json.loads(HYBRID_BUILD_REPORT.read_text(encoding="utf-8"))
        if report["status"] != "ready-inactive":
            raise ValueError
        manifest = IndexManifest.model_validate(report["candidate_manifest"])
        validate_index_manifest(manifest)
        stored_path = SERVER_INDEX_ROOT / "manifests" / f"{manifest.build_id}.json"
        stored = IndexManifest.model_validate_json(stored_path.read_text(encoding="utf-8"))
    except (OSError, KeyError, ValueError) as error:
        raise RuntimeError("Hybrid candidate manifest is unavailable") from error
    if stored != manifest or manifest.specification.schema_version != "2":
        raise RuntimeError("Hybrid candidate manifest does not match stored build")
    return manifest


if __name__ == "__main__":
    raise SystemExit(main())
