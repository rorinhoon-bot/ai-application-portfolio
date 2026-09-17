"""Offline graduation integration: real P2 graph, P1 parser, P3 MCP reads."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import uuid

from common import (HERE, P1, P2, P3, BoundaryError, P1Response, Record, digest,
                    read_json, safe_directory, worker, write_once, publish_bytes)

os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"


def _offline(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "socket.bind"):
        raise RuntimeError("OFFLINE_NETWORK_BLOCKED")


sys.addaudithook(_offline)

sys.path.insert(0, str(P2 / "src"))
# Only P3's data contracts are shared here; its MCP SDK runs in its own interpreter.
sys.path.insert(0, str(P3 / "src"))
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from agent_research.v2.contracts import (BudgetAuthorization, CandidateSpec, DimensionSpec,
    EvidenceRecord, ResearchRequestV2, SourceEntryV2, SourceSnapshotV2)
from agent_research.v2.graph import build_v2_graph, create_initial_state, graph_config
from agent_research.v2.ledger import OperationLedger
from agent_research.v2.model_client import ScriptedModelClient
from agent_research.v2.exporter import V2Exporter
from agent_research.v2.source_store import SourceStoreError
from mcp_notes.v2.contracts import Result

QUESTION = "Compare graph-plan and chain-plan for an AI evidence research application with tool calling, human approval and recovery."
LIMITATIONS = [
    "Offline synthetic fixtures and scripted model; not a real model quality evaluation.",
    "P1 fixture-keyword adapter uses its HTML parser; BGE/Qdrant and HTTP/container behavior were not exercised.",
    "P2 real content acceptance failed: first batch 2 limited approvals and 4 rejections; later 2 limited approvals and 1 rejection.",
    "P2 permanent limit CNY 5; conservative occupancy 417/500 minor units and 109/109 calls. No new real calls are authorized.",
    "Assistant implemented this integration; independent student explanation and human content grading remain unverified.",
]


def p3_call(root, ids):
    return worker(P3, "p3_worker.py", {"note_ids": ids},
                  arguments=("--notes-root", root / "notes", "--audit-root", root / "mcp-audit"))


def validate_bridge(response, *, snapshot_hash=None):
    if set(response) != {"schema_version", "snapshot_hash", "results"} or response["schema_version"] != "p3-bridge-v1":
        raise BoundaryError("MCP_OUTPUT_INVALID")
    if not re.fullmatch(r"[a-f0-9]{64}", response["snapshot_hash"]):
        raise BoundaryError("MCP_OUTPUT_INVALID")
    if snapshot_hash and response["snapshot_hash"] != snapshot_hash:
        raise BoundaryError("MCP_SNAPSHOT_DRIFT")
    return [Result.model_validate(value) for value in response["results"]]


class IntegratedStore:
    def __init__(self, root, metadata):
        self.root = root
        self.metadata = metadata
        self.records = {r.record_id: r for r in (Record.model_validate(r) for r in metadata["catalog"]["records"])}
        self.snapshot = SourceSnapshotV2.model_validate(metadata["source_snapshot"])

    def search(self, *, query, request, top_k=6, candidate_ids=None):
        try:
            allowed = {c.candidate_id for c in request.candidates}
            candidates = candidate_ids or allowed
            if not candidates or not set(candidates) <= allowed:
                raise BoundaryError("CANDIDATE_OUTSIDE_SCOPE")
            p1 = P1Response.model_validate(worker(P1, "p1_worker.py", {
                "operation": "search", "query": query, "top_k": top_k, "candidate_ids": sorted(candidates)}))
            if p1.corpus_hash != self.metadata["catalog"]["corpus_hash"]:
                raise BoundaryError("P1_SNAPSHOT_DRIFT")
            for record in p1.records:
                if self.records.get(record.record_id) != record or record.candidate_id not in candidates:
                    raise BoundaryError("P1_EVIDENCE_DRIFT")
            if not p1.records:
                return ()
            bridge = p3_call(self.root, [r.note_id for r in p1.records])
            results = validate_bridge(bridge, snapshot_hash=self.metadata["p3_snapshot_hash"])
            if len(results) != len(p1.records):
                raise BoundaryError("MCP_MEMBER_MISMATCH")
            evidence = []
            for record, result in zip(p1.records, results, strict=True):
                if result.status != "ok" or result.document is None:
                    raise BoundaryError("MCP_TOOL_FAILED")
                doc = result.document
                if (result.snapshot_hash != self.metadata["p3_snapshot_hash"] or doc.note_id != record.note_id
                        or doc.text != record.text or doc.content_sha256 != record.content_sha256):
                    raise BoundaryError("MCP_EVIDENCE_DRIFT")
                begin = read_json(self.root / "mcp-audit" / f"audit-{result.call_id}-begin.json")
                end = read_json(self.root / "mcp-audit" / f"audit-{result.call_id}-end.json")
                for receipt in (begin, end):
                    unsigned = {k: v for k, v in receipt.items() if k != "content_hash"}
                    if digest(unsigned) != receipt["content_hash"] or receipt["call_id"] != result.call_id:
                        raise BoundaryError("MCP_AUDIT_INVALID")
                if end["result_hash"] != digest(result.model_dump(mode="json")):
                    raise BoundaryError("MCP_AUDIT_INVALID")
                item = EvidenceRecord(evidence_id=record.record_id + "#" + record.section_id,
                    source_id=record.record_id, candidate_id=record.candidate_id, section_id=record.section_id,
                    locator=record.source_file + "#" + record.section_id, excerpt=record.text,
                    content_sha256=record.content_sha256, source_snapshot_id=self.snapshot.snapshot_id)
                event = {"schema_version": "integration-tool-event-v1", "run_id": self.metadata["run_id"],
                         "request_hash": request.content_hash(), "query_hash": digest(query),
                         "evidence_id": item.evidence_id, "p1_source_sha256": record.source_sha256,
                         "p3_call_id": result.call_id, "p3_snapshot_hash": result.snapshot_hash,
                         "result_hash": end["result_hash"], "receipt_hash": end["content_hash"]}
                write_once(self.root / "tool-events" / (result.call_id + ".json"), event)
                evidence.append(item)
            return tuple(evidence)
        except (ValueError, TypeError, KeyError, OSError):
            raise SourceStoreError("INTEGRATION_EVIDENCE_FAILED") from None


def initialize(parent, question=QUESTION):
    parent = safe_directory(parent)
    if not isinstance(question, str) or not 10 <= len(question) <= 500:
        raise BoundaryError("QUESTION_INVALID")
    run_id = "run-" + uuid.uuid4().hex
    root = parent / run_id
    root.mkdir()
    for name in ("notes", "mcp-audit", "tool-events", "approvals", "artifacts"):
        (root / name).mkdir()
    p1 = P1Response.model_validate(worker(P1, "p1_worker.py", {"operation": "catalog"}))
    entries = []
    for record in p1.records:
        raw = record.text.encode()
        filename = record.record_id + ".md"
        (root / "notes" / filename).write_bytes(raw)
        entries.append(SourceEntryV2(source_id=record.record_id, candidate_id=record.candidate_id,
            title=record.title, canonical_url="https://example.invalid/synthetic/" + record.source_file,
            version="original-fixture-v1", accessed_at="2026-09-16T00:00:00Z", license_id="CC0-1.0",
            relative_path=filename, raw_sha256=record.content_sha256, normalized_sha256=record.content_sha256,
            size_bytes=len(raw)))
    snapshot = SourceSnapshotV2(snapshot_id="snapshot-integration-" + p1.corpus_hash[:20],
        entries=tuple(entries), total_size_bytes=sum(e.size_bytes for e in entries))
    bridge = p3_call(root, [])
    validate_bridge(bridge)
    metadata = {"schema_version": "graduation-run-v1", "run_id": run_id, "question": question,
                "catalog": p1.model_dump(mode="json"), "source_snapshot": snapshot.model_dump(mode="json"),
                "p3_snapshot_hash": bridge["snapshot_hash"], "mode": "scripted-offline"}
    metadata["content_hash"] = digest(metadata)
    write_once(root / "run.json", metadata)
    with Runtime(root) as runtime:
        runtime.graph.invoke(create_initial_state(run_id=run_id, thread_id=run_id, request=runtime.request),
                             runtime.config, durability="sync")
        return root, runtime.state()


class Runtime:
    def __init__(self, root):
        self.root = safe_directory(root)
        if not re.fullmatch(r"run-[a-f0-9]{32}", self.root.name):
            raise BoundaryError("RUN_ID_INVALID")
        self.metadata = read_json(self.root / "run.json")
        unsigned = {k: v for k, v in self.metadata.items() if k != "content_hash"}
        if digest(unsigned) != self.metadata["content_hash"] or self.metadata["run_id"] != self.root.name:
            raise BoundaryError("RUN_METADATA_INVALID")
        if self.metadata["mode"] != "scripted-offline":
            raise BoundaryError("LIVE_FORBIDDEN")
        for name in ("notes", "mcp-audit", "tool-events", "approvals", "artifacts"):
            safe_directory(self.root / name)
        self.store = IntegratedStore(self.root, self.metadata)
        actual_names = {p.name for p in (self.root / "notes").iterdir()}
        if actual_names != {r.record_id + ".md" for r in self.store.records.values()}:
            raise BoundaryError("SNAPSHOT_MEMBER_DRIFT")
        for record in self.store.records.values():
            path = self.root / "notes" / (record.record_id + ".md")
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                raise BoundaryError("RUNTIME_PATH_UNSAFE")
            if hashlib.sha256(path.read_bytes()).hexdigest() != record.content_sha256:
                raise BoundaryError("SNAPSHOT_DRIFT")
        self.model = ScriptedModelClient()  # No factory, provider option or live fallback.
        self.request = ResearchRequestV2(research_question=self.metadata["question"], audience="graduation demonstration",
            candidates=tuple(CandidateSpec(candidate_id=c, name=c) for c in ("graph-plan", "chain-plan")),
            dimensions=tuple(DimensionSpec(dimension_id=d, question=d, weight_percent=w)
                             for d, w in (("tool-calling",34),("human-approval",33),("recovery",33))),
            source_snapshot_id=self.store.snapshot.snapshot_id, model_config_hash=self.model.config_hash,
            budget_authorization_id="offline-zero-cost")
        self.budget = BudgetAuthorization(authorization_id="offline-zero-cost", max_cost_minor_units=0,
            max_model_calls=12, max_input_tokens=48000, max_output_tokens=12000,
            expires_at="2099-01-01T00:00:00Z", approved=True)
        # These paths belong exclusively to this newly created integration run, never P2's real ledger.
        for name in ("operations.sqlite3", "checkpoints.sqlite3"):
            path = self.root / name
            if path.exists() and (path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
                raise BoundaryError("RUNTIME_PATH_UNSAFE")
        self.ledger = OperationLedger(self.root / "operations.sqlite3")
        self.connection = sqlite3.connect(self.root / "checkpoints.sqlite3", check_same_thread=False)
        self.saver = SqliteSaver(self.connection)
        self.saver.setup()
        self.graph = build_v2_graph(checkpointer=self.saver, model=self.model, source_store=self.store,
            ledger=self.ledger, budget=self.budget, exporter=V2Exporter(self.root / "artifacts"))
        self.config = graph_config(self.metadata["run_id"])

    def __enter__(self):
        path = self.root / "session.lock"
        if path.exists() and (path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
            self.__exit__()
            raise BoundaryError("RUNTIME_PATH_UNSAFE")
        self._lock = path.open("a+b")
        if self._lock.tell() == 0:
            self._lock.write(b"0")
            self._lock.flush()
        self._lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.__exit__()
            raise BoundaryError("RUN_BUSY") from None
        return self

    def __exit__(self, *args):
        self.ledger.close()
        self.connection.close()
        if getattr(self, "_lock", None) is not None:
            self._lock.close()

    def state(self):
        return self.graph.get_state(self.config).values

    def decide(self, action, expected_hash, *, actor="operator-cli"):
        if action not in ("approve", "reject", "cancel") or actor not in ("operator-cli", "scripted-test"):
            raise BoundaryError("ACTION_INVALID")
        current = self.state()
        if current["status"] == "COMPLETED":
            if action != "approve" or current["report_hash"] != expected_hash:
                raise BoundaryError("APPROVAL_HASH_MISMATCH")
            self.delivery()
            return current
        gate = current["status"]
        if gate == "NEEDS_HUMAN":
            expected = current["request_hash"]
            resume = {"expected_request_hash": expected}
        elif gate == "REPORT_NEEDS_HUMAN":
            expected = current["report_hash"]
            resume = {"report_hash": expected, "report_revision": current["report_revision"]}
        else:
            raise BoundaryError("NOT_AT_APPROVAL_GATE")
        if expected != expected_hash:
            raise BoundaryError("APPROVAL_HASH_MISMATCH")
        if gate == "REPORT_NEEDS_HUMAN" and action == "approve":
            self.verify_tool_audit(current)
        event = {"run_id": self.metadata["run_id"], "gate": gate, "expected_hash": expected,
                 "action": action, "actor": actor, "content_quality_approval": False}
        event["event_hash"] = digest(event)
        # Record submitted decision before graph resume so a crash cannot silently erase operator intent.
        write_once(self.root / "approvals" / (event["event_hash"] + ".json"), event)
        resume.update(run_id=self.metadata["run_id"], thread_id=self.metadata["run_id"], action=action)
        self.graph.invoke(Command(resume=resume), self.config, durability="sync")
        result = self.state()
        if result["status"] == "COMPLETED":
            self.delivery()
        return result

    def delivery(self):
        state = self.state()
        if state["status"] != "COMPLETED":
            raise BoundaryError("REPORT_NOT_APPROVED")
        artifacts = list((self.root / "artifacts").glob("*.md"))
        if len(artifacts) != 1:
            raise BoundaryError("ARTIFACT_COUNT_INVALID")
        approvals = sorted((read_json(p) for p in (self.root / "approvals").glob("*.json")), key=lambda x:x["event_hash"])
        events = self.verify_tool_audit(state)
        value = {"schema_version": "graduation-delivery-v1", "run_id": self.metadata["run_id"],
            "mode": "scripted-offline", "request_hash": state["request_hash"], "report_hash": state["report_hash"],
            "artifact_id": state["artifact_id"], "artifact_name": artifacts[0].name,
            "artifact_sha256": hashlib.sha256(artifacts[0].read_bytes()).hexdigest(),
            "p1_corpus_hash": self.metadata["catalog"]["corpus_hash"],
            "p3_snapshot_hash": self.metadata["p3_snapshot_hash"], "approvals": approvals, "tool_events": events,
            "evidence_count": len(state["evidence"]), "scripted_model_calls": state["model_call_count"],
            "real_model_calls": 0, "cost_minor_units": 0, "content_quality_passed": False,
            "limitations": LIMITATIONS}
        return self._publish_delivery(state, artifacts, approvals, events, value)

    def verify_tool_audit(self, state):
        events = sorted((read_json(p) for p in (self.root / "tool-events").glob("*.json")), key=lambda x:x["p3_call_id"])
        evidence_ids = {e["evidence_id"] for e in state["evidence"]}
        if not evidence_ids or evidence_ids != {e["evidence_id"] for e in events}:
            raise BoundaryError("MCP_AUDIT_INVALID")
        for event in events:
            if (not re.fullmatch(r"[a-f0-9]{32}", event["p3_call_id"]) or
                    event["run_id"] != self.metadata["run_id"] or event["request_hash"] != state["request_hash"]):
                raise BoundaryError("MCP_AUDIT_INVALID")
            receipt = read_json(self.root / "mcp-audit" / ("audit-" + event["p3_call_id"] + "-end.json"))
            unsigned = {k:v for k,v in receipt.items() if k != "content_hash"}
            if digest(unsigned) != event["receipt_hash"] or receipt["result_hash"] != event["result_hash"]:
                raise BoundaryError("MCP_AUDIT_INVALID")
            if (receipt["error_code"] is not None or receipt["tool"] != "read_note"
                    or receipt["snapshot_hash"] != self.metadata["p3_snapshot_hash"]):
                raise BoundaryError("MCP_AUDIT_INVALID")
        return events

    def _publish_delivery(self, state, artifacts, approvals, events, value):
        applied = {(a["gate"], a["expected_hash"]) for a in approvals if a["action"] == "approve"}
        if not {("NEEDS_HUMAN", state["approved_request_hash"]),
                ("REPORT_NEEDS_HUMAN", state["approved_report_hash"])} <= applied:
            raise BoundaryError("APPROVAL_AUDIT_MISSING")
        heading = ["# 可信 AI 应用方案研究与交付平台：离线交付报告", "",
            "本报告使用原创合成资料和脚本模型。下列审批仅批准演示流程，不是独立内容质量评分。", "",
            f"运行：`{value['run_id']}`；报告哈希：`{value['report_hash']}`。", "",
            "## 边界与未验证项", "",
            "P2真实内容验收未通过：首批2份有限批准、4份拒绝；修复后2份有限批准、1份拒绝。",
            "P2永久上限5元，保守占用417/500分、调用容量109/109；本轮真实调用0、费用0。",
            "P1只运行HTML解析与夹具关键词适配器，未验证BGE/Qdrant、HTTP、容器或云部署。",
            "本轮由助手实现，学习者独立实现、答辩讲解和独立人工评分尚未验证。", "",
            "## 审批记录", ""]
        heading += [f"- {a['gate']} / {a['action']} / {a['actor']} / `{a['expected_hash']}`" for a in approvals]
        heading += ["", "## MCP调用审计", "", "每条引用通过P1原始资料哈希与P3读取正文交叉核验；收据位于mcp-audit目录。", ""]
        heading += [f"- `{e['evidence_id']}`：call `{e['p3_call_id']}`；result `{e['result_hash']}`" for e in events]
        heading += ["", "## P2生成制品（脚本模型）", "", artifacts[0].read_text(encoding="utf-8")]
        report_bytes = ("\n".join(heading) + "\n").encode("utf-8")
        publish_bytes(self.root / "delivery-report.md", report_bytes)
        value["delivery_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
        write_once(self.root / "delivery.json", value)
        return value

    def recover(self):
        """Resume persisted unfinished graph work; never invent a new human decision."""
        state = self.state()
        if state["status"] == "COMPLETED":
            self.delivery()
        elif state["status"] not in ("NEEDS_HUMAN", "REPORT_NEEDS_HUMAN", "FAILED", "CANCELLED"):
            if self.graph.get_state(self.config).next:
                self.graph.invoke(None, self.config, durability="sync")
                state = self.state()
                if state["status"] == "COMPLETED":
                    self.delivery()
        return state
