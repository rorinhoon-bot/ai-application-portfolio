"""Frozen app inputs, real P2 checkpoints and P3 MCP, scripted models only.

Imported exclusively in an isolated worker because workflow_runtime denies network.
"""
import hashlib
import sqlite3
from pathlib import Path

from domain import APP, digest, require, safe_path
from workflow_runtime import (Runtime, P1, worker, read_json, write_once, publish_bytes,
    SqliteSaver, OperationLedger, ScriptedModelClient, V2Exporter, build_v2_graph,
    create_initial_state, graph_config, ResearchRequestV2, CandidateSpec, DimensionSpec,
    SourceEntryV2, SourceSnapshotV2, EvidenceRecord, BudgetAuthorization, SourceStoreError,
    p3_call, validate_bridge, LIMITATIONS as OLD_LIMITATIONS)
from agent_research.v2.contracts import ModelResult
from agent_research.v2.graph import _coverage_query

LIMITATIONS = [
    'Offline frozen user-provided text and scripted model; no real content quality acceptance.',
    'P1 tokenize_sparse only; application token-overlap ranking, not P1 vector/BM25 retrieval or service evaluation.',
    *OLD_LIMITATIONS[2:],
    'Local operator approval and manual summary editing are not independent content quality grading.',
]


def validate_snapshot(snapshot):
    from library import chunks
    require(snapshot.get('schema_version') == 'frozen-execution-v1', 'ENGINE_FAILED')
    require(digest({k: v for k, v in snapshot.items() if k != 'execution_hash'}) == snapshot['execution_hash'], 'ENGINE_FAILED')
    require(digest({'schema_version': 'research-scope-v1', 'title': snapshot['project_title'],
        'question': snapshot['question'], 'constraints': snapshot['constraints'],
        'version_ids': [m['version_id'] for m in snapshot['manifest']],
        'manifest': snapshot['manifest']}) == snapshot['contract_hash'], 'ENGINE_FAILED')
    records = snapshot['records']
    require(0 < len(records) <= 64 and sum(len(r['text'].encode()) for r in records) <= 98304, 'EXECUTION_SCOPE')
    require(2 <= len(snapshot['candidates']) <= 4, 'EXECUTION_SCOPE')
    candidates = {c['candidate_id']: c['version_id'] for c in snapshot['candidates']}
    require(len(candidates) == len(snapshot['candidates']) == len(set(candidates.values())), 'EXECUTION_SCOPE')
    manifest = {m['version_id']: m for m in snapshot['manifest']}
    source_documents = {s['version_id']: s['content'] for s in snapshot['source_documents']}
    require(set(source_documents) == set(candidates.values()) and
            len(snapshot['source_documents']) == len(source_documents) and
            sum(len(t.encode()) for t in source_documents.values()) <= 98304, 'ENGINE_FAILED')
    for version, content in source_documents.items():
        require(hashlib.sha256(content.encode()).hexdigest() == manifest[version]['content_hash'], 'ENGINE_FAILED')
        expected_parts = chunks(content, version)
        actual_parts = [{k:r[k] for k in ('text','line_start','line_end','column_start','column_end','chunk_id','content_hash','locator')}
                        for r in records if r['version_id'] == version]
        require(actual_parts == expected_parts, 'ENGINE_FAILED')
    require(len({r['record_id'] for r in records}) == len(records), 'ENGINE_FAILED')
    for index, record in enumerate(records, 1):
        require(record['record_id'] == f'source-{index}', 'ENGINE_FAILED')
        require(record['version_id'] == candidates.get(record['candidate_id']) and
                record['source_hash'] == manifest[record['version_id']]['content_hash'], 'ENGINE_FAILED')
        require(hashlib.sha256(record['text'].encode()).hexdigest() == record['content_hash'], 'ENGINE_FAILED')


class FrozenStore:
    def __init__(self, root, metadata):
        self.root, self.metadata = root, metadata
        self.records = metadata['execution']['records']
        self.snapshot = SourceSnapshotV2.model_validate(metadata['source_snapshot'])
        self.tokens = None

    def search(self, *, query, request, top_k=6, candidate_ids=None):
        try:
            candidates = candidate_ids or {c.candidate_id for c in request.candidates}
            require(set(candidates) <= {c.candidate_id for c in request.candidates}, 'ENGINE_FAILED')
            queries = [_coverage_query(d) for d in request.dimensions] + [request.research_question[:300]]
            if query not in queries:
                queries.append(query)
            if self.tokens is None or query not in self.tokens[1]:
                result = worker(P1, str(APP / 'frozen_p1_worker.py'),
                                {'texts': [r['text'] for r in self.records] + queries})
                require(set(result) == {'tokens'} and len(result['tokens']) == len(self.records) + len(queries), 'ENGINE_FAILED')
                require(all(type(t) is list and all(type(v) is str for v in t) for t in result['tokens']), 'ENGINE_FAILED')
                self.tokens = ([set(t) for t in result['tokens'][:len(self.records)]],
                               dict(zip(queries, map(set, result['tokens'][len(self.records):]), strict=True)))
            scores = [(len(tokens & self.tokens[1][query]), record) for record, tokens in zip(self.records, self.tokens[0], strict=True)
                      if record['candidate_id'] in candidates]
            selected = [r for score, r in sorted(scores, key=lambda p: (-p[0], p[1]['record_id'])) if score > 0][:top_k]
            if not selected:
                return ()
            ids = [hashlib.sha256((r['record_id'] + '.md').encode()).hexdigest()[:16] for r in selected]
            bridge = p3_call(self.root, ids)
            snapshot_file = self.root / 'p3-snapshot.json'
            expected = read_json(snapshot_file)['snapshot_hash'] if snapshot_file.exists() else None
            results = validate_bridge(bridge, snapshot_hash=expected)
            write_once(snapshot_file, {'snapshot_hash': bridge['snapshot_hash']})
            require(len(results) == len(selected), 'ENGINE_FAILED')
            evidence = []
            for record, note_id, result in zip(selected, ids, results, strict=True):
                doc = result.document
                require(result.status == 'ok' and doc is not None and doc.note_id == note_id and
                    doc.text == record['text'] and doc.content_sha256 == record['content_hash'] and
                    result.snapshot_hash == bridge['snapshot_hash'], 'ENGINE_FAILED')
                for phase in ('begin', 'end'):
                    receipt = read_json(self.root / 'mcp-audit' / f'audit-{result.call_id}-{phase}.json')
                    require(digest({k:v for k,v in receipt.items() if k != 'content_hash'}) == receipt['content_hash'] and
                            receipt['call_id'] == result.call_id, 'ENGINE_FAILED')
                require(receipt['result_hash'] == digest(result.model_dump(mode='json')), 'ENGINE_FAILED')
                item = EvidenceRecord(evidence_id=record['record_id'] + '#chunk', source_id=record['record_id'],
                    candidate_id=record['candidate_id'], section_id='chunk', locator=record['version_id'] + ':' + record['locator'],
                    excerpt=record['text'], content_sha256=record['content_hash'], source_snapshot_id=self.snapshot.snapshot_id)
                event = {'schema_version': 'frozen-tool-event-v1', 'run_id': self.metadata['run_id'],
                    'request_hash': request.content_hash(), 'query_hash': digest(query), 'evidence_id': item.evidence_id,
                    'execution_hash': self.metadata['execution']['execution_hash'], 'version_id': record['version_id'],
                    'chunk_id': record['chunk_id'], 'p1_source_sha256': record['source_hash'],
                    'p3_call_id': result.call_id, 'p3_snapshot_hash': result.snapshot_hash,
                    'result_hash': receipt['result_hash'], 'receipt_hash': receipt['content_hash'],
                    'result': result.model_dump(mode='json')}
                write_once(self.root / 'tool-events' / (result.call_id + '.json'), event)
                evidence.append(item)
            return tuple(evidence)
        except (ValueError, TypeError, KeyError, OSError):
            raise SourceStoreError('FROZEN_EVIDENCE_FAILED') from None


def initialize(root, snapshot):
    validate_snapshot(snapshot)
    root = safe_path(root, directory=True)
    root.mkdir(parents=True, exist_ok=True)
    for name in ('notes', 'mcp-audit', 'tool-events', 'approvals', 'artifacts', 'revisions'):
        safe_path(root / name, directory=True).mkdir(exist_ok=True)
    entries = []
    manifest = {m['version_id']: m for m in snapshot['manifest']}
    for record in snapshot['records']:
        filename = record['record_id'] + '.md'
        publish_bytes(root / 'notes' / filename, record['text'].encode())
        entries.append(SourceEntryV2(source_id=record['record_id'], candidate_id=record['candidate_id'],
            title='Frozen ' + record['title'], canonical_url='https://example.invalid/local/' + record['version_id'],
            version=record['version_id'], accessed_at=manifest[record['version_id']]['created_at'], license_id='user-confirmed',
            relative_path=filename, raw_sha256=record['content_hash'], normalized_sha256=record['content_hash'],
            size_bytes=len(record['text'].encode())))
    sources = SourceSnapshotV2(snapshot_id='snapshot-frozen-' + snapshot['execution_hash'][:20],
        entries=tuple(entries), total_size_bytes=sum(e.size_bytes for e in entries))
    metadata = {'schema_version': 'frozen-run-v1', 'run_id': root.name, 'execution': snapshot,
                'source_snapshot': sources.model_dump(mode='json'), 'mode': 'frozen-scripted-offline'}
    metadata['content_hash'] = digest(metadata)
    write_once(root / 'run.json', metadata)


class FrozenRuntime(Runtime):
    def __init__(self, root, snapshot):
        self.root = safe_path(root, directory=True)
        self.metadata = read_json(self.root / 'run.json')
        require(self.metadata['mode'] == 'frozen-scripted-offline' and self.metadata['run_id'] == root.name and
                self.metadata['execution'] == snapshot and
                digest({k:v for k,v in self.metadata.items() if k != 'content_hash'}) == self.metadata['content_hash'], 'ENGINE_FAILED')
        validate_snapshot(snapshot)
        for name in ('notes','mcp-audit','tool-events','approvals','artifacts','revisions'):
            safe_path(root / name,directory=True)
        self.store = FrozenStore(self.root, self.metadata)
        require({p.name for p in (root / 'notes').iterdir()} == {r['record_id'] + '.md' for r in snapshot['records']}, 'ENGINE_FAILED')
        for r in snapshot['records']:
            require(safe_path(root / 'notes' / (r['record_id'] + '.md')).read_bytes() == r['text'].encode(), 'ENGINE_FAILED')
        self.model = ScriptedModelClient()
        self.request = ResearchRequestV2(research_question=snapshot['question'], audience='local graduation demonstration',
            candidates=tuple(CandidateSpec(candidate_id=c['candidate_id'], name=c['name'], scope_note='Frozen version ' + c['version_id']) for c in snapshot['candidates']),
            dimensions=tuple(DimensionSpec(**d) for d in snapshot['dimensions']),
            hard_constraints=tuple(snapshot['constraints']) + ('Frozen execution SHA-256: ' + snapshot['execution_hash'],),
            source_snapshot_id=self.store.snapshot.snapshot_id, model_config_hash=self.model.config_hash,
            budget_authorization_id='offline-zero-cost')
        self.budget = BudgetAuthorization(authorization_id='offline-zero-cost', max_cost_minor_units=0,
            max_model_calls=12, max_input_tokens=48000, max_output_tokens=12000, expires_at='2099-01-01T00:00:00Z', approved=True)
        self.ledger = OperationLedger(safe_path(root / 'operations.sqlite3'))
        self.connection = sqlite3.connect(safe_path(root / 'checkpoints.sqlite3'), check_same_thread=False)
        self.saver = SqliteSaver(self.connection)
        self.saver.setup()
        self.graph = build_v2_graph(checkpointer=self.saver, model=self.model, source_store=self.store,
            ledger=self.ledger, budget=self.budget, exporter=V2Exporter(root / 'artifacts'))
        self.config = graph_config(root.name)

    def start(self):
        if not self.state():
            self.graph.invoke(create_initial_state(run_id=self.root.name, thread_id=self.root.name, request=self.request),
                              self.config, durability='sync')

    def revisions(self):
        return sorted((read_json(p) for p in (self.root / 'revisions').glob('*.json')), key=lambda r:r['revision'])

    def revise(self, request_id, payload):
        current = self.state()
        path = self.root / 'revisions' / (request_id + '.json')
        if path.exists():
            revision = read_json(path)
            require(revision['payload_hash'] == digest(payload), 'IDEMPOTENCY_CONFLICT')
        else:
            require(current['status'] == 'REPORT_NEEDS_HUMAN' and current['report_hash'] == payload['expected_hash'], 'STALE_APPROVAL')
            require(current['report_revision'] < 3 and len(self.revisions()) < 2, 'REVISION_INVALID')
            report = {**current['report'], 'executive_summary': payload['summary'],
                      'limitations': list(dict.fromkeys(payload['limitations'] + LIMITATIONS))}
            report = ModelResult.model_validate(report).model_dump(mode='json')
            revision = {'request_id': request_id, 'payload_hash': digest(payload), 'note': payload['note'],
                'old_report': current['report'], 'old_hash': current['report_hash'], 'new_report': report,
                'new_hash': digest(report), 'revision': current['report_revision'] + 1, 'actor': 'local-browser',
                'content_quality_approval': False}
            revision['event_hash'] = digest(revision)
            write_once(path, revision)
        self.apply_revision(revision)

    def apply_revision(self, revision):
        require(digest({k:v for k,v in revision.items() if k != 'event_hash'}) == revision['event_hash'], 'ENGINE_FAILED')
        current = self.state()
        if current['report_hash'] == revision['old_hash']:
            require(current['status'] == 'REPORT_NEEDS_HUMAN', 'REVISION_INVALID')
            self.graph.update_state(self.config, {'report': revision['new_report'], 'report_hash': revision['new_hash'],
                'report_revision': revision['revision'], 'approved_report_hash': None, 'approved_report_revision': None,
                'status': 'REPORT_NEEDS_HUMAN', 'current_node': 'report-gate'}, as_node='review_report')
        require(self.state()['report_hash'] == revision['new_hash'], 'REVISION_INVALID')
        # The updated checkpoint must run the gate once to persist its new interrupt.
        view = self.graph.get_state(self.config)
        if view.next and not any(t.interrupts for t in view.tasks):
            self.graph.invoke(None, self.config, durability='sync')

    def recover(self):
        revisions = self.revisions()
        if revisions and self.state()['status'] == 'REPORT_NEEDS_HUMAN':
            self.apply_revision(revisions[-1])
        return super().recover()

    def verify_tool_audit(self, state):
        from frozen_bundle import verify_evidence
        events = [read_json(p) for p in sorted((self.root / 'tool-events').glob('*.json'))]
        receipts = {}
        for event in events:
            for phase in ('begin', 'end'):
                name = f"audit-{event['p3_call_id']}-{phase}.json"
                receipts[name] = read_json(safe_path(self.root / 'mcp-audit' / name))
        verify_evidence(self.metadata['execution'], state, events, receipts)
        return events

    def delivery(self):
        from frozen_bundle import build_content, verify_content
        content = build_content(self)
        return verify_content(content)
