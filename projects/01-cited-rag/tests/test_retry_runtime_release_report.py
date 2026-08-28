import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "data" / "retry-runtime-release-report.json"


def load_report() -> dict[str, object]:
    value = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_retry_runtime_candidate_is_isolated_and_hardened() -> None:
    report = load_report()
    candidate = report["candidate_image"]
    acceptance = report["isolated_acceptance"]

    assert report["status"] == "passed"
    assert candidate["tag"] == "cited-rag-api:v2-d3"
    assert candidate["container_user"] == "10001:10001"
    assert acceptance["read_only_rootfs"] is True
    assert acceptance["cap_drop"] == ["ALL"]
    assert acceptance["healthz"] == 200
    assert acceptance["readyz"] == 200
    assert acceptance["invalid_answer"] == 422
    assert acceptance["container_removed_after_acceptance"] is True


def test_retry_runtime_preserves_rollback_and_external_boundaries() -> None:
    report = load_report()
    baseline = report["rollback_baseline"]
    qdrant = report["qdrant_immutability"]

    assert baseline["tag"] == "cited-rag-api:v2-d1"
    assert baseline["identity_unchanged"] is True
    assert baseline["traffic_switched"] is False
    assert baseline["healthz_after_acceptance"] == 200
    assert baseline["readyz_after_acceptance"] == 200
    assert qdrant["identity_unchanged"] is True
    assert qdrant["active_pointer_sha256"] == (
        "5a905dc41cebc1a9b40d73ef19840629ebd490398a34bfd1639bdb9f0bd54e84"
    )
    assert qdrant["manifest_sha256"] == (
        "4c8f38c0547fa575a8bef783a4065679153b6c3f5ec5fa86645d83f78f193697"
    )
    assert not any(report["side_effects"].values())
    assert report["isolated_acceptance"]["mimo_calls"] == 0
