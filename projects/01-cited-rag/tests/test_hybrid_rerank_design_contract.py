import json
from hashlib import sha256
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = PROJECT_ROOT / "data" / "hybrid-rerank-capability-audit.json"
DESIGN_PATH = PROJECT_ROOT / "docs" / "HYBRID_RERANK_DESIGN.md"
PREFLIGHT_PATH = PROJECT_ROOT / "data" / "hybrid-index-preflight.json"


def audit() -> dict[str, object]:
    value = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_capability_audit_preserves_old_baseline_and_no_side_effects() -> None:
    value = audit()
    baseline = value["current_baseline"]
    side_effects = value["external_side_effects"]

    assert isinstance(baseline, dict)
    assert baseline["case_count"] == 15
    assert baseline["dense_hit_count"] == 10
    assert baseline["dense_plus_identifiers_hit_count"] == 13
    assert isinstance(side_effects, dict)
    assert not any(side_effects.values())


def test_audit_rejects_non_chinese_fastembed_bm25() -> None:
    bm25 = audit()["fastembed_bm25"]

    assert isinstance(bm25, dict)
    assert bm25["available"] is True
    assert bm25["selected"] is False
    assert "chinese" not in bm25["supported_languages"]


def test_reranker_candidate_is_metadata_only() -> None:
    reranker = audit()["reranker_candidate"]

    assert isinstance(reranker, dict)
    assert reranker["model"] == "BAAI/bge-reranker-base"
    assert reranker["revision"] == "2cfc18c9415c912f9d8155881c133215df768a70"
    assert reranker["required_file_bytes"] == 1_129_559_216
    assert reranker["downloaded"] is False
    assert reranker["selected_for_default_runtime"] is False


def test_design_requires_evaluation_before_hybrid_and_reranker() -> None:
    text = DESIGN_PATH.read_text(encoding="utf-8")

    assert "30题 `development`、20题 `locked-test`" in text
    assert "candidate Recall@20" in text
    assert "批准按 HYBRID_RERANK_DESIGN.md 第10.1节执行 V2-C1" in text
    assert "不安装依赖、不下载模型、不调用MiMo、不重启容器" in text


def test_c2_preflight_freezes_sparse_identity_without_side_effects() -> None:
    value = json.loads(PREFLIGHT_PATH.read_text(encoding="utf-8"))
    config = value["sparse_config"]
    canonical = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    assert value["status"] == "design-ready-runtime-stopped"
    assert sha256(canonical.encode("utf-8")).hexdigest() == (
        value["sparse_config_sha256"]
    )
    assert value["offline_corpus_audit"] == {
        "chunk_count": 1359,
        "token_occurrences": 158321,
        "unique_token_count": 25836,
        "document_sparse_nnz": 118664,
        "average_document_length": 116.49816041206769,
        "average_sparse_nnz": 87.31714495952906,
        "maximum_sparse_nnz": 280,
        "empty_sparse_document_count": 0,
        "mmh3_collision_count": 0,
        "minimum_raw_indices_values_bytes": 949312,
    }
    assert not any(value["preflight_side_effects"].values())


def test_c2_design_requires_explicit_approval_and_protects_old_state() -> None:
    text = DESIGN_PATH.read_text(encoding="utf-8")

    assert "批准按 HYBRID_RERANK_DESIGN.md 第10.2节执行 V2-C2" in text
    assert "旧活动collection、snapshot和两个named volume禁止删除" in text
    assert "未过门则保留候选Manifest和报告，不切指针、不重启API" in text
    assert "1,073,741,824" in text
