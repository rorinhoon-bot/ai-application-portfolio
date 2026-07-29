from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from cited_rag.models import ContentBlockType

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
HTML_ROOT = FIXTURE_ROOT / "html"
EXPECTED_ROOT = FIXTURE_ROOT / "expected"

VALID_FIXTURES = ("valid_sphinx_page", "valid_sphinx_page_313")
INVALID_FIXTURES = ("missing_main", "missing_title", "duplicate_anchor")
ALL_FIXTURES = VALID_FIXTURES + INVALID_FIXTURES

EXPECTED_BLOCK_KEYS = {
    "block_order",
    "paragraph_order",
    "block_type",
    "raw_text",
    "clean_text",
    "section_path",
    "section_anchor",
    "block_anchor",
    "list_level",
}


def load_expectation(name: str) -> dict[str, object]:
    path = EXPECTED_ROOT / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def normalized_text_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_fixture_is_synthetic_and_hash_is_fixed(name: str) -> None:
    html_path = HTML_ROOT / f"{name}.html"
    expectation = load_expectation(name)
    html = html_path.read_text(encoding="utf-8")

    assert "synthetic test fixture" in html
    assert expectation["fixture_schema_version"] == "1"
    assert expectation["fixture_text_sha256"] == normalized_text_sha256(html_path)


@pytest.mark.parametrize("name", VALID_FIXTURES)
def test_valid_fixture_cleaning_expectation_is_complete(name: str) -> None:
    expectation = load_expectation(name)
    blocks = expectation["blocks"]

    assert isinstance(expectation["page_title"], str)
    assert isinstance(expectation["html_canonical_url"], str)
    assert isinstance(blocks, list)
    assert blocks
    assert [block["block_order"] for block in blocks] == list(
        range(1, len(blocks) + 1)
    )

    paragraph_orders = [
        block["paragraph_order"]
        for block in blocks
        if block["paragraph_order"] is not None
    ]
    assert paragraph_orders == list(range(1, len(paragraph_orders) + 1))

    supported_types = {block_type.value for block_type in ContentBlockType}
    for block in blocks:
        assert set(block) == EXPECTED_BLOCK_KEYS
        assert block["block_type"] in supported_types
        assert block["raw_text"].strip()
        assert block["clean_text"].strip()
        assert block["section_path"]
        assert block["section_anchor"]
        if block["block_type"] == ContentBlockType.CODE:
            assert block["raw_text"] == block["clean_text"]


@pytest.mark.parametrize("name", INVALID_FIXTURES)
def test_invalid_fixture_has_stable_parse_error(name: str) -> None:
    expectation = load_expectation(name)

    assert set(expectation) == {
        "fixture_schema_version",
        "fixture_text_sha256",
        "expected_error_code",
        "reason_contains",
    }
    assert expectation["expected_error_code"] == "DOCUMENT_PARSE_ERROR"
    assert expectation["reason_contains"]


def test_page_noise_is_absent_from_valid_expectations() -> None:
    serialized = json.dumps(
        load_expectation("valid_sphinx_page"),
        ensure_ascii=False,
    )

    for noise in (
        "样式噪声",
        "脚本噪声",
        "页眉噪声",
        "导航噪声",
        "查看源码",
        "复制",
        "页脚噪声",
    ):
        assert noise not in serialized
