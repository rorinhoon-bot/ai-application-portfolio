from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import validate_pages_artifact as validator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
SITE_ROOT = REPOSITORY_ROOT / "portfolio-site" / "p1"
READINESS_REPORT = PROJECT_ROOT / "data" / "pages-release-readiness-report.json"


MINIMAL_INDEX = """<!doctype html>
<html><head>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; connect-src 'none'; form-action 'none'; frame-src 'none'; object-src 'none'">
</head><body>recorded evidence</body></html>
"""


def make_site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(MINIMAL_INDEX, encoding="utf-8")
    return site


def test_current_artifact_has_deterministic_exact_manifest() -> None:
    first = validator.validate_artifact()
    second = validator.validate_artifact()

    assert first == second
    assert first["artifact_root"] == "portfolio-site/p1"
    assert first["totals"] == {"file_count": 9, "byte_count": 233880}
    paths = [item["path"] for item in first["files"]]
    assert paths == sorted(paths)
    assert paths[0] == "README.md"
    assert paths[-1] == "index.html"
    assert all(len(item["sha256"]) == 64 for item in first["files"])
    assert set(first["external_side_effects"].values()) == {False}
    assert json.loads(READINESS_REPORT.read_text(encoding="utf-8")) == first


def test_report_writer_refuses_overwrite(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text("preserve", encoding="utf-8")

    with pytest.raises(validator.PagesArtifactError, match="refusing overwrite"):
        validator._write_report(report, b"replacement")
    assert report.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize(
    ("relative_path", "content", "message"),
    [
        (".hidden.json", "{}", "hidden path"),
        ("payload.exe", "not executable", "extension is not allowed"),
        ("assets/net.js", "fetch('/api')", "runtime network API"),
        ("assets/remote.css", "@import url(https://example.test/a.css);", "remote CSS"),
        ("local.md", "C:\\Users\\person\\secret.txt", "absolute local path"),
        ("secret.json", '{"api_key": "not-a-real-key"}', "secret-like assignment"),
    ],
)
def test_validator_rejects_forbidden_files_and_text(
    tmp_path: Path,
    relative_path: str,
    content: str,
    message: str,
) -> None:
    site = make_site(tmp_path)
    target = site / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    with pytest.raises(validator.PagesArtifactError, match=message):
        validator.validate_artifact(site, check_evidence=False)


@pytest.mark.parametrize(
    ("markup", "message"),
    [
        ("<form></form>", "interactive or framed HTML"),
        ("<iframe></iframe>", "interactive or framed HTML"),
        ('<script src="https://example.test/app.js"></script>', "remote subresource"),
    ],
)
def test_validator_rejects_active_html(
    tmp_path: Path,
    markup: str,
    message: str,
) -> None:
    site = make_site(tmp_path)
    (site / "index.html").write_text(
        MINIMAL_INDEX.replace("</body>", f"{markup}</body>"),
        encoding="utf-8",
    )

    with pytest.raises(validator.PagesArtifactError, match=message):
        validator.validate_artifact(site, check_evidence=False)


def test_validator_requires_root_index_and_enforces_size_limits(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "README.md").write_text("only docs", encoding="utf-8")
    with pytest.raises(validator.PagesArtifactError, match="index.html is required"):
        validator.validate_artifact(site, check_evidence=False)

    (site / "index.html").write_text(MINIMAL_INDEX, encoding="utf-8")
    (site / "large.json").write_bytes(b"x" * (validator.MAXIMUM_SINGLE_FILE_BYTES + 1))
    with pytest.raises(validator.PagesArtifactError, match="single-file size limit"):
        validator.validate_artifact(site, check_evidence=False)


def test_validator_enforces_file_count_and_total_size_limits(tmp_path: Path) -> None:
    site = make_site(tmp_path)
    for index in range(validator.MAXIMUM_FILE_COUNT):
        (site / f"extra-{index:02}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(validator.PagesArtifactError, match="file-count limit"):
        validator.validate_artifact(site, check_evidence=False)

    for path in site.glob("extra-*.json"):
        path.unlink()
    for index in range(5):
        (site / f"large-{index}.json").write_bytes(b"x" * 220_000)
    with pytest.raises(validator.PagesArtifactError, match="total-size limit"):
        validator.validate_artifact(site, check_evidence=False)


def test_validator_rejects_symlink_when_supported(tmp_path: Path) -> None:
    site = make_site(tmp_path)
    target = tmp_path / "outside.json"
    target.write_text("{}", encoding="utf-8")
    link = site / "linked.json"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symlink creation is not permitted on this Windows host")

    with pytest.raises(validator.PagesArtifactError, match="symlink is forbidden"):
        validator.validate_artifact(site, check_evidence=False)
