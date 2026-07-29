"""Fetch the explicitly approved Python documentation snapshot."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

from bs4 import BeautifulSoup

ALLOWED_HOST = "docs.python.org"
MAX_PAGE_BYTES = 10 * 1024 * 1024
USER_AGENT = "cited-rag-corpus-fetch/1.0"


class SameHostRedirectHandler(HTTPRedirectHandler):
    """Reject redirects that leave the approved HTTPS host."""

    def redirect_request(
        self,
        request,
        fp,
        code,
        msg,
        headers,
        new_url,
    ):
        parsed = urlparse(new_url)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise HTTPError(
                new_url,
                code,
                "redirect left approved docs.python.org HTTPS boundary",
                headers,
                fp,
            )
        return super().redirect_request(
            request,
            fp,
            code,
            msg,
            headers,
            new_url,
        )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != ALLOWED_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or not parsed.path.endswith(".html")
    ):
        raise ValueError(f"URL is outside the approved boundary: {url}")


def _safe_output_path(root: Path, relative_path: str) -> Path:
    parts = relative_path.split("/")
    if (
        not relative_path
        or "\\" in relative_path
        or any(part in {"", ".", ".."} for part in parts)
        or not relative_path.endswith(".html")
    ):
        raise ValueError(f"unsafe output path: {relative_path}")
    root = root.resolve()
    output = root.joinpath(*parts).resolve()
    if not output.is_relative_to(root):
        raise ValueError(f"output escaped root: {relative_path}")
    return output


def _extract_h1(raw_html: bytes) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    h1 = soup.find("h1")
    if h1 is None:
        raise ValueError("downloaded HTML has no h1")
    for permalink in h1.select(".headerlink"):
        permalink.decompose()
    title = " ".join(h1.get_text(" ", strip=True).split())
    if not title:
        raise ValueError("downloaded HTML has an empty h1")
    return title


def _fetch(opener, url: str) -> tuple[bytes, str, str]:
    _validate_url(url)
    request = Request(
        url,
        headers={
            "Accept": "text/html",
            "User-Agent": USER_AGENT,
        },
    )
    with opener.open(request, timeout=30) as response:
        final_url = response.geturl()
        _validate_url(final_url)
        content_type = response.headers.get_content_type()
        if content_type != "text/html":
            raise ValueError(
                f"unexpected Content-Type for {url}: {content_type}"
            )
        raw_html = response.read(MAX_PAGE_BYTES + 1)
    if len(raw_html) > MAX_PAGE_BYTES:
        raise ValueError(f"page exceeds {MAX_PAGE_BYTES} bytes: {url}")
    return raw_html, final_url, content_type


def fetch_catalog(*, catalog_path: Path, output_root: Path) -> dict[str, object]:
    catalog = _read_json(catalog_path)
    sources = catalog["sources"]
    license_evidence = catalog["license_evidence"]
    if not isinstance(sources, list) or not isinstance(license_evidence, dict):
        raise ValueError("catalog shape is invalid")

    jobs = [
        {
            "kind": "corpus",
            **source,
        }
        for source in sources
    ]
    jobs.append(
        {
            "kind": "license",
            "source_url": license_evidence["url"],
            "relative_path": license_evidence["relative_path"],
        }
    )

    if len(jobs) != 26:
        raise ValueError(f"approved catalog must contain 26 downloads, got {len(jobs)}")
    urls = [job["source_url"] for job in jobs]
    paths = [job["relative_path"] for job in jobs]
    if len(urls) != len(set(urls)) or len(paths) != len(set(paths)):
        raise ValueError("catalog contains a duplicate URL or output path")

    output_root.mkdir(parents=True, exist_ok=True)
    opener = build_opener(SameHostRedirectHandler())
    records: list[dict[str, object]] = []
    for job in jobs:
        output_path = _safe_output_path(output_root, job["relative_path"])
        if output_path.exists():
            raise FileExistsError(f"refusing to overwrite {job['relative_path']}")
        raw_html, final_url, content_type = _fetch(opener, job["source_url"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(raw_html)
        record = {
            **job,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "final_url": final_url,
            "media_type": content_type,
            "raw_sha256": sha256(raw_html).hexdigest(),
            "byte_count": len(raw_html),
            "observed_h1": _extract_h1(raw_html),
        }
        records.append(record)

    return {
        "schema_version": "1",
        "catalog_path": catalog_path.name,
        "record_count": len(records),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    if args.report.exists():
        raise FileExistsError(f"refusing to overwrite {args.report}")
    report = fetch_catalog(
        catalog_path=args.catalog,
        output_root=args.output_root,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
