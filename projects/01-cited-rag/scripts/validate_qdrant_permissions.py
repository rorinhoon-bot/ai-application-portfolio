"""Prove that the runtime Qdrant credential cannot mutate collections."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib.parse import quote
from uuid import uuid4

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cited_rag.indexing import load_active_index  # noqa: E402
from cited_rag.qdrant_connection import (  # noqa: E402
    QdrantAdminSettings,
    QdrantReadSettings,
)

INDEX_ROOT = PROJECT_ROOT / "data" / "server-indexes"
REPORT_PATH = PROJECT_ROOT / "data" / "qdrant-permission-report.json"
READ_ENV = PROJECT_ROOT / ".env.qdrant-read"
ADMIN_ENV = PROJECT_ROOT / ".env.qdrant-admin"


def main(*, preserve_existing_report: bool = False) -> int:
    report_already_exists = _validate_report_target(REPORT_PATH)
    if report_already_exists and not preserve_existing_report:
        raise FileExistsError("Qdrant permission report already exists")

    _, manifest = load_active_index(index_root=INDEX_ROOT)
    read_settings = QdrantReadSettings(_env_file=READ_ENV)
    admin_settings = QdrantAdminSettings(_env_file=ADMIN_ENV)
    if read_settings.qdrant_profile != "server":
        raise RuntimeError("permission validation requires server profile")
    assert read_settings.qdrant_url is not None
    assert read_settings.qdrant_read_only_api_key is not None

    base_url = str(read_settings.qdrant_url).removesuffix("/")
    if base_url != str(admin_settings.qdrant_url).removesuffix("/"):
        raise RuntimeError("read and admin credentials target different servers")

    collection_path = quote(manifest.collection_name, safe="")
    probe_name = f"cited-rag-permission-probe-{uuid4().hex}"
    probe_path = quote(probe_name, safe="")
    read_headers = {
        "api-key": (
            read_settings.qdrant_read_only_api_key.get_secret_value()
        )
    }
    admin_headers = {
        "api-key": admin_settings.qdrant_admin_api_key.get_secret_value()
    }
    timeout = httpx.Timeout(read_settings.qdrant_timeout_seconds)
    cleanup_performed = False

    with (
        httpx.Client(
            base_url=base_url,
            headers=read_headers,
            timeout=timeout,
            trust_env=False,
        ) as read_client,
        httpx.Client(
            base_url=base_url,
            headers=admin_headers,
            timeout=timeout,
            trust_env=False,
        ) as admin_client,
    ):
        try:
            count_response = read_client.post(
                f"/collections/{collection_path}/points/count",
                json={"exact": True},
            )
            _require_status(count_response, expected=200, operation="count")
            count = _result_object(count_response)["count"]
            if count != manifest.point_count:
                raise RuntimeError(
                    f"count changed: expected {manifest.point_count}, got {count}"
                )

            scroll_response = read_client.post(
                f"/collections/{collection_path}/points/scroll",
                json={
                    "limit": 1,
                    "with_payload": True,
                    "with_vector": True,
                },
            )
            _require_status(scroll_response, expected=200, operation="scroll")
            points = _result_object(scroll_response)["points"]
            if len(points) != 1 or not points[0].get("payload"):
                raise RuntimeError("scroll did not return one payload-bearing point")
            source_point = points[0]
            vector = source_point.get("vector")
            if (
                not isinstance(vector, list)
                or len(vector)
                != manifest.specification.embedding_dimension
            ):
                raise RuntimeError("scroll vector dimension changed")

            query_response = read_client.post(
                f"/collections/{collection_path}/points/query",
                json={
                    "query": vector,
                    "limit": 1,
                    "with_payload": True,
                    "with_vector": False,
                },
            )
            _require_status(query_response, expected=200, operation="query")
            query_points = _result_object(query_response)["points"]
            if (
                len(query_points) != 1
                or query_points[0].get("id") != source_point.get("id")
                or float(query_points[0].get("score", 0.0)) < 0.999
            ):
                raise RuntimeError("read-only self-query validation failed")

            create_response = read_client.put(
                f"/collections/{probe_path}",
                json={
                    "vectors": {"size": 1, "distance": "Cosine"},
                },
            )
            upsert_response = read_client.put(
                f"/collections/{collection_path}/points",
                params={"wait": "true"},
                json={
                    "points": [
                        {
                            "id": source_point["id"],
                            "vector": vector,
                            "payload": source_point["payload"],
                        }
                    ]
                },
            )
            delete_response = read_client.delete(
                f"/collections/{probe_path}"
            )
            write_statuses = {
                "create_collection": create_response.status_code,
                "upsert_point": upsert_response.status_code,
                "delete_collection": delete_response.status_code,
            }
            denied = all(status == 403 for status in write_statuses.values())
        finally:
            probe_response = admin_client.get(
                f"/collections/{probe_path}"
            )
            if probe_response.status_code == 200:
                cleanup_response = admin_client.delete(
                    f"/collections/{probe_path}"
                )
                _require_status(
                    cleanup_response,
                    expected=200,
                    operation="probe cleanup",
                )
                cleanup_performed = True
            elif probe_response.status_code != 404:
                raise RuntimeError(
                    "could not prove permission probe collection is absent"
                )

    if cleanup_performed:
        raise RuntimeError("read-only key unexpectedly created a collection")
    if not denied:
        raise RuntimeError(
            f"read-only write denial changed: {write_statuses}"
        )

    report = {
        "schema_version": "1",
        "status": "passed",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "qdrant_transport": "loopback-http",
        "collection_name": manifest.collection_name,
        "point_count": count,
        "read_only_access": {
            "count_status": count_response.status_code,
            "scroll_status": scroll_response.status_code,
            "query_status": query_response.status_code,
            "self_query_top_score": query_points[0]["score"],
        },
        "write_denial": {
            "expected_status": 403,
            **write_statuses,
        },
        "probe_collection_absent": True,
        "secrets_recorded": False,
    }
    if not report_already_exists:
        with REPORT_PATH.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
            file.write("\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "point_count": count,
                "read_statuses": {
                    "count": count_response.status_code,
                    "scroll": scroll_response.status_code,
                    "query": query_response.status_code,
                },
                "write_statuses": write_statuses,
                "probe_collection_absent": True,
                (
                    "report_preserved"
                    if report_already_exists
                    else "report"
                ): str(REPORT_PATH),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _require_status(
    response: httpx.Response,
    *,
    expected: int,
    operation: str,
) -> None:
    if response.status_code != expected:
        raise RuntimeError(
            f"{operation} returned HTTP {response.status_code}, expected {expected}"
        )


def _result_object(response: httpx.Response) -> dict[str, object]:
    value = response.json().get("result")
    if not isinstance(value, dict):
        raise RuntimeError("Qdrant response has no result object")
    return value


def _validate_report_target(path: Path) -> bool:
    if path.is_symlink():
        raise RuntimeError("permission report must not be a symbolic link")
    if path.exists() and not path.is_file():
        raise RuntimeError("permission report must be a regular file")
    return path.exists()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Validate Qdrant read-only credential boundaries."
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="preserve an existing tracked historical permission report",
    )
    arguments = parser.parse_args()
    raise SystemExit(
        main(preserve_existing_report=arguments.restore)
    )
