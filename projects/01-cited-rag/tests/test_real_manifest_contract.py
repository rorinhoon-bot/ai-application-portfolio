from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from cited_rag.models import SourceManifest

SOURCE_ROOT = Path(__file__).parents[1] / "data" / "sources"


def read_json(name: str) -> dict[str, object]:
    return json.loads(
        (SOURCE_ROOT / name).read_text(encoding="utf-8")
    )


def test_real_manifest_has_approved_release_counts() -> None:
    manifest = SourceManifest.model_validate_json(
        (SOURCE_ROOT / "manifest.json").read_text(encoding="utf-8")
    )

    releases = [
        source.documentation_release
        for source in manifest.sources
    ]
    assert len(releases) == 25
    assert releases.count("3.14.6") == 22
    assert releases.count("3.13.14") == 3


def test_source_catalog_is_an_exact_docs_python_org_allowlist() -> None:
    catalog = read_json("source-catalog.json")
    sources = catalog["sources"]
    urls = [source["source_url"] for source in sources]
    paths = [source["relative_path"] for source in sources]

    assert len(urls) == 25
    assert len(set(urls)) == 25
    assert len(set(paths)) == 25
    assert all(
        urlsplit(url).scheme == "https"
        and urlsplit(url).hostname == "docs.python.org"
        and not urlsplit(url).query
        and not urlsplit(url).fragment
        for url in urls
    )


def test_manifest_matches_acquisition_report() -> None:
    manifest = SourceManifest.model_validate_json(
        (SOURCE_ROOT / "manifest.json").read_text(encoding="utf-8")
    )
    report = read_json("acquisition-report.json")
    corpus_records = {
        record["source_id"]: record
        for record in report["records"]
        if record["kind"] == "corpus"
    }

    assert report["record_count"] == 26
    assert len(corpus_records) == 25
    for source in manifest.sources:
        record = corpus_records[source.source_id]
        assert record["source_url"] == str(source.source_url)
        assert record["relative_path"] == source.relative_path
        assert record["observed_h1"] == source.expected_title
        assert record["raw_sha256"] == source.raw_sha256
