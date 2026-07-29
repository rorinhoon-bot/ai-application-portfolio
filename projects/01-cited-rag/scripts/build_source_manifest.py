"""Build the strict source manifest from an approved catalog and fetch report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.models import SourceManifest  # noqa: E402


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_manifest(
    *,
    catalog_path: Path,
    report_path: Path,
) -> SourceManifest:
    catalog = _read_json(catalog_path)
    report = _read_json(report_path)
    catalog_sources = catalog["sources"]
    report_records = report["records"]
    license_url = catalog["license_evidence"]["url"]
    license_name = catalog["license_name"]

    if not isinstance(catalog_sources, list) or not isinstance(
        report_records,
        list,
    ):
        raise ValueError("catalog or report shape is invalid")

    corpus_records = {
        record["source_id"]: record
        for record in report_records
        if record["kind"] == "corpus"
    }
    if len(corpus_records) != len(catalog_sources):
        raise ValueError("report does not contain exactly one record per source")

    sources: list[dict[str, object]] = []
    for source in catalog_sources:
        source_id = source["source_id"]
        record = corpus_records.get(source_id)
        if record is None:
            raise ValueError(f"missing acquisition record: {source_id}")
        for field in (
            "document_key",
            "python_version",
            "documentation_release",
            "source_url",
            "relative_path",
        ):
            if record[field] != source[field]:
                raise ValueError(
                    f"catalog/report mismatch for {source_id}: {field}"
                )
        if record["final_url"] != source["source_url"]:
            raise ValueError(f"source URL redirected: {source_id}")

        sources.append(
            {
                "schema_version": "1",
                **source,
                "retrieved_at": record["retrieved_at"],
                "expected_title": record["observed_h1"],
                "license_name": license_name,
                "license_url": license_url,
                "raw_sha256": record["raw_sha256"],
                "media_type": record["media_type"],
                "language": "zh-CN",
            }
        )

    return SourceManifest.model_validate(
        {
            "schema_version": "1",
            "sources": sources,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    manifest = build_manifest(
        catalog_path=args.catalog,
        report_path=args.report,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
