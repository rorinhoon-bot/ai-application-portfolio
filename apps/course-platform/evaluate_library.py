"""Fixed synthetic retrieval mechanism comparison; no model or external data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time
import uuid

from library import Library
from store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    fixture = Path(__file__).parent / 'evals/library-v1.json'
    raw = fixture.read_bytes()
    dataset = json.loads(raw)
    rows = []
    with tempfile.TemporaryDirectory(prefix='library-eval-') as temporary:
        library = Library(Store(Path(temporary)))
        mapping, parts = {}, []
        for document in dataset['documents']:
            item = library.import_text(dict(request_id=uuid.uuid4().hex, title=document['title'], filename=document['id']+'.md',
                                           source_ref='synthetic:'+document['id'], rights_note=dataset['provenance'], content=document['content'],
                                           confirmed=True, expected_version=''))
            mapping[item['document_id']] = document['id']
            parts.extend({**part, 'expected':document['id']} for part in item['chunks'])
        for case in dataset['questions']:
            start = time.perf_counter()
            result = library.search(dict(query=case['query'], document_ids=[], top_k=3))['results']
            elapsed = (time.perf_counter()-start)*1000
            predicted = [mapping[r['document_id']] for r in result]
            baseline = [p['expected'] for p in parts if case['query'].casefold() in p['text'].casefold()][:3]
            expected = case['expected']
            def metrics(values):
                return {'hit_at_1':bool(values and values[0]==expected) if expected else None,
                        'hit_at_3':expected in values if expected else None,
                        'empty_correct':not values if expected is None else None}
            rows.append({**case, 'lexical':{'predicted':predicted, **metrics(predicted)},
                         'exact_substring':{'predicted':baseline, **metrics(baseline)}, 'latency_ms':round(elapsed,3)})
    def aggregate(name):
        positives = [row[name] for row in rows if row['expected']]
        negatives = [row[name] for row in rows if row['expected'] is None]
        return {'hit_at_1':sum(r['hit_at_1'] for r in positives)/len(positives),
                'hit_at_3':sum(r['hit_at_3'] for r in positives)/len(positives),
                'no_evidence_correct':sum(r['empty_correct'] for r in negatives)/len(negatives)}
    result = {'schema_version':'synthetic-library-eval-v1','at':datetime.now(timezone.utc).isoformat(),
              'fixture_sha256':hashlib.sha256(raw).hexdigest(), 'documents':len(dataset['documents']), 'questions':len(rows),
              'answerable':18,'unanswerable':2,'metrics':{name:aggregate(name) for name in ('lexical','exact_substring')},
              'rows':rows,'real_model_calls':0,'real_world_quality_accepted':False,'provenance':dataset['provenance'],
              'limitation':'Same-author small synthetic fixture; lexical mechanism check only. No independent corpus or semantic paraphrase benchmark.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('documents','questions','metrics','real_world_quality_accepted')}))


if __name__ == '__main__':
    main()
