from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
MODEL_REPORT_PATH = PROJECT_ROOT / "data" / "model-assets.json"
TOKEN_AUDIT_PATH = PROJECT_ROOT / "data" / "embedding-token-audit.json"
TOKEN_AUDIT_V2_PATH = (
    PROJECT_ROOT / "data" / "embedding-token-audit-v2.json"
)
CONFIG_ANALYSIS_PATH = (
    PROJECT_ROOT / "data" / "chunk-token-config-analysis.json"
)
INDEX_BUILD_REPORT_PATH = PROJECT_ROOT / "data" / "index-build-report.json"
EXPECTED_REVISION = "46fbe35fd4374a00fee7de77dfddaeb6dd6a2c59"
EXPECTED_ASSETS_SHA256 = (
    "dea3d1b18367c7734c34cdcdc01d4cc7"
    "8ccf8f591fceb7e74d6e272e8f8e4133"
)


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_model_asset_report_pins_identity_and_canonical_file_hashes() -> None:
    report = load_json(MODEL_REPORT_PATH)
    files = report["files"]
    canonical_json = json.dumps(
        files,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    assert report["repository_id"] == "Qdrant/bge-small-zh-v1.5"
    assert report["public_model_name"] == "BAAI/bge-small-zh-v1.5"
    assert report["revision"] == EXPECTED_REVISION
    assert report["license"] == "mit"
    assert report["cache_relative_path"] == "data/models/fastembed"
    assert report["file_count"] == 5
    assert report["total_bytes"] == 95_221_432
    assert [file["relative_path"] for file in files] == [
        "config.json",
        "model_optimized.onnx",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
    ]
    assert report["model_assets_sha256"] == EXPECTED_ASSETS_SHA256
    assert (
        sha256(canonical_json.encode("utf-8")).hexdigest()
        == EXPECTED_ASSETS_SHA256
    )


def test_no_truncation_audit_blocks_current_chunk_baseline() -> None:
    report = load_json(TOKEN_AUDIT_PATH)

    assert report["status"] == "failed"
    assert report["model"]["revision"] == EXPECTED_REVISION
    assert report["model"]["model_assets_sha256"] == EXPECTED_ASSETS_SHA256
    assert report["model"]["configured_truncation"]["max_length"] == 512
    assert report["model"]["audit_truncation"] is None
    assert report["chunking"]["chunk_count"] == 974
    assert report["token_count"]["over_limit_count"] == 94
    assert report["token_count"]["maximum"] == 694
    assert len(report["over_limit"]) == 94
    assert all(
        row["token_count"] > 512 for row in report["over_limit"]
    )


def test_proposed_chunk_candidate_has_zero_token_overflow() -> None:
    report = load_json(CONFIG_ANALYSIS_PATH)
    candidates = {
        candidate["name"]: candidate
        for candidate in report["candidates"]
    }
    proposed = candidates["proportional-520"]

    assert proposed == {
        "name": "proportional-520",
        "max_characters": 520,
        "overlap_characters": 80,
        "minimum_split_characters": 260,
        "chunk_config_sha256": (
            "ff8d07e2916a175093ce9c06920013dd"
            "a95e6ce61036ece84ac34e614c9b28b4"
        ),
        "chunk_count": 1359,
        "overlap_chunk_count": 349,
        "token_median": 241,
        "token_p90": 346,
        "token_p95": 369,
        "token_p99": 407,
        "token_maximum": 460,
        "over_limit_count": 0,
    }


def test_accepted_chunk_baseline_passes_no_truncation_audit() -> None:
    report = load_json(TOKEN_AUDIT_V2_PATH)

    assert report["status"] == "passed"
    assert report["model"]["revision"] == EXPECTED_REVISION
    assert report["model"]["model_assets_sha256"] == EXPECTED_ASSETS_SHA256
    assert report["chunking"] == {
        "schema_version": "chunker-v1",
        "chunk_config_sha256": (
            "ff8d07e2916a175093ce9c06920013dd"
            "a95e6ce61036ece84ac34e614c9b28b4"
        ),
        "chunk_count": 1359,
    }
    assert report["token_count"] == {
        "median": 241,
        "p90": 346,
        "p95": 369,
        "p99": 407,
        "maximum": 460,
        "over_limit_count": 0,
        "per_source_over_limit": {},
    }
    assert report["over_limit"] == []


def test_real_local_index_build_report_matches_pinned_inputs() -> None:
    report = load_json(INDEX_BUILD_REPORT_PATH)

    assert report["status"] == "ready"
    assert report["network_mode"] == "offline"
    assert report["duration_seconds"] > 0
    assert report["model"]["model_revision"] == EXPECTED_REVISION
    assert report["model"]["model_assets_sha256"] == EXPECTED_ASSETS_SHA256
    assert report["model"]["dimension"] == 512
    assert report["model"]["batch_size"] == 64
    assert report["corpus"]["corpus_id"] == (
        "5386ccee-bb5f-5417-b70a-33395abe9669"
    )
    assert report["chunking"]["chunk_count"] == 1359
    assert report["chunking"]["chunk_config_sha256"] == (
        "ff8d07e2916a175093ce9c06920013dd"
        "a95e6ce61036ece84ac34e614c9b28b4"
    )
    assert report["index_manifest"]["index_id"] == (
        "614f6c23-7c35-5832-8086-c29651d60866"
    )
    assert report["index_manifest"]["index_fingerprint"] == (
        "ea641fef238f3e74d6f64fa923feb53f"
        "9a7f36d88b082f14cafdcaabb541c4cd"
    )
    assert report["index_manifest"]["point_count"] == 1359
    assert report["validation"]["point_count"] == 1359
    assert report["validation"]["payload_count"] == 1359
    assert report["validation"]["unique_point_count"] == 1359
    assert report["validation"]["self_query_top_score"] >= 0.999
    assert report["validation"]["version_filter_checked"] is True
    assert report["embedded_count"] == 1359
