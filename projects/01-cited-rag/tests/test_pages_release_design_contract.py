from __future__ import annotations

import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
DESIGN_PATH = PROJECT_ROOT / "docs" / "PAGES_RELEASE_DESIGN.md"
AUDIT_PATH = PROJECT_ROOT / "data" / "pages-release-capability-audit.json"
PLANNED_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "p1-pages.yml"


def design_text() -> str:
    return DESIGN_PATH.read_text(encoding="utf-8")


def audit_data() -> dict[str, object]:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def test_design_splits_local_readiness_from_public_activation() -> None:
    text = design_text()

    assert "V2-E2A本地发布就绪" in text
    assert "V2-E2B公开激活" in text
    assert "E2A通过不自动授权E2B" in text
    assert "批准按 PAGES_RELEASE_DESIGN.md 第11.1节执行 V2-E2A" in text


def test_design_freezes_url_without_claiming_live_site() -> None:
    text = design_text()
    audit = audit_data()

    expected = "https://rorinhoon-bot.github.io/ai-application-portfolio/"
    assert expected in text
    assert audit["url"]["expected_shape"] == expected
    assert audit["url"]["verified_public_url"] is None
    assert "首次部署成功前不得写成实际在线URL" in text


def test_action_supply_chain_uses_only_full_sha_pins() -> None:
    audit = audit_data()
    actions = audit["actions"]

    assert {item["name"] for item in actions} == {
        "actions/checkout",
        "actions/setup-python",
        "actions/upload-pages-artifact",
        "actions/deploy-pages",
    }
    assert all(re.fullmatch(r"[0-9a-f]{40}", item["commit_sha"]) for item in actions)
    text = design_text()
    assert all(item["commit_sha"] in text for item in actions)
    assert "不使用第三方Action、floating tag" in text


def test_permissions_and_triggers_fail_closed() -> None:
    text = design_text()
    workflow = audit_data()["workflow"]

    assert workflow["top_level_permissions_empty"] is True
    assert workflow["verify_permissions"] == {"contents": "read"}
    assert workflow["deploy_permissions"] == {
        "pages": "write",
        "id-token": "write",
    }
    assert workflow["pull_request_deploys"] is False
    assert workflow["non_main_deploys"] is False
    assert "\n  pull_request_target:" not in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "persist-credentials: false" in text


def test_artifact_contract_is_static_bounded_and_rooted() -> None:
    artifact = audit_data()["artifact"]

    assert artifact["root"] == "portfolio-site/p1"
    assert artifact["entrypoint"] == "index.html"
    assert artifact["file_count"] == 9
    assert artifact["byte_count"] == 233881
    assert artifact["maximum_total_bytes"] == 1024 * 1024
    assert artifact["runtime_backend"] is False
    assert artifact["arbitrary_input"] is False
    assert artifact["remote_subresources"] is False


def test_design_snapshot_preserves_zero_side_effects_after_local_implementation() -> None:
    audit = audit_data()

    assert audit["status"] == "design-input-complete"
    assert set(audit["external_side_effects"].values()) == {False}
    assert audit["workflow"]["exists"] is False
    assert PLANNED_WORKFLOW_PATH.is_file()


def test_rollback_preserves_evidence_and_requires_public_change_authority() -> None:
    text = design_text()

    assert "禁止force-push或删除失败证据" in text
    assert "禁用Pages或更改Source是外部设置变更，需用户授权" in text
    assert "E2B批准不包含E3实时服务" in text
