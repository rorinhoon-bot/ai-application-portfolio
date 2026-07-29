from __future__ import annotations

import json
from pathlib import Path

import pytest

from cited_rag.adapters.html_parser import PythonDocsHtmlParser
from cited_rag.errors import DocumentParseError

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
HTML_ROOT = FIXTURE_ROOT / "html"
EXPECTED_ROOT = FIXTURE_ROOT / "expected"

VALID_FIXTURES = ("valid_sphinx_page", "valid_sphinx_page_313")
INVALID_FIXTURES = ("missing_main", "missing_title", "duplicate_anchor")


def load_html(name: str) -> str:
    return (HTML_ROOT / f"{name}.html").read_text(encoding="utf-8")


def load_expectation(name: str) -> dict[str, object]:
    return json.loads(
        (EXPECTED_ROOT / f"{name}.json").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("name", VALID_FIXTURES)
def test_parser_matches_fixed_cleaning_expectation(name: str) -> None:
    expected = load_expectation(name)

    parsed = PythonDocsHtmlParser().parse(load_html(name))

    assert parsed.page_title == expected["page_title"]
    assert parsed.html_canonical_url == expected["html_canonical_url"]
    assert parsed.model_dump(mode="json")["blocks"] == expected["blocks"]
    assert parsed.warnings == ()


@pytest.mark.parametrize("name", INVALID_FIXTURES)
def test_parser_returns_stable_document_parse_error(name: str) -> None:
    expected = load_expectation(name)

    with pytest.raises(DocumentParseError) as captured:
        PythonDocsHtmlParser().parse(load_html(name))

    assert captured.value.code == expected["expected_error_code"]
    assert expected["reason_contains"] in captured.value.reason


def test_parser_rejects_empty_html() -> None:
    with pytest.raises(DocumentParseError, match="HTML input is empty"):
        PythonDocsHtmlParser().parse("   ")
