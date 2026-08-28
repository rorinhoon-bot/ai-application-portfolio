from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "p1-pages.yml"
CI_WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "p1-ci.yml"

ACTION_PINS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/upload-pages-artifact": "fc324d3547104276b827a68afc52ff2a11cc49c9",
    "actions/deploy-pages": "cd2ce8fcbc39b97be8ca5fce6e763baed58fa128",
}


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def indented_block(text: str, heading: str, indentation: int) -> str:
    lines = text.splitlines()
    start = lines.index(" " * indentation + heading)
    collected = [lines[start]]
    for line in lines[start + 1 :]:
        stripped = line.lstrip()
        current_indent = len(line) - len(stripped)
        if stripped and current_indent <= indentation:
            break
        collected.append(line)
    return "\n".join(collected)


def test_workflow_triggers_only_review_main_and_manual_verification() -> None:
    text = workflow_text()
    trigger = indented_block(text, "on:", 0)

    assert re.search(r"(?m)^  pull_request:$", trigger)
    assert re.search(r"(?m)^  push:$", trigger)
    assert 'branches: ["main"]' in trigger
    assert re.search(r"(?m)^  workflow_dispatch:$", trigger)
    assert not any(
        forbidden in trigger
        for forbidden in ("pull_request_target", "repository_dispatch", "schedule:")
    )
    assert '"portfolio-site/p1/**"' in trigger
    assert '"projects/01-cited-rag/scripts/validate_pages_artifact.py"' in trigger


def test_workflow_uses_only_exact_official_action_pins() -> None:
    text = workflow_text()
    uses = re.findall(r"(?m)^\s+uses:\s+([^\s]+)$", text)

    assert set(uses) == {f"{name}@{sha}" for name, sha in ACTION_PINS.items()}
    assert all(re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", item) for item in uses)
    assert "${{ secrets." not in text
    assert "npm " not in text


def test_verify_job_has_read_only_source_and_exact_artifact() -> None:
    text = workflow_text()
    verify = indented_block(text, "verify:", 2)

    assert re.search(r"(?m)^    permissions:\n      contents: read$", verify)
    assert "pages: write" not in verify
    assert "id-token: write" not in verify
    assert "persist-credentials: false" in verify
    assert "export_portfolio_evidence.py --check" in verify
    assert "validate_pages_artifact.py" in verify
    assert re.search(r"(?m)^          path: portfolio-site/p1$", verify)
    assert re.search(r"(?m)^          retention-days: 1$", verify)


def test_deploy_job_is_main_only_and_minimally_privileged() -> None:
    text = workflow_text()
    deploy = indented_block(text, "deploy:", 2)

    assert "if: github.ref == 'refs/heads/main' && github.event_name != 'pull_request'" in deploy
    assert re.search(r"(?m)^    needs: verify$", deploy)
    assert re.search(
        r"(?m)^    permissions:\n      pages: write\n      id-token: write$",
        deploy,
    )
    assert "contents:" not in deploy
    assert re.search(r"(?m)^      name: github-pages$", deploy)
    assert "url: ${{ steps.deployment.outputs.page_url }}" in deploy
    assert "actions/checkout@" not in deploy


def test_top_level_and_existing_ci_permissions_remain_bounded() -> None:
    text = workflow_text()
    ci_text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert re.search(r"(?m)^permissions: \{\}$", text)
    assert re.search(r"(?m)^permissions:\n  contents: read$", ci_text)
    assert "pages: write" not in ci_text
    assert "id-token: write" not in ci_text
