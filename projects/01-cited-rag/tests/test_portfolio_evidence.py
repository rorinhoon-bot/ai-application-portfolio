from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from scripts import export_portfolio_evidence as exporter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
SITE_ROOT = REPOSITORY_ROOT / "portfolio-site" / "p1"


class SiteHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.tags.append((tag, dict(attrs)))


def load_evidence() -> dict[str, object]:
    return json.loads((SITE_ROOT / "assets/evidence.json").read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_evidence_export_is_current() -> None:
    assert exporter.export(check=True) is None


def test_json_source_hashes_are_newline_stable() -> None:
    lf = b'{\n  "status": "passed"\n}\n'
    crlf = lf.replace(b"\n", b"\r\n")

    assert exporter.normalized_source_bytes("data/report.json", lf) == lf
    assert exporter.normalized_source_bytes("data/report.json", crlf) == lf
    assert exporter.normalized_source_bytes("docs/image.png", crlf) == crlf


def test_retrieval_comparison_uses_one_fixed_evaluation_set() -> None:
    evidence = load_evidence()
    rows = evidence["retrieval_comparison"]

    assert [row["recall_at_5"] for row in rows] == [0.75, 0.8, 0.95]
    assert [row["mrr_at_5"] for row in rows] == [
        0.48666666666666664,
        0.6125,
        0.71,
    ]
    assert {row["evaluation_set_sha256"] for row in rows} == {
        rows[0]["evaluation_set_sha256"]
    }
    assert {row["case_count"] for row in rows} == {20}
    assert rows[-1]["candidate_recall_at_20"] == 1.0
    assert rows[-1]["external_api_calls"] == 0


def test_answer_metrics_and_recorded_cases_are_honestly_labeled() -> None:
    evidence = load_evidence()
    quality = evidence["answer_quality"]
    cases = evidence["recorded_cases"]

    assert quality["case_count"] == 10
    assert quality["answerable_recall"] == 0.8
    assert quality["refusal_accuracy"] == 1.0
    assert quality["citation_binding_validity"] == 1.0
    assert quality["manual_faithfulness"] == "4/4"
    assert {case["kind"] for case in cases} == {
        "answered",
        "refused",
        "version-comparison",
    }
    assert all(case["recorded_evidence"] is True for case in cases)
    assert all(case["live_inference"] is False for case in cases)


def test_post_hoc_review_does_not_rewrite_original_automatic_result() -> None:
    comparison = load_evidence()["recorded_cases"][2]
    review = comparison["review"]

    assert review["kind"] == "post-hoc-human-review"
    assert review["accepted"] is True
    assert review["original_automatic_correct"] is False
    assert review["original_expected_status"] == "conflict"


def test_manifest_hashes_every_fixed_input_and_generated_output() -> None:
    manifest = json.loads(
        (SITE_ROOT / "evidence-manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["exporter_version"] == exporter.EXPORTER_VERSION
    assert len(manifest["inputs"]) == len(exporter.SOURCE_REPORTS) + len(
        exporter.SOURCE_IMAGES
    )
    for item in manifest["inputs"]:
        source = REPOSITORY_ROOT / item["path"]
        assert source.is_file()
        content = exporter.normalized_source_bytes(item["path"], source.read_bytes())
        assert item["byte_count"] == len(content)
        assert item["sha256"] == hashlib.sha256(content).hexdigest()
    for item in manifest["outputs"]:
        output = REPOSITORY_ROOT / item["path"]
        assert output.is_file()
        assert item["byte_count"] == output.stat().st_size
        assert item["sha256"] == sha256(output)


def test_export_records_published_static_boundary() -> None:
    evidence = load_evidence()

    assert evidence["site_status"] == "public-static-artifact"
    assert evidence["publication_status"] == "published-and-verified"
    assert evidence["remote_ci_status"] == "passed"
    assert evidence["public_url"] == (
        "https://rorinhoon-bot.github.io/ai-application-portfolio/"
    )
    assert evidence["live_service"] is False
    assert set(evidence["external_side_effects"].values()) == {False}


def test_publication_proof_is_bound_to_tracked_release_report() -> None:
    evidence = load_evidence()
    proof = evidence["publication_proof"]

    assert proof["merge_commit"] == "0748abfa2f0ec579179ca8095513c0ac3462a2b1"
    assert proof["deployment_id"] == 6141599225
    assert proof["public_http_files_verified"] == 6
    assert proof["public_http_all_status_200"] is True
    assert proof["public_http_all_sha256_match"] is True
    assert len(proof["source_sha256"]) == 64


def test_html_has_static_security_and_accessibility_contracts() -> None:
    html = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
    parser = SiteHTMLParser()
    parser.feed(html)
    tags = parser.tags

    csp = next(
        attrs["content"]
        for tag, attrs in tags
        if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy"
    )
    assert "default-src 'none'" in csp
    assert "connect-src 'none'" in csp
    assert "form-action 'none'" in csp
    assert not {"form", "input", "textarea", "iframe"} & {tag for tag, _ in tags}
    assert any(tag == "main" and attrs.get("id") == "main" for tag, attrs in tags)
    assert any(tag == "h1" for tag, _ in tags)
    assert any(
        tag == "a" and attrs.get("class") == "skip-link" for tag, attrs in tags
    )
    for tag, attrs in tags:
        if tag == "a" and attrs.get("target") == "_blank":
            assert set((attrs.get("rel") or "").split()) >= {"noopener", "noreferrer"}
    assert "录制证据 · 非实时推理" in html
    assert "GitHub Pages 已公开发布" in html
    assert "<noscript>" in html


def test_static_assets_make_no_runtime_network_or_dynamic_html_calls() -> None:
    javascript = "\n".join(
        (SITE_ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in ("assets/app.js", "assets/evidence.js")
    )
    forbidden = (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "sendBeacon",
        "serviceWorker",
        ".innerHTML",
    )

    assert not any(token in javascript for token in forbidden)
    assert "textContent" in javascript


def test_site_has_no_remote_subresources_or_local_absolute_paths() -> None:
    html = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
    parser = SiteHTMLParser()
    parser.feed(html)
    for tag, attrs in parser.tags:
        if tag in {"script", "img", "link"}:
            target = attrs.get("src") or attrs.get("href") or ""
            assert not target.startswith(("http://", "https://", "//"))

    text_files = [
        SITE_ROOT / "index.html",
        SITE_ROOT / "README.md",
        SITE_ROOT / "evidence-manifest.json",
        *(SITE_ROOT / "assets").glob("*.js"),
        *(SITE_ROOT / "assets").glob("*.json"),
        *(SITE_ROOT / "assets").glob("*.css"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in text_files)
    assert "H:\\" not in combined
    assert "C:\\Users\\" not in combined
    assert not re.search(r"(?i)(api[_-]?key|secret|token)\s*[=:]\s*['\"][^'\"]+", combined)


def test_styles_and_tabs_include_small_screen_and_keyboard_contracts() -> None:
    html = (SITE_ROOT / "index.html").read_text(encoding="utf-8")
    css = (SITE_ROOT / "assets/styles.css").read_text(encoding="utf-8")
    javascript = (SITE_ROOT / "assets/app.js").read_text(encoding="utf-8")

    assert 'name="viewport"' in html
    assert "role=\"tablist\"" in html
    assert "@media (max-width: 380px)" in css
    assert ":focus-visible" in css
    assert all(key in javascript for key in ("ArrowLeft", "ArrowRight", "Home", "End"))
