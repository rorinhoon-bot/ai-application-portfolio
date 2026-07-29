from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest

from agent_research.demo_assets import (
    render_terminal_demo_svg,
    render_workflow_overview_svg,
)
from agent_research.demo_runner import run_offline_demo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = PROJECT_ROOT / "demo" / "assets"
TERMINAL_PATH = ASSET_ROOT / "offline-demo-terminal.svg"
WORKFLOW_PATH = ASSET_ROOT / "workflow-overview.svg"


def test_terminal_svg_is_generated_from_verified_demo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    run = run_offline_demo(PROJECT_ROOT)
    actual = render_terminal_demo_svg(run.bundle.to_text())

    assert TERMINAL_PATH.read_text(encoding="utf-8") == actual
    assert "missing-candidates" in actual
    assert "privacy-durable-selection" in actual
    assert "missing-offline-proof" in actual
    assert "network=false · model_api=false" in actual


def test_workflow_svg_matches_deterministic_renderer() -> None:
    actual = render_workflow_overview_svg()

    assert WORKFLOW_PATH.read_text(encoding="utf-8") == actual
    assert 'data-node="requirements-human-gate"' in actual
    assert 'data-node="report-human-gate"' in actual
    assert "最多重试 2 次" in actual
    assert "最多检索 2 轮" in actual
    assert "自动修改最多 2 次" in actual
    assert "不覆盖；重复导出 UNCHANGED" in actual


@pytest.mark.parametrize("path", [TERMINAL_PATH, WORKFLOW_PATH])
def test_demo_svg_is_accessible_and_well_formed(path: Path) -> None:
    root = ElementTree.fromstring(path.read_text(encoding="utf-8"))

    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["role"] == "img"
    assert root.attrib["aria-labelledby"]
    assert root.find("{http://www.w3.org/2000/svg}title") is not None
    assert root.find("{http://www.w3.org/2000/svg}desc") is not None


def test_demo_assets_exclude_sensitive_and_runtime_values() -> None:
    content = (
        TERMINAL_PATH.read_text(encoding="utf-8")
        + WORKFLOW_PATH.read_text(encoding="utf-8")
    ).lower()

    forbidden = (
        "checkpoint.sqlite",
        "authorization:",
        "bearer ",
        "cookie:",
        "api_key",
        "vendor_sensitive_response",
        "p2-offline-demo-",
    )
    assert not any(value in content for value in forbidden)


def test_terminal_renderer_rejects_non_demo_transcript() -> None:
    with pytest.raises(ValueError, match="DEMO_TRANSCRIPT_LINE_COUNT_MISMATCH"):
        render_terminal_demo_svg("not a demo\n")
