"""D2 collector tests use mocked responses and never perform network I/O."""

from __future__ import annotations

import json
from pathlib import Path
import socket
from dataclasses import replace
import urllib.request

import pytest

from agent_research.v2.source_collector import (
    FetchPolicy,
    SourceCollectionError,
    SourcePlanItem,
    collect_snapshot,
    fetch_bytes,
    load_source_plan,
    write_snapshot_manifest,
)
from agent_research.v2.source_store import load_snapshot


URL = "https://docs.example.invalid/official/page.md"


class _Response:
    def __init__(self, payload: bytes, final_url: str = URL) -> None:
        self.payload = payload
        self.final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def geturl(self) -> str:
        return self.final_url

    def read(self, limit: int) -> bytes:
        return self.payload[:limit]


def _policy(*, max_file_bytes: int = 1024) -> FetchPolicy:
    return FetchPolicy(
        allowed_urls=frozenset({URL}),
        allowed_hosts=frozenset({"docs.example.invalid"}),
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_file_bytes,
    )


def _plan() -> tuple[SourcePlanItem, ...]:
    return (
        SourcePlanItem(
            source_id="official-page",
            candidate_id="langgraph",
            title="Official page",
            canonical_url=URL,
            version="2026-09-14",
            accessed_at="2026-09-14T00:00:00Z",
            license_id="verify-before-redistribution",
            relative_path="langgraph/page.md",
        ),
    )


def test_collect_snapshot_hashes_normalized_text_and_writes_once(tmp_path: Path) -> None:
    payload = b"## [state-model] State\r\n\r\nOfficial text.\r\n"

    def opener(request):
        assert request.full_url == URL
        return _Response(payload)

    snapshot = collect_snapshot(
        plan=_plan(),
        policy=_policy(),
        output_root=tmp_path / "snapshot",
        open_url=opener,
    )
    entry = snapshot.entries[0]
    assert entry.size_bytes == len(payload)
    assert entry.raw_sha256 != entry.normalized_sha256
    assert (tmp_path / "snapshot" / "langgraph" / "page.md").read_bytes() == payload
    assert snapshot.total_size_bytes == len(payload)
    manifest = tmp_path / "snapshot-manifest.json"
    write_snapshot_manifest(snapshot, manifest)
    loaded, _ = load_snapshot(tmp_path / "snapshot", manifest)
    assert loaded == snapshot

    # A repeated collection with identical bytes is safe and leaves one file.
    collect_snapshot(
        plan=_plan(),
        policy=_policy(),
        output_root=tmp_path / "snapshot",
        open_url=opener,
    )
    assert len(tuple((tmp_path / "snapshot").rglob("*.md"))) == 1


def test_fetch_rejects_redirect_and_oversized_response() -> None:
    with pytest.raises(SourceCollectionError, match="REDIRECT_REJECTED"):
        fetch_bytes(
            URL,
            policy=_policy(),
            open_url=lambda request: _Response(b"ok", "https://other.invalid/page.md"),
        )
    with pytest.raises(SourceCollectionError, match="FILE_SIZE_LIMIT"):
        fetch_bytes(
            URL,
            policy=_policy(max_file_bytes=3),
            open_url=lambda request: _Response(b"four"),
        )


def test_collector_rejects_unallowlisted_or_unsafe_url(tmp_path: Path) -> None:
    with pytest.raises(SourceCollectionError, match="URL_NOT_ALLOWLISTED"):
        fetch_bytes(
            "https://docs.example.invalid/other.md",
            policy=_policy(),
            open_url=lambda request: _Response(b"never"),
        )
    unsafe = _plan()[0].__class__(**{
        **_plan()[0].__dict__,
        "canonical_url": "https://docs.example.invalid:8443/official/page.md",
    })
    with pytest.raises(SourceCollectionError, match="URL_NOT_ALLOWLISTED"):
        collect_snapshot(
            plan=(unsafe,),
            policy=_policy(),
            output_root=tmp_path / "snapshot",
            open_url=lambda request: _Response(b"never"),
        )


def test_machine_plan_is_offline_checkable_and_freeze_gate_is_enforced(tmp_path: Path) -> None:
    plan_path = Path(__file__).resolve().parents[1] / "docs" / "v2" / "source-plan-v1.json"
    plan = load_source_plan(plan_path)
    assert plan.status == "frozen"
    assert plan.plan_id == "p2-v2-source-plan-0.1"
    assert len(plan.items) == 6
    assert load_source_plan(plan_path, require_frozen=True).status == "frozen"
    proposed_path = tmp_path / "proposed.json"
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    payload["status"] = "proposed-awaiting-freeze"
    proposed_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SourceCollectionError, match="PLAN_NOT_FROZEN"):
        load_source_plan(proposed_path, require_frozen=True)


def test_default_opener_rejects_private_dns_target(monkeypatch: pytest.MonkeyPatch) -> None:
    def private_addresses(*args, **kwargs):
        del args, kwargs
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", private_addresses)
    with pytest.raises(SourceCollectionError, match="PRIVATE_TARGET"):
        fetch_bytes(URL, policy=_policy())


def test_failed_later_fetch_leaves_no_partial_files(tmp_path: Path) -> None:
    second = replace(_plan()[0], source_id="second-page", relative_path="other/page.md")
    responses = iter((_Response(b"valid"), _Response(b"\xffinvalid")))

    with pytest.raises(SourceCollectionError, match="UTF8_INVALID"):
        collect_snapshot(
            plan=(_plan()[0], second),
            policy=_policy(),
            output_root=tmp_path / "snapshot",
            open_url=lambda request: next(responses),
        )
    assert not (tmp_path / "snapshot" / "langgraph" / "page.md").exists()
    assert not (tmp_path / "snapshot" / "other" / "page.md").exists()


def test_local_proxy_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_research.v2 import source_collector

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

    called = {"urlopen": False}

    def urlopen(request, timeout):
        assert request.full_url == URL
        assert timeout == 60.0
        called["urlopen"] = True
        return Response()

    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"https": "http://127.0.0.1:7897"})
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with source_collector._default_open_url(
        urllib.request.Request(URL), allow_local_proxy=True
    ):
        pass
    assert called["urlopen"]
