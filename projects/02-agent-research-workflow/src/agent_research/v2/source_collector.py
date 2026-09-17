"""Allowlisted, bounded source collector for the future D2 live step.

The collector is deliberately separate from ``SourceStore``. Tests inject an
HTTP opener; production callers must pass an explicitly frozen plan and invoke
this module only after the external download approval gate.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, ContextManager

from agent_research.v2.contracts import SourceEntryV2, SourceSnapshotV2, canonical_json


class SourceCollectionError(ValueError):
    """Stable error for unsafe plans or failed bounded downloads."""


@dataclass(frozen=True)
class SourcePlanItem:
    source_id: str
    candidate_id: str | None
    title: str
    canonical_url: str
    version: str
    accessed_at: str
    license_id: str
    relative_path: str
    license_url: str | None = None


@dataclass(frozen=True)
class FetchPolicy:
    allowed_urls: frozenset[str]
    allowed_hosts: frozenset[str]
    max_file_bytes: int = 5 * 1024 * 1024
    max_total_bytes: int = 5 * 1024 * 1024
    allow_local_proxy: bool = False


@dataclass(frozen=True)
class SourcePlanDocument:
    """Machine-readable plan loaded before any source download."""

    plan_id: str
    status: str
    max_pages: int
    items: tuple[SourcePlanItem, ...]
    policy: FetchPolicy


OpenUrl = Callable[[urllib.request.Request], ContextManager[object]]


def collect_snapshot(
    *,
    plan: tuple[SourcePlanItem, ...],
    policy: FetchPolicy,
    output_root: Path,
    open_url: OpenUrl | None = None,
) -> SourceSnapshotV2:
    """Fetch exactly a frozen plan and atomically write immutable raw files."""

    if not plan:
        raise SourceCollectionError("SOURCE_PLAN_EMPTY")
    _validate_policy(policy)
    root = _safe_root(output_root)
    if len({item.source_id for item in plan}) != len(plan):
        raise SourceCollectionError("SOURCE_PLAN_DUPLICATE_ID")
    if len({item.relative_path for item in plan}) != len(plan):
        raise SourceCollectionError("SOURCE_PLAN_DUPLICATE_PATH")
    opener = open_url or (
        lambda request: _default_open_url(request, allow_local_proxy=policy.allow_local_proxy)
    )
    for item in plan:
        _validate_item(item, policy)
    fetched: list[tuple[SourcePlanItem, bytes, bytes]] = []
    entries: list[SourceEntryV2] = []
    total = 0
    for item in plan:
        raw = fetch_bytes(item.canonical_url, policy=policy, open_url=opener)
        total += len(raw)
        if total > policy.max_total_bytes:
            raise SourceCollectionError("SOURCE_TOTAL_SIZE_LIMIT")
        normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        try:
            normalized.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceCollectionError("SOURCE_UTF8_INVALID") from exc
        fetched.append((item, raw, normalized))
        entries.append(
            SourceEntryV2(
                source_id=item.source_id,
                candidate_id=item.candidate_id,
                title=item.title,
                canonical_url=item.canonical_url,
                version=item.version,
                accessed_at=item.accessed_at,
                license_id=item.license_id,
                license_url=item.license_url,
                relative_path=item.relative_path,
                raw_sha256=hashlib.sha256(raw).hexdigest(),
                normalized_sha256=hashlib.sha256(normalized).hexdigest(),
                size_bytes=len(raw),
            )
        )
    for item, raw, _ in fetched:
        target = _safe_target(root, item.relative_path)
        _atomic_create(target, raw)
    return SourceSnapshotV2(
        snapshot_id="snapshot-" + hashlib.sha256(
            canonical_json([entry.model_dump(mode="json") for entry in entries]).encode("utf-8")
        ).hexdigest()[:24],
        entries=tuple(entries),
        total_size_bytes=total,
    )


def load_source_plan(path: Path, *, require_frozen: bool = False) -> SourcePlanDocument:
    """Load and validate a versioned source plan without making network calls."""

    if not path.is_absolute() or ".." in path.parts:
        raise SourceCollectionError("SOURCE_PLAN_PATH_UNSAFE")
    if not path.exists() or not path.is_file() or path.is_symlink() or _is_reparse(path):
        raise SourceCollectionError("SOURCE_PLAN_FILE_INVALID")
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise SourceCollectionError("SOURCE_PLAN_JSON_INVALID") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "source-plan-v1":
        raise SourceCollectionError("SOURCE_PLAN_SCHEMA_UNSUPPORTED")
    status = payload.get("status")
    if status not in {"proposed-awaiting-freeze", "frozen"}:
        raise SourceCollectionError("SOURCE_PLAN_STATUS_INVALID")
    if require_frozen and status != "frozen":
        raise SourceCollectionError("SOURCE_PLAN_NOT_FROZEN")
    plan_id = payload.get("plan_id")
    if not isinstance(plan_id, str) or not 3 <= len(plan_id) <= 100:
        raise SourceCollectionError("SOURCE_PLAN_ID_INVALID")
    max_pages = payload.get("max_pages")
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 12:
        raise SourceCollectionError("SOURCE_PLAN_PAGE_LIMIT_INVALID")
    allowed_urls = payload.get("allowed_urls")
    allowed_hosts = payload.get("allowed_hosts")
    if not (
        isinstance(allowed_urls, list)
        and all(isinstance(item, str) for item in allowed_urls)
        and isinstance(allowed_hosts, list)
        and all(isinstance(item, str) for item in allowed_hosts)
    ):
        raise SourceCollectionError("SOURCE_PLAN_ALLOWLIST_INVALID")
    try:
        policy = FetchPolicy(
            allowed_urls=frozenset(allowed_urls),
            allowed_hosts=frozenset(allowed_hosts),
            max_file_bytes=payload.get("max_file_bytes", 5 * 1024 * 1024),
            max_total_bytes=payload.get("max_total_bytes", 5 * 1024 * 1024),
        )
        _validate_policy(policy)
    except (TypeError, ValueError) as exc:
        raise SourceCollectionError("SOURCE_PLAN_POLICY_INVALID") from exc
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > max_pages:
        raise SourceCollectionError("SOURCE_PLAN_PAGE_COUNT_INVALID")
    items: list[SourcePlanItem] = []
    required = {
        "source_id",
        "candidate_id",
        "title",
        "canonical_url",
        "version",
        "accessed_at",
        "license_id",
        "license_url",
        "relative_path",
    }
    for raw_item in raw_items:
        if not isinstance(raw_item, dict) or set(raw_item) != required:
            raise SourceCollectionError("SOURCE_PLAN_ITEM_INVALID")
        try:
            item = SourcePlanItem(**raw_item)
        except TypeError as exc:
            raise SourceCollectionError("SOURCE_PLAN_ITEM_INVALID") from exc
        _validate_item(item, policy)
        items.append(item)
    if len({item.source_id for item in items}) != len(items):
        raise SourceCollectionError("SOURCE_PLAN_DUPLICATE_ID")
    if len({item.relative_path for item in items}) != len(items):
        raise SourceCollectionError("SOURCE_PLAN_DUPLICATE_PATH")
    return SourcePlanDocument(
        plan_id=plan_id,
        status=status,
        max_pages=max_pages,
        items=tuple(items),
        policy=policy,
    )


def write_snapshot_manifest(snapshot: SourceSnapshotV2, path: Path) -> None:
    """Atomically create a manifest; an existing different manifest is an error."""

    if not path.is_absolute() or ".." in path.parts:
        raise SourceCollectionError("SOURCE_MANIFEST_PATH_UNSAFE")
    if not path.parent.exists() or not path.parent.is_dir():
        raise SourceCollectionError("SOURCE_MANIFEST_PARENT_REQUIRED")
    if path.exists() and (path.is_symlink() or _is_reparse(path)):
        raise SourceCollectionError("SOURCE_MANIFEST_REPARSE_POINT")
    payload = (snapshot.model_dump_json(indent=2) + "\n").encode("utf-8")
    _atomic_create(path, payload)


def fetch_bytes(
    url: str,
    *,
    policy: FetchPolicy,
    open_url: OpenUrl | None = None,
) -> bytes:
    """Fetch one URL with exact URL/host checks and a hard byte limit."""

    if url not in policy.allowed_urls:
        raise SourceCollectionError("SOURCE_URL_NOT_ALLOWLISTED")
    _validate_url(url, policy)
    opener = open_url or (
        lambda request: _default_open_url(request, allow_local_proxy=policy.allow_local_proxy)
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "p2-agent-research-workflow/2-source-collector"},
        method="GET",
    )
    try:
        with opener(request) as response:
            final_url = getattr(response, "geturl", lambda: url)()
            if final_url != url:
                raise SourceCollectionError("SOURCE_REDIRECT_REJECTED")
            read = getattr(response, "read", None)
            if not callable(read):
                raise SourceCollectionError("SOURCE_RESPONSE_INVALID")
            raw = read(policy.max_file_bytes + 1)
    except SourceCollectionError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceCollectionError("SOURCE_DOWNLOAD_FAILED") from exc
    if not isinstance(raw, bytes):
        raise SourceCollectionError("SOURCE_RESPONSE_INVALID")
    if len(raw) > policy.max_file_bytes:
        raise SourceCollectionError("SOURCE_FILE_SIZE_LIMIT")
    return raw


def _validate_policy(policy: FetchPolicy) -> None:
    if not policy.allowed_urls or not policy.allowed_hosts:
        raise SourceCollectionError("SOURCE_POLICY_EMPTY")
    if not 1 <= policy.max_file_bytes <= 5 * 1024 * 1024:
        raise SourceCollectionError("SOURCE_FILE_LIMIT_INVALID")
    if not 1 <= policy.max_total_bytes <= 5 * 1024 * 1024:
        raise SourceCollectionError("SOURCE_TOTAL_LIMIT_INVALID")


def _validate_item(item: SourcePlanItem, policy: FetchPolicy) -> None:
    if item.canonical_url not in policy.allowed_urls:
        raise SourceCollectionError("SOURCE_URL_NOT_ALLOWLISTED")
    _validate_url(item.canonical_url, policy)
    try:
        SourceEntryV2(
            source_id=item.source_id,
            candidate_id=item.candidate_id,
            title=item.title,
            canonical_url=item.canonical_url,
            version=item.version,
            accessed_at=item.accessed_at,
            license_id=item.license_id,
            relative_path=item.relative_path,
            raw_sha256="0" * 64,
            normalized_sha256="0" * 64,
            size_bytes=1,
        )
    except ValueError as exc:
        raise SourceCollectionError("SOURCE_PLAN_ITEM_INVALID") from exc


def _validate_url(url: str, policy: FetchPolicy) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.hostname not in policy.allowed_hosts
        or parsed.port not in (None, 443)
        or not parsed.path.startswith("/")
    ):
        raise SourceCollectionError("SOURCE_URL_UNSAFE")


def _safe_root(root: Path) -> Path:
    if not root.is_absolute() or ".." in root.parts:
        raise SourceCollectionError("SOURCE_ROOT_UNSAFE")
    if not root.parent.exists() or not root.parent.is_dir():
        raise SourceCollectionError("SOURCE_ROOT_PARENT_REQUIRED")
    root.mkdir(exist_ok=True)
    if root.is_symlink() or _is_reparse(root):
        raise SourceCollectionError("SOURCE_ROOT_REPARSE_POINT")
    return root


def _safe_target(root: Path, relative_path: str) -> Path:
    lexical = PurePosixPath(relative_path)
    if (
        lexical.is_absolute()
        or ".." in lexical.parts
        or "." in lexical.parts
        or "\\" in relative_path
    ):
        raise SourceCollectionError("SOURCE_PATH_UNSAFE")
    target = root.joinpath(*lexical.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    current = root
    for part in lexical.parts:
        current = current / part
        if current.exists() and (current.is_symlink() or _is_reparse(current)):
            raise SourceCollectionError("SOURCE_REPARSE_POINT")
    if target.exists() and not target.is_file():
        raise SourceCollectionError("SOURCE_TARGET_NOT_FILE")
    return target


def _atomic_create(target: Path, raw: bytes) -> None:
    if target.exists():
        if target.read_bytes() != raw:
            raise SourceCollectionError("SOURCE_TARGET_CONFLICT")
        return
    descriptor, temp_name = tempfile.mkstemp(prefix=".source-", suffix=".tmp", dir=target.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_bytes() != raw:
                raise SourceCollectionError("SOURCE_TARGET_CONFLICT")
        except OSError as exc:
            raise SourceCollectionError("SOURCE_ATOMIC_PUBLISH_FAILED") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _default_open_url(
    request: urllib.request.Request,
    *,
    allow_local_proxy: bool = False,
) -> ContextManager[object]:
    host = urllib.parse.urlsplit(request.full_url).hostname
    if not host:
        raise SourceCollectionError("SOURCE_URL_UNSAFE")
    if allow_local_proxy and _has_safe_local_proxy():
        return urllib.request.urlopen(request, timeout=60.0)
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SourceCollectionError("SOURCE_DNS_FAILED") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
            raise SourceCollectionError("SOURCE_PRIVATE_TARGET")
    return urllib.request.urlopen(request, timeout=60.0)


def _is_reparse(path: Path) -> bool:
    return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def _has_safe_local_proxy() -> bool:
    """Return true only for an explicitly local, credential-free proxy."""

    proxies = urllib.request.getproxies()
    proxy_url = proxies.get("https") or proxies.get("http")
    if not proxy_url:
        return False
    parsed = urllib.parse.urlsplit(proxy_url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.username is None
        and parsed.password is None
        and parsed.port is not None
    )
