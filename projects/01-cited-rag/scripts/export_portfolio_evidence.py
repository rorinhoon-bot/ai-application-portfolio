from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


EXPORTER_VERSION = "p1-portfolio-exporter-v1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SITE_ROOT = REPOSITORY_ROOT / "portfolio-site" / "p1"

SOURCE_REPORTS = (
    "data/answering-v3-report.json",
    "data/conflict-v2-evaluation-report.json",
    "data/conflict-v2-human-review.json",
    "data/retrieval-v3-dense-report.json",
    "data/retrieval-v3-dense-plus-identifiers-report.json",
    "data/retrieval-v3-hybrid-client-rrf-v1-report.json",
    "data/deterministic-fusion-release-report.json",
    "data/hybrid-locked-run-failure.json",
    "data/observability-runtime-release-report.json",
    "data/retry-smoke-report.json",
    "data/ci-smoke-report.json",
)

SOURCE_IMAGES = (
    "docs/images/streamlit-cited-answer.png",
    "docs/images/cli-demo.png",
)

STATIC_SITE_FILES = (
    "index.html",
    "assets/app.js",
    "assets/styles.css",
)

GENERATED_TEXT_FILES = (
    "assets/evidence.json",
    "assets/evidence.js",
)

GENERATED_IMAGE_FILES = {
    "docs/images/streamlit-cited-answer.png": "assets/streamlit-cited-answer.png",
    "docs/images/cli-demo.png": "assets/cli-demo.png",
}


class EvidenceExportError(RuntimeError):
    pass


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, separators=(",", ": "))
        + "\n"
    ).encode("utf-8")


def _require_regular_file(path: Path, *, label: str) -> bytes:
    if path.is_symlink():
        raise EvidenceExportError(f"{label} must not be a symlink: {path.name}")
    if not path.is_file():
        raise EvidenceExportError(f"{label} is missing or not a file: {path.name}")
    return path.read_bytes()


def _load_report(project_root: Path, relative_path: str) -> dict[str, Any]:
    raw = _require_regular_file(project_root / relative_path, label="source report")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceExportError(f"invalid source JSON: {relative_path}") from exc
    if not isinstance(value, dict):
        raise EvidenceExportError(f"source JSON must be an object: {relative_path}")
    return value


def _find_case(report: dict[str, Any], case_id: str) -> dict[str, Any]:
    cases = report.get("cases")
    if not isinstance(cases, list):
        raise EvidenceExportError("source report cases must be a list")
    for case in cases:
        if isinstance(case, dict) and case.get("case_id") == case_id:
            return case
    raise EvidenceExportError(f"required case is missing: {case_id}")


def _citation_view(citation: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": citation["rank"],
        "python_version": citation["python_version"],
        "documentation_release": citation["documentation_release"],
        "section_path": citation["section_path"],
        "citation_url": citation["citation_url"],
        "excerpt": citation["excerpt"],
    }


def _recorded_case(
    *,
    label: str,
    kind: str,
    case: dict[str, Any],
    source_path: str,
    source_sha256: str,
    recorded_at: str,
    model_name: str,
    review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answer = case.get("answer")
    if not isinstance(answer, dict):
        raise EvidenceExportError(f"recorded case has no answer: {case.get('case_id')}")
    citations = answer.get("citations")
    if not isinstance(citations, list):
        raise EvidenceExportError(f"recorded case has invalid citations: {case.get('case_id')}")

    result: dict[str, Any] = {
        "case_id": case["case_id"],
        "label": label,
        "kind": kind,
        "recorded_evidence": True,
        "live_inference": False,
        "question": answer["question"],
        "status": answer["status"],
        "answer": answer["answer"],
        "citations": [_citation_view(item) for item in citations],
        "index_id": answer["index_id"],
        "build_id": answer["build_id"],
        "model_name": model_name,
        "recorded_at": recorded_at,
        "total_tokens": answer.get("total_tokens"),
        "source_path": source_path,
        "source_sha256": source_sha256,
    }
    if review is not None:
        result["review"] = review
    return result


def _retrieval_view(report: dict[str, Any], label: str) -> dict[str, Any]:
    overall = report["overall"]
    latency = report["latency"]
    runtime = report["runtime"]
    return {
        "mode": report["mode"],
        "label": label,
        "evaluation_set_id": report["evaluation_set_id"],
        "evaluation_set_sha256": report["evaluation_set_sha256"],
        "case_count": overall["case_count"],
        "hit_count": overall["hit_count"],
        "recall_at_5": overall["recall_at_5"],
        "mrr_at_5": overall["mrr_at_5"],
        "ndcg_at_5": overall["ndcg_at_5"],
        "candidate_recall_at_20": overall["candidate_recall_at_20"],
        "p50_ms": latency["p50_ms"],
        "p95_ms": latency["p95_ms"],
        "sample_count": latency["sample_count"],
        "external_api_calls": runtime["external_api_calls"],
    }


def build_evidence(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    project_root = project_root.resolve()
    report_bytes = {
        path: _require_regular_file(project_root / path, label="source report")
        for path in SOURCE_REPORTS
    }
    reports = {
        path: _load_report(project_root, path)
        for path in SOURCE_REPORTS
    }
    source_hashes = {path: sha256_bytes(raw) for path, raw in report_bytes.items()}

    answering_path = "data/answering-v3-report.json"
    answering = reports[answering_path]
    answered_case = _find_case(answering, "answer-venv-activation")
    refused_case = _find_case(answering, "refuse-flask-app-context")

    conflict_path = "data/conflict-v2-evaluation-report.json"
    conflict = reports[conflict_path]
    comparison_case = _find_case(conflict, "argparse-prog-balanced")
    review_report = reports["data/conflict-v2-human-review.json"]
    review_case = _find_case(review_report, "argparse-prog-balanced")

    dense_path = "data/retrieval-v3-dense-report.json"
    production_path = "data/retrieval-v3-dense-plus-identifiers-report.json"
    hybrid_path = "data/retrieval-v3-hybrid-client-rrf-v1-report.json"
    release = reports["data/deterministic-fusion-release-report.json"]
    locked_failure = reports["data/hybrid-locked-run-failure.json"]
    observability = reports["data/observability-runtime-release-report.json"]
    retry = reports["data/retry-smoke-report.json"]
    ci = reports["data/ci-smoke-report.json"]

    retry_rate_limit = next(
        item
        for item in retry["scenarios"]
        if item["name"] == "rate_limit_then_success"
    )

    comparison_review = {
        "kind": "post-hoc-human-review",
        "accepted": review_case["accepted"],
        "decision": review_report["decision"],
        "note": review_case["note"],
        "original_automatic_correct": comparison_case["correct"],
        "original_expected_status": comparison_case["expected_status"],
        "accepted_semantics": review_report["accepted_semantics"],
        "review_source_path": "data/conflict-v2-human-review.json",
        "review_source_sha256": source_hashes["data/conflict-v2-human-review.json"],
    }

    active_index = release["active_index"]["after"]
    answer_quality = {
        "evaluation_set_id": answering["evaluation_set_id"],
        "evaluation_set_sha256": answering["evaluation_set_sha256"],
        "case_count": len(answering["cases"]),
        "answerable_recall": answering["answerable_recall"],
        "refusal_accuracy": answering["refusal_accuracy"],
        "citation_binding_validity": answering["citation_binding_validity"],
        "manual_faithfulness": "4/4",
        "api_call_count": answering["api_call_count"],
        "total_tokens": answering["total_tokens"],
        "automatic_retries": answering["automatic_retries"],
        "source_path": answering_path,
        "source_sha256": source_hashes[answering_path],
    }

    evidence = {
        "schema_version": "1",
        "site_id": "p1-cited-rag-recorded-evidence-v1",
        "exporter_version": EXPORTER_VERSION,
        "language": "zh-CN",
        "title": "带引用的 Python 官方文档知识库",
        "headline": "让 RAG 回答可核验，也让发布失败可追溯",
        "recorded_evidence": True,
        "live_service": False,
        "site_status": "local-static-artifact",
        "publication_status": "not-published",
        "remote_ci_status": "workflow-ready-remote-unrun",
        "repository_url": "https://github.com/rorinhoon-bot/ai-application-portfolio",
        "retrieval_comparison": [
            _retrieval_view(reports[dense_path], "Dense 基线"),
            _retrieval_view(reports[production_path], "旧生产路径"),
            _retrieval_view(reports[hybrid_path], "确定性 Hybrid"),
        ],
        "answer_quality": answer_quality,
        "headline_metrics": [
            {
                "label": "新20题 Recall@5",
                "value": "95%",
                "note": "确定性 Hybrid；同集 Dense 为75%",
                "source_path": hybrid_path,
            },
            {
                "label": "候选 Recall@20",
                "value": "100%",
                "note": "相关证据已进入前20",
                "source_path": hybrid_path,
            },
            {
                "label": "引用绑定有效率",
                "value": "100%",
                "note": "answering-v3 固定10题",
                "source_path": answering_path,
            },
            {
                "label": "发布门",
                "value": "14/14",
                "note": "通过后才切活动索引",
                "source_path": "data/deterministic-fusion-release-report.json",
            },
        ],
        "recorded_cases": [
            _recorded_case(
                label="有依据回答",
                kind="answered",
                case=answered_case,
                source_path=answering_path,
                source_sha256=source_hashes[answering_path],
                recorded_at=answering["generated_at"],
                model_name=answering["model_name"],
            ),
            _recorded_case(
                label="证据不足拒答",
                kind="refused",
                case=refused_case,
                source_path=answering_path,
                source_sha256=source_hashes[answering_path],
                recorded_at=answering["generated_at"],
                model_name=answering["model_name"],
            ),
            _recorded_case(
                label="跨版本比较",
                kind="version-comparison",
                case=comparison_case,
                source_path=conflict_path,
                source_sha256=source_hashes[conflict_path],
                recorded_at=conflict["generated_at"],
                model_name=conflict["model"],
                review=comparison_review,
            ),
        ],
        "failure_cases": [
            {
                "label": "服务端 RRF 锁定集失败",
                "status": locked_failure["status"],
                "error_code": locked_failure["error_code"],
                "error_message": locked_failure["error_message"],
                "evidence": "唯一一次 locked-test 在指标生成前发现重复排名漂移；未重跑、未激活。",
                "resolution": "改用 exact 两路召回、同分边界闭合与客户端 Fraction RRF；新20题发布门14/14通过。",
                "source_path": "data/hybrid-locked-run-failure.json",
                "source_sha256": source_hashes["data/hybrid-locked-run-failure.json"],
            },
            {
                "label": "Collector 故障隔离",
                "status": "passed",
                "error_code": None,
                "error_message": None,
                "evidence": "Collector停止时 health=200、ready=200、非法请求=422，API容器身份不变。",
                "resolution": "遥测不参与 readiness；恢复Collector后metrics再次返回200。",
                "source_path": "data/observability-runtime-release-report.json",
                "source_sha256": source_hashes["data/observability-runtime-release-report.json"],
            },
            {
                "label": "429重试与计费不确定性",
                "status": retry_rate_limit["outcome"],
                "error_code": None,
                "error_message": None,
                "evidence": "fake provider先返回429，再成功；共2次物理尝试、1次重试。",
                "resolution": "最多一次重试；潜在已计费尝试显式记录为billing_uncertain，不伪造零费用。",
                "source_path": "data/retry-smoke-report.json",
                "source_sha256": source_hashes["data/retry-smoke-report.json"],
            },
        ],
        "runtime_proof": {
            "active_retrieval_mode": release["post_activation_retrieval_smoke"]["mode"],
            "active_index_id": active_index["index_id"],
            "active_build_id": active_index["build_id"],
            "point_count": active_index["point_count"],
            "api_image": observability["api"]["image"],
            "api_image_size_bytes": observability["api"]["image_size_bytes"],
            "api_user": observability["api"]["container_user"],
            "api_read_only_rootfs": observability["api"]["read_only_rootfs"],
            "healthz": observability["endpoint_checks"]["healthz"],
            "readyz": observability["endpoint_checks"]["readyz"],
            "sensitive_fixture_occurrences": observability["observability_checks"]["sensitive_fixture_occurrences"],
            "qdrant_points": observability["runtime"]["active_collection_points"],
            "ci_smoke_status": ci["status"],
            "ci_network_accessed": ci["network_accessed"],
            "remote_ci_status": "workflow-ready-remote-unrun",
        },
        "architecture": [
            {"step": "01", "title": "只读 FastAPI", "detail": "严格请求模型、Problem Details、服务端request ID"},
            {"step": "02", "title": "确定性 Hybrid", "detail": "Dense exact + 中文/代码 Sparse + Fraction RRF"},
            {"step": "03", "title": "Qdrant Server", "detail": "读写Key隔离、不可变build、snapshot恢复"},
            {"step": "04", "title": "MiMo结构化回答", "detail": "模型只选Chunk ID，引用元数据由程序绑定"},
            {"step": "05", "title": "可观测与CI", "detail": "隐私安全trace/metrics；普通路径完全离线"},
        ],
        "limitations": [
            "当前页面是录制证据，不是实时推理服务；不接受任意问题。",
            "GitHub Pages尚未启用；当前没有可宣传的在线URL。",
            "远程GitHub Actions尚未运行，只能声称workflow-ready。",
            "answering-v3只有10题；跨版本人工复核只有3题。",
            "真实供应商故障、线上并发、硬费用上限和公网高可用仍无证据。",
            "95 MB模型资产与Qdrant运行数据不进入Git，新环境需按README恢复。",
        ],
        "external_side_effects": {
            "network_accessed": False,
            "mimo_called": False,
            "qdrant_written": False,
            "docker_changed": False,
            "dependency_installed": False,
            "cloud_resource_created": False,
            "public_deployment_created": False,
            "remote_workflow_triggered": False,
        },
    }
    return evidence


def _source_manifest(project_root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for relative_path in (*SOURCE_REPORTS, *SOURCE_IMAGES):
        content = _require_regular_file(project_root / relative_path, label="evidence input")
        entries.append(
            {
                "path": f"projects/01-cited-rag/{relative_path}",
                "sha256": sha256_bytes(content),
                "byte_count": len(content),
            }
        )
    return entries


def _javascript_bytes(evidence_json: bytes) -> bytes:
    serialized = evidence_json.decode("utf-8").rstrip("\n")
    outer = json.dumps(serialized, ensure_ascii=True)
    return (
        "/* Generated by export_portfolio_evidence.py. Do not edit. */\n"
        f"globalThis.P1_EVIDENCE = Object.freeze(JSON.parse({outer}));\n"
    ).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise EvidenceExportError(f"output must be a regular file: {path.name}")
    temporary_path = path.with_name(f".{path.name}.tmp")
    if temporary_path.exists():
        raise EvidenceExportError(f"temporary output already exists: {temporary_path.name}")
    try:
        temporary_path.write_bytes(content)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _expected_outputs(project_root: Path, site_root: Path) -> dict[str, bytes]:
    evidence_json = canonical_json_bytes(build_evidence(project_root))
    outputs = {
        "assets/evidence.json": evidence_json,
        "assets/evidence.js": _javascript_bytes(evidence_json),
    }
    for source_path, output_path in GENERATED_IMAGE_FILES.items():
        outputs[output_path] = _require_regular_file(
            project_root / source_path,
            label="source image",
        )
    for relative_path in STATIC_SITE_FILES:
        _require_regular_file(site_root / relative_path, label="static site file")
    return outputs


def _manifest(
    project_root: Path,
    site_root: Path,
    generated_outputs: dict[str, bytes],
) -> dict[str, Any]:
    output_entries: list[dict[str, Any]] = []
    for relative_path in STATIC_SITE_FILES:
        content = _require_regular_file(site_root / relative_path, label="static site file")
        output_entries.append(
            {
                "path": f"portfolio-site/p1/{relative_path}",
                "sha256": sha256_bytes(content),
                "byte_count": len(content),
                "generated": False,
            }
        )
    for relative_path, content in generated_outputs.items():
        output_entries.append(
            {
                "path": f"portfolio-site/p1/{relative_path}",
                "sha256": sha256_bytes(content),
                "byte_count": len(content),
                "generated": True,
            }
        )
    return {
        "schema_version": "1",
        "manifest_id": "p1-static-evidence-manifest-v1",
        "exporter_version": EXPORTER_VERSION,
        "recorded_evidence": True,
        "live_inference": False,
        "publication_status": "not-published",
        "inputs": _source_manifest(project_root),
        "outputs": output_entries,
        "external_side_effects": {
            "network_accessed": False,
            "mimo_called": False,
            "qdrant_written": False,
            "docker_changed": False,
            "dependency_installed": False,
            "cloud_resource_created": False,
            "public_deployment_created": False,
            "remote_workflow_triggered": False,
        },
    }


def export(*, check: bool = False) -> None:
    project_root = PROJECT_ROOT.resolve()
    site_root = SITE_ROOT.resolve()
    expected_site_root = (REPOSITORY_ROOT.resolve() / "portfolio-site" / "p1").resolve()
    if site_root != expected_site_root:
        raise EvidenceExportError("site output root escaped the fixed portfolio directory")
    if SITE_ROOT.exists() and SITE_ROOT.is_symlink():
        raise EvidenceExportError("site root must not be a symlink")

    generated_outputs = _expected_outputs(project_root, site_root)
    manifest_bytes = canonical_json_bytes(_manifest(project_root, site_root, generated_outputs))
    all_outputs = {**generated_outputs, "evidence-manifest.json": manifest_bytes}

    if check:
        mismatches = []
        for relative_path, expected in all_outputs.items():
            output_path = site_root / relative_path
            if not output_path.is_file() or output_path.is_symlink():
                mismatches.append(relative_path)
                continue
            if output_path.read_bytes() != expected:
                mismatches.append(relative_path)
        if mismatches:
            raise EvidenceExportError(
                "static evidence outputs are stale: " + ", ".join(sorted(mismatches))
            )
        return

    for relative_path, content in generated_outputs.items():
        _atomic_write(site_root / relative_path, content)
    _atomic_write(site_root / "evidence-manifest.json", manifest_bytes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export deterministic P1 recorded evidence for the local static portfolio."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify committed outputs without writing files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        export(check=args.check)
    except EvidenceExportError as exc:
        print(f"EVIDENCE_EXPORT_ERROR: {exc}")
        return 1
    print("P1 static evidence outputs are current." if args.check else "P1 static evidence exported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
