import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_INDEX_ID = "614f6c23-7c35-5832-8086-c29651d60866"
EXPECTED_BUILD_ID = "418359df-7c62-4345-9bfe-57459c251dd3"
EXPECTED_COLLECTION = "cited-rag-614f6c237c35-418359df7c62"
EXPECTED_VALIDATION = {
    "point_count": 1359,
    "payload_count": 1359,
    "unique_point_count": 1359,
    "self_query_top_score": 1.0,
    "version_filter_checked": True,
}


def load_report(name: str) -> dict[str, object]:
    return json.loads(
        (PROJECT_ROOT / "data" / name).read_text(encoding="utf-8")
    )


def test_server_build_report_pins_real_migration_evidence() -> None:
    report = load_report("server-index-build-report.json")

    assert report["status"] == "ready"
    assert report["model_network_mode"] == "offline"
    assert report["qdrant_transport"] == "loopback-http"
    assert report["qdrant_server_version"] == "1.19.0"
    assert report["qdrant_client_version"] == "1.18.0"
    assert report["model"]["dimension"] == 512
    assert report["chunking"]["chunk_count"] == 1359
    assert report["index_manifest"]["index_id"] == EXPECTED_INDEX_ID
    assert report["index_manifest"]["build_id"] == EXPECTED_BUILD_ID
    assert report["index_manifest"]["collection_name"] == EXPECTED_COLLECTION
    assert report["validation"] == EXPECTED_VALIDATION
    assert report["embedded_count"] == 1359


def test_permission_report_proves_read_and_write_roles() -> None:
    report = load_report("qdrant-permission-report.json")

    assert report["status"] == "passed"
    assert report["collection_name"] == EXPECTED_COLLECTION
    assert report["point_count"] == 1359
    assert report["read_only_access"] == {
        "count_status": 200,
        "scroll_status": 200,
        "query_status": 200,
        "self_query_top_score": 1.0,
    }
    assert report["write_denial"] == {
        "expected_status": 403,
        "create_collection": 403,
        "upsert_point": 403,
        "delete_collection": 403,
    }
    assert report["probe_collection_absent"] is True
    assert report["secrets_recorded"] is False
    assert "api_key" not in json.dumps(report).lower()


def test_persistence_report_preserves_identity_without_rebuild() -> None:
    report = load_report("qdrant-persistence-report.json")

    assert report["status"] == "passed"
    assert report["compose_down_used_volume_removal"] is False
    assert report["named_volumes_preserved"] == [
        "cited-rag-qdrant_qdrant_storage",
        "cited-rag-qdrant_qdrant_snapshots",
    ]
    phases = report["phases"]
    assert [phase["phase"] for phase in phases] == [
        "before_restart",
        "after_restart",
        "after_down_up",
    ]
    for phase in phases:
        assert phase["index_id"] == EXPECTED_INDEX_ID
        assert phase["build_id"] == EXPECTED_BUILD_ID
        assert phase["collection_name"] == EXPECTED_COLLECTION
        assert phase["embedded_count"] == 0
        assert phase["validation"] == EXPECTED_VALIDATION


def test_recovery_report_proves_snapshot_and_cleanup() -> None:
    report = load_report("qdrant-recovery-report.json")

    assert report["status"] == "passed"
    assert report["active_collection"] == EXPECTED_COLLECTION
    assert report["active_index_id"] == EXPECTED_INDEX_ID
    assert report["active_build_id"] == EXPECTED_BUILD_ID
    snapshot = report["snapshot"]
    assert snapshot["server_reported_bytes"] == 9_922_560
    assert snapshot["downloaded_bytes"] == 9_922_560
    assert snapshot["sha256"] == (
        "6f447e48ca32a7e60de2a5a1a01d5104"
        "881452c1c01ecca7067d1fa98ed36732"
    )
    assert snapshot["qdrant_checksum_matched"] is True
    assert len(snapshot["manifest_backup_sha256"]) == 64
    recovery = report["recovery"]
    assert recovery["temporary_collection"].startswith("cited-rag-recovery-")
    assert recovery["temporary_collection"] != EXPECTED_COLLECTION
    assert recovery["upload_only"] is True
    assert recovery["validation"] == EXPECTED_VALIDATION
    assert recovery["temporary_collection_deleted"] is True
    assert report["active_collection_validation_after_cleanup"] == (
        EXPECTED_VALIDATION
    )
    assert report["secrets_recorded"] is False
