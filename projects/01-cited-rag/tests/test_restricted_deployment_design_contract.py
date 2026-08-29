import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = PROJECT_ROOT / "docs" / "RESTRICTED_DEPLOYMENT_DESIGN.md"
AUDIT_PATH = PROJECT_ROOT / "data" / "deployment-capability-audit.json"
PRD_PATH = PROJECT_ROOT / "docs" / "PRD.md"
ARCHITECTURE_PATH = PROJECT_ROOT / "docs" / "ARCHITECTURE.md"
STATUS_PATH = PROJECT_ROOT / "STATUS.md"
DECISIONS_PATH = PROJECT_ROOT / "DECISIONS.md"


def design_text() -> str:
    return DESIGN_PATH.read_text(encoding="utf-8")


def audit_data() -> dict[str, object]:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def test_design_records_local_e1_without_claiming_public_deployment() -> None:
    text = design_text()

    assert "design-frozen；e1-implemented；e2-design-frozen；external-unexecuted" in text
    assert "GitHub Pages托管纯静态制品" in text
    assert "录制证据，非实时推理" in text
    assert "No FastAPI | No Qdrant | No MiMo | No secrets | No arbitrary input" in text


def test_static_artifact_has_truth_and_browser_security_boundaries() -> None:
    text = design_text()

    assert "evidence-manifest.json" in text
    assert "recorded_evidence=true" in text
    assert "`connect-src 'none'`" in text
    assert "不使用远程JavaScript、字体、分析、广告、追踪像素、表单或第三方iframe" in text
    assert "GitHub Pages不能提供项目自定义安全响应头" in text


def test_live_path_requires_identity_persistent_quota_and_cost_breaker() -> None:
    text = design_text()

    assert "每个演示者使用独立、可撤销凭据" in text
    assert "进程重启不能重置预算" in text
    assert "全局日预算与每身份预算在发出MiMo请求前原子扣减" in text
    assert "预算告警不得描述成硬封顶" in text
    assert "不能长期匿名开放" in text


def test_platform_claims_have_official_sources_and_recheck_boundary() -> None:
    text = design_text()

    assert "执行前必须重新检查" in text
    assert "https://docs.github.com/en/pages/" in text
    assert "https://cloud.google.com/run/pricing" in text
    assert "https://qdrant.tech/documentation/cloud/create-cluster/" in text
    assert "https://render.com/docs/free" in text
    assert "https://fly.io/docs/about/pricing/" in text


def test_machine_audit_preserves_unknowns_and_external_zeroes() -> None:
    audit = audit_data()
    workload = audit["workload"]
    decision = audit["decision"]
    effects = audit["external_side_effects"]

    assert audit["status"] == "design-input-complete"
    assert workload["qdrant_point_count"] == 1359
    assert workload["observed_first_query_peak_rss_bytes"] is None
    assert workload["verified_mimo_unit_price"] is None
    assert decision["public_evidence_host"] == "GitHub Pages"
    assert decision["accepts_arbitrary_questions"] is False
    assert decision["anonymous_persistent_live_inference_allowed"] is False
    assert all(value == 0 for value in effects.values())


def test_e1_approval_does_not_authorize_publication_or_live_service() -> None:
    text = design_text()

    assert "不更改GitHub Pages设置，不公开URL，不产生费用" in text
    assert "E1或E2批准不包含E3" in text
    assert "批准按 RESTRICTED_DEPLOYMENT_DESIGN.md 第12.1节执行 V2-E1" in text


def test_public_project_documents_share_the_restricted_deployment_contract() -> None:
    prd = PRD_PATH.read_text(encoding="utf-8")
    architecture = ARCHITECTURE_PATH.read_text(encoding="utf-8")
    status = STATUS_PATH.read_text(encoding="utf-8")
    decisions = DECISIONS_PATH.read_text(encoding="utf-8")

    assert "#### FR-V2-07：受限求职展示" in prd
    assert "### 23.22 P1-F / V2-E双路径展示架构" in architecture
    assert "当前唯一目标：完成V2-E2B发布状态回填" in status
    assert "## D-061：P1-F先公开静态证据" in decisions
    assert "## D-062：V2-E1使用确定性静态证据制品" in decisions
    assert "## D-065：V2-E2B公开激活" in decisions
