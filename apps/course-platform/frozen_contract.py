"""HTTP-side preparation of bounded, immutable execution inputs; no graph imports."""
from domain import digest, fields, identifier, require
from projects import project_text
from library import Library


DIMENSIONS = [
    {'dimension_id': 'tool-calling', 'question': '工具调用 tool calling', 'weight_percent': 34},
    {'dimension_id': 'human-approval', 'question': '人工审批 human approval', 'weight_percent': 33},
    {'dimension_id': 'recovery', 'question': '故障恢复 recovery checkpoint', 'weight_percent': 33},
]


def prepare(projects, project_id, payload):
    fields(payload, 'request_id expected_contract_hash candidates confirmed')
    request_id = identifier(payload['request_id'])
    require(payload['confirmed'] is True, 'PROJECT_CONFIRMATION')
    project = projects.get(project_id)
    require(payload['expected_contract_hash'] == project['contract_hash'], 'STALE_APPROVAL')
    require(type(payload['candidates']) is list and 2 <= len(payload['candidates']) <= 4, 'EXECUTION_SCOPE')
    candidates, versions = [], []
    for i, item in enumerate(payload['candidates'], 1):
        fields(item, 'name version_id')
        name = project_text(item['name'], 2, 100)
        require(type(item['version_id']) is str and item['version_id'] in project['version_ids'], 'EXECUTION_SCOPE')
        versions.append(item['version_id'])
        candidates.append({'candidate_id': f'candidate-{i}', 'name': name, 'version_id': item['version_id']})
    require(len(set(versions)) == len(versions) and len({c['name'] for c in candidates}) == len(candidates), 'EXECUTION_SCOPE')
    records = [r for r in projects._records(project) if r['version_id'] in versions]
    require(0 < len(records) <= 64 and sum(len(r['text'].encode()) for r in records) <= 98304, 'EXECUTION_SCOPE')
    source_documents = [{'version_id': version, 'content': Library(projects.store).get(version)['content']}
                        for version in sorted(versions)]
    require(sum(len(d['content'].encode()) for d in source_documents) <= 98304, 'EXECUTION_SCOPE')
    for i, record in enumerate(records, 1):
        record.update(record_id=f'source-{i}', candidate_id=next(c['candidate_id'] for c in candidates if c['version_id'] == record['version_id']))
    snapshot = {'schema_version': 'frozen-execution-v1', 'project_id': project_id,
                'contract_hash': project['contract_hash'], 'project_title': project['title'],
                'question': project['question'], 'constraints': project['constraints'],
                'manifest': project['manifest'], 'candidates': candidates, 'dimensions': DIMENSIONS,
                'source_documents': source_documents, 'records': records}
    snapshot['execution_hash'] = digest(snapshot)
    return request_id, snapshot
