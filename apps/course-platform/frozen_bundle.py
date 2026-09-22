"""Independent bounded verifier for the frozen-project delivery contract."""
import hashlib
import json
import re

from domain import digest, require
from workflow_runtime import read_json
from agent_research.v2.contracts import ResearchRequestV2, ModelResult, EvidenceRecord
from agent_research.v2.exporter import render_markdown


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def verify_evidence(execution, state, events, receipts):
    require(state['approved_request_hash'] == state['request_hash'], 'ENGINE_FAILED')
    records = {r['record_id']: r for r in execution['records']}
    ids = {e['evidence_id'] for e in state['evidence']}
    require(bool(ids) and ids == {e['evidence_id'] for e in events}, 'ENGINE_FAILED')
    snapshots = set()
    for event in events:
        require(event['schema_version'] == 'frozen-tool-event-v1' and
                event['execution_hash'] == execution['execution_hash'] and
                event['request_hash'] == state['request_hash'], 'ENGINE_FAILED')
        source_id = event['evidence_id'].split('#')[0]
        record = records.get(source_id)
        require(record is not None and event['evidence_id'] == source_id + '#chunk' and
                event['chunk_id'] == record['chunk_id'] and event['version_id'] == record['version_id'] and
                event['p1_source_sha256'] == record['source_hash'], 'ENGINE_FAILED')
        item = next(e for e in state['evidence'] if e['evidence_id'] == event['evidence_id'])
        require(item['content_sha256'] == record['content_hash'] and item['excerpt'] == record['text'] and
                item['candidate_id'] == record['candidate_id'] and item['source_id'] == source_id, 'ENGINE_FAILED')
        call = event['p3_call_id']
        require(re.fullmatch('[a-f0-9]{32}', call) is not None, 'ENGINE_FAILED')
        begin = receipts.get(f'audit-{call}-begin.json')
        end = receipts.get(f'audit-{call}-end.json')
        require(begin is not None and end is not None, 'ENGINE_FAILED')
        for phase, receipt in [('begin', begin), ('end', end)]:
            require(receipt['call_id'] == call and receipt['phase'] == phase and receipt['tool'] == 'read_note' and
                    digest({k:v for k,v in receipt.items() if k != 'content_hash'}) == receipt['content_hash'], 'ENGINE_FAILED')
        result = event['result']
        note_id = hashlib.sha256((source_id + '.md').encode()).hexdigest()[:16]
        require(result['call_id'] == call and result['status'] == 'ok' and result['error_code'] is None and
                result['document']['text'] == record['text'] and result['document']['content_sha256'] == record['content_hash'] and
                result['document']['note_id'] == note_id and
                result['snapshot_hash'] == event['p3_snapshot_hash'] and
                end['result_hash'] == digest(result) == event['result_hash'] and
                end['content_hash'] == event['receipt_hash'] and
                begin['snapshot_hash'] == end['snapshot_hash'] == result['snapshot_hash'] and
                begin['arguments_hash'] == end['arguments_hash'] == digest({'note_id':note_id}), 'ENGINE_FAILED')
        snapshots.add(result['snapshot_hash'])
    require(len(snapshots) == 1, 'ENGINE_FAILED')


def build_content(runtime):
    state = runtime.state()
    require(state['status'] == 'COMPLETED' and state['approved_report_hash'] == state['report_hash'] and
            state['report_hash'] == digest(state['report']), 'NOT_COMPLETED')
    events = runtime.verify_tool_audit(state)
    revisions = runtime.revisions()
    artifacts = list((runtime.root / 'artifacts').glob('*.md'))
    require(len(artifacts) == 1 and artifacts[0].name == state['artifact_id'] + '.md', 'ENGINE_FAILED')
    approvals = [read_json(p) for p in sorted((runtime.root / 'approvals').glob('*.json'))]
    require({(a['gate'],a['expected_hash']) for a in approvals if a['action'] == 'approve'} >=
            {('NEEDS_HUMAN',state['request_hash']),('REPORT_NEEDS_HUMAN',state['report_hash'])}, 'ENGINE_FAILED')
    for approval in approvals:
        require(digest({k:v for k,v in approval.items() if k != 'event_hash'}) == approval['event_hash'] and
                approval['content_quality_approval'] is False, 'ENGINE_FAILED')
    content = {
        'execution.json': canonical(runtime.metadata['execution']),
        'state.json': canonical({k:state[k] for k in ('run_id','status','request','request_hash','report','report_hash',
            'report_revision','approved_request_hash','approved_report_hash','evidence','artifact_id','model_call_count','tool_call_count')}),
        'source-snapshot.json': canonical(runtime.metadata['source_snapshot']),
        'approvals.json': canonical(approvals), 'revisions.json': canonical(revisions), 'tool-events.json': canonical(events),
        'report.md': artifacts[0].read_bytes(),
    }
    for record in runtime.metadata['execution']['records']:
        filename = record['record_id'] + '.md'
        content['sources/' + filename] = (runtime.root / 'notes' / filename).read_bytes()
    for original in runtime.metadata['execution']['source_documents']:
        content['versions/' + original['version_id'] + '.md'] = original['content'].encode()
    for event in events:
        for phase in ('begin', 'end'):
            filename = f"audit-{event['p3_call_id']}-{phase}.json"
            content['mcp-audit/' + filename] = (runtime.root / 'mcp-audit' / filename).read_bytes()
    manifest = {'schema_version': 'frozen-delivery-v1', 'project_id': runtime.metadata['execution']['project_id'],
        'contract_hash': runtime.metadata['execution']['contract_hash'],
        'execution_hash': runtime.metadata['execution']['execution_hash'],
        'files': {name:sha(data) for name,data in sorted(content.items())},
        'real_model_calls': 0, 'cost_minor_units': 0, 'content_quality_passed': False,
        'limitations': ['P2 real model content quality not accepted; scripted offline only.',
                        'School cohort requirements and independent human grading unverified.']}
    manifest['content_hash'] = digest(manifest)
    content['manifest.json'] = canonical(manifest)
    verify_content(content)
    return content


def verify_content(content):
    require(type(content) is dict and len(content) <= 300 and
            sum(len(v) for v in content.values()) <= 2 * 1024 * 1024 and
            all(type(k) is str and type(v) is bytes and '..' not in k and '\\' not in k for k,v in content.items()), 'ENGINE_FAILED')
    require('manifest.json' in content, 'ENGINE_FAILED')
    manifest = json.loads(content['manifest.json'])
    require(manifest['schema_version'] == 'frozen-delivery-v1' and manifest['real_model_calls'] == 0 and
            manifest['cost_minor_units'] == 0 and manifest['content_quality_passed'] is False and
            digest({k:v for k,v in manifest.items() if k != 'content_hash'}) == manifest['content_hash'] and
            set(manifest['files']) == set(content) - {'manifest.json'}, 'ENGINE_FAILED')
    require(all(manifest['files'][name] == sha(data) for name,data in content.items() if name != 'manifest.json'), 'ENGINE_FAILED')
    execution = json.loads(content['execution.json'])
    state = json.loads(content['state.json'])
    approvals = json.loads(content['approvals.json'])
    revisions = json.loads(content['revisions.json'])
    events = json.loads(content['tool-events.json'])
    require(digest({k:v for k,v in execution.items() if k != 'execution_hash'}) == execution['execution_hash'] == manifest['execution_hash'] and
            execution['contract_hash'] == manifest['contract_hash'] and execution['project_id'] == manifest['project_id'], 'ENGINE_FAILED')
    require(state['status'] == 'COMPLETED' and state['request_hash'] == state['approved_request_hash'] and
            state['report_hash'] == state['approved_report_hash'] == digest(state['report']) and
            state['request_hash'] == digest(state['request']), 'ENGINE_FAILED')
    request = ResearchRequestV2.model_validate(state['request'])
    report = ModelResult.model_validate(state['report'])
    evidence = tuple(EvidenceRecord.model_validate(e) for e in state['evidence'])
    source_snapshot = json.loads(content['source-snapshot.json'])
    require(request.source_snapshot_id == source_snapshot['snapshot_id'] and
            {e['source_id']: e['raw_sha256'] for e in source_snapshot['entries']} ==
            {r['record_id']:r['content_hash'] for r in execution['records']} and
            {c.candidate_id:c.name for c in request.candidates} ==
            {c['candidate_id']:c['name'] for c in execution['candidates']} and
            {d.dimension_id:d.weight_percent for d in request.dimensions} ==
            {d['dimension_id']:d['weight_percent'] for d in execution['dimensions']} and
            request.research_question == execution['question'] and
            execution['execution_hash'] in ' '.join(request.hard_constraints), 'ENGINE_FAILED')
    require(content['report.md'] == render_markdown(request=request,report=report,evidence=evidence) and
            state['artifact_id'] == digest({'run_id':state['run_id'], 'report_revision':state['report_revision'],
                'report_hash':report.raw_response_sha256 or state['report_hash'],'format':'markdown-v2.1'}), 'ENGINE_FAILED')
    require({(a['gate'],a['expected_hash']) for a in approvals if a['action'] == 'approve'} >=
            {('NEEDS_HUMAN',state['request_hash']),('REPORT_NEEDS_HUMAN',state['report_hash'])}, 'ENGINE_FAILED')
    for approval in approvals:
        require(digest({k:v for k,v in approval.items() if k != 'event_hash'}) == approval['event_hash'] and
                approval['content_quality_approval'] is False, 'ENGINE_FAILED')
    prior_hash = None
    for revision in revisions:
        require(digest({k:v for k,v in revision.items() if k != 'event_hash'}) == revision['event_hash'] and
                digest(revision['old_report']) == revision['old_hash'] and
                digest(revision['new_report']) == revision['new_hash'] and
                (prior_hash is None or revision['old_hash'] == prior_hash), 'ENGINE_FAILED')
        prior_hash = revision['new_hash']
    if revisions:
        require(prior_hash == state['report_hash'] and state['report_revision'] == 1 + len(revisions), 'ENGINE_FAILED')
    records = execution['records']
    manifest_sources = {m['version_id']:m for m in execution['manifest']}
    require({k for k in content if k.startswith('versions/')} ==
            {'versions/'+s['version_id']+'.md' for s in execution['source_documents']}, 'ENGINE_FAILED')
    from library import chunks
    for original in execution['source_documents']:
        version = original['version_id']
        require(content['versions/'+version+'.md'] == original['content'].encode() and
                sha(original['content'].encode()) == manifest_sources[version]['content_hash'], 'ENGINE_FAILED')
        actual = [{k:r[k] for k in ('text','line_start','line_end','column_start','column_end','chunk_id','content_hash','locator')}
                  for r in records if r['version_id'] == version]
        require(actual == chunks(original['content'],version), 'ENGINE_FAILED')
    require({k for k in content if k.startswith('sources/')} == {'sources/'+r['record_id']+'.md' for r in records}, 'ENGINE_FAILED')
    for record in records:
        require(content['sources/'+record['record_id']+'.md'] == record['text'].encode() and
                sha(record['text'].encode()) == record['content_hash'], 'ENGINE_FAILED')
    receipt_names = {k[10:] for k in content if k.startswith('mcp-audit/')}
    require(receipt_names == {f'audit-{e["p3_call_id"]}-{phase}.json' for e in events for phase in ('begin','end')}, 'ENGINE_FAILED')
    receipts = {name:json.loads(content['mcp-audit/'+name]) for name in receipt_names}
    verify_evidence(execution,state,events,receipts)
    return {'bundle_consistent': True, 'schema_version': manifest['schema_version'],
            'project_id': manifest['project_id'], 'execution_hash': manifest['execution_hash'],
            'evidence_count': len(state['evidence']), 'mcp_calls': len(events),
            'scripted_model_calls': state['model_call_count'], 'real_model_calls': 0,
            'cost_minor_units': 0, 'content_quality_passed': False}
