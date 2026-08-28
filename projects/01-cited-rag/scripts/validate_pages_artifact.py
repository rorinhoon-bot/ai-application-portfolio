from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

try:
    from .export_portfolio_evidence import EvidenceExportError, export
except ImportError:  # Direct script execution puts this directory on sys.path.
    from export_portfolio_evidence import EvidenceExportError, export


VALIDATOR_VERSION = "p1-pages-artifact-validator-v1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SITE_ROOT = REPOSITORY_ROOT / "portfolio-site" / "p1"
READINESS_REPORT = PROJECT_ROOT / "data" / "pages-release-readiness-report.json"
ALLOWED_EXTENSIONS = frozenset({".html", ".md", ".json", ".js", ".css", ".png"})
TEXT_EXTENSIONS = frozenset({".html", ".md", ".json", ".js", ".css"})
MAXIMUM_FILE_COUNT = 32
MAXIMUM_TOTAL_BYTES = 1024 * 1024
MAXIMUM_SINGLE_FILE_BYTES = 256 * 1024

NETWORK_TOKENS = (
    "fetch(",
    "XMLHttpRequest",
    "WebSocket",
    "EventSource",
    "sendBeacon",
    "serviceWorker",
)
REMOTE_URL_RE = re.compile(r"(?i)^(?:https?:)?//")
REMOTE_CSS_RE = re.compile(r"(?i)(?:@import\s+|url\s*\(\s*['\"]?)(?:https?:)?//")
LOCAL_PATH_RE = re.compile(
    r"(?i)(?:[a-z]:\\(?:users|windows|programdata|temp)\\|/(?:users|home|var|tmp)/)"
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)['\"]?(?:api[_-]?key|secret|password|authorization|private[_-]?key)"
    r"['\"]?\s*[=:]\s*['\"][^'\"\r\n]+"
)


class PagesArtifactError(RuntimeError):
    pass


class _ArtifactHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.tags.append((tag.lower(), {key.lower(): value for key, value in attrs}))


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, separators=(",", ": ")) + "\n"
    ).encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _relative_path(path: Path, root: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PagesArtifactError("artifact path escaped its root") from exc
    if relative.is_absolute() or ".." in relative.parts:
        raise PagesArtifactError("artifact path escaped its root")
    return relative.as_posix()


def _inventory(site_root: Path) -> list[tuple[str, bytes]]:
    if site_root.is_symlink():
        raise PagesArtifactError("artifact root must not be a symlink")
    if not site_root.is_dir():
        raise PagesArtifactError("artifact root is missing or not a directory")

    root = site_root.resolve(strict=True)
    files: list[tuple[str, bytes]] = []
    for directory, names, filenames in os.walk(root, topdown=True, followlinks=False):
        directory_path = Path(directory)
        for name in sorted(names):
            candidate = directory_path / name
            relative = _relative_path(candidate, root)
            if name.startswith("."):
                raise PagesArtifactError(f"hidden path is forbidden: {relative}")
            if candidate.is_symlink():
                raise PagesArtifactError(f"symlink is forbidden: {relative}")
            if not candidate.is_dir():
                raise PagesArtifactError(f"non-directory path is forbidden: {relative}")

        for name in sorted(filenames):
            candidate = directory_path / name
            relative = _relative_path(candidate, root)
            if name.startswith("."):
                raise PagesArtifactError(f"hidden path is forbidden: {relative}")
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise PagesArtifactError(f"symlink is forbidden: {relative}")
            if not stat.S_ISREG(metadata.st_mode):
                raise PagesArtifactError(f"non-regular file is forbidden: {relative}")
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise PagesArtifactError(f"artifact path escaped its root: {relative}")
            if candidate.suffix.lower() not in ALLOWED_EXTENSIONS:
                raise PagesArtifactError(f"file extension is not allowed: {relative}")
            content = candidate.read_bytes()
            if len(content) > MAXIMUM_SINGLE_FILE_BYTES:
                raise PagesArtifactError(f"single-file size limit exceeded: {relative}")
            files.append((relative, content))

    files.sort(key=lambda item: item[0])
    if not any(relative == "index.html" for relative, _ in files):
        raise PagesArtifactError("artifact root index.html is required")
    if len(files) > MAXIMUM_FILE_COUNT:
        raise PagesArtifactError("artifact file-count limit exceeded")
    if sum(len(content) for _, content in files) > MAXIMUM_TOTAL_BYTES:
        raise PagesArtifactError("artifact total-size limit exceeded")
    return files


def _validate_html(relative: str, text: str) -> None:
    parser = _ArtifactHTMLParser()
    parser.feed(text)
    tags = parser.tags
    forbidden_tags = {"form", "iframe"}
    present_forbidden = sorted(forbidden_tags & {tag for tag, _ in tags})
    if present_forbidden:
        raise PagesArtifactError(
            f"interactive or framed HTML is forbidden in {relative}: {present_forbidden[0]}"
        )

    subresources = {
        "script": "src",
        "img": "src",
        "link": "href",
        "source": "src",
        "audio": "src",
        "video": "src",
        "object": "data",
    }
    for tag, attrs in tags:
        attribute = subresources.get(tag)
        target = attrs.get(attribute, "") if attribute else ""
        if target and REMOTE_URL_RE.match(target.strip()):
            raise PagesArtifactError(f"remote subresource is forbidden in {relative}")

    if relative == "index.html":
        csp_values = [
            attrs.get("content") or ""
            for tag, attrs in tags
            if tag == "meta"
            and (attrs.get("http-equiv") or "").lower() == "content-security-policy"
        ]
        if len(csp_values) != 1:
            raise PagesArtifactError("index.html must contain exactly one CSP meta policy")
        required = (
            "default-src 'none'",
            "connect-src 'none'",
            "form-action 'none'",
            "frame-src 'none'",
            "object-src 'none'",
        )
        if not all(directive in csp_values[0] for directive in required):
            raise PagesArtifactError("index.html CSP does not fail closed")


def _validate_text(relative: str, content: bytes) -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PagesArtifactError(f"text file is not UTF-8: {relative}") from exc

    if LOCAL_PATH_RE.search(text):
        raise PagesArtifactError(f"absolute local path is forbidden: {relative}")
    if SECRET_ASSIGNMENT_RE.search(text):
        raise PagesArtifactError(f"secret-like assignment is forbidden: {relative}")
    if relative.endswith(".html"):
        _validate_html(relative, text)
    if relative.endswith(".css") and REMOTE_CSS_RE.search(text):
        raise PagesArtifactError(f"remote CSS resource is forbidden: {relative}")
    if relative.endswith(".js") and any(token in text for token in NETWORK_TOKENS):
        raise PagesArtifactError(f"runtime network API is forbidden: {relative}")


def validate_artifact(
    site_root: Path = SITE_ROOT,
    *,
    check_evidence: bool = True,
) -> dict[str, Any]:
    if check_evidence:
        try:
            export(check=True)
        except EvidenceExportError as exc:
            raise PagesArtifactError(f"deterministic evidence is stale: {exc}") from exc

    files = _inventory(site_root)
    for relative, content in files:
        if Path(relative).suffix.lower() in TEXT_EXTENSIONS:
            _validate_text(relative, content)

    total_bytes = sum(len(content) for _, content in files)
    artifact_root = (
        "portfolio-site/p1"
        if site_root.resolve() == SITE_ROOT.resolve()
        else site_root.name
    )
    return {
        "schema_version": "1",
        "manifest_id": "p1-pages-artifact-readiness-v1",
        "validator_version": VALIDATOR_VERSION,
        "status": "local-verified",
        "artifact_root": artifact_root,
        "entrypoint": "index.html",
        "files": [
            {
                "path": relative,
                "byte_count": len(content),
                "sha256": _sha256(content),
            }
            for relative, content in files
        ],
        "totals": {
            "file_count": len(files),
            "byte_count": total_bytes,
        },
        "limits": {
            "maximum_file_count": MAXIMUM_FILE_COUNT,
            "maximum_total_bytes": MAXIMUM_TOTAL_BYTES,
            "maximum_single_file_bytes": MAXIMUM_SINGLE_FILE_BYTES,
            "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
        },
        "security": {
            "symlinks": False,
            "hidden_files": False,
            "remote_subresources": False,
            "runtime_network_api": False,
            "forms": False,
            "iframes": False,
            "absolute_local_paths": False,
            "secret_like_assignments": False,
        },
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


def _write_report(path: Path, content: bytes) -> None:
    if path.exists():
        raise PagesArtifactError(f"report already exists; refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the exact offline P1 GitHub Pages artifact."
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write the fixed project-local readiness report if it does not exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = validate_artifact()
        content = _canonical_json_bytes(report)
        if args.write_report:
            _write_report(READINESS_REPORT, content)
        else:
            print(content.decode("utf-8"), end="")
    except PagesArtifactError as exc:
        print(f"PAGES_ARTIFACT_ERROR: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
