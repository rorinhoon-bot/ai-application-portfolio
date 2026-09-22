"""Prepare independent claim-rating sheets and summarize human labels offline.

This tool never generates labels, resolves disagreements, or declares quality passed.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


LABELS = {'supported', 'partially_supported', 'unsupported', 'unclear'}
SEVERITIES = {'none', 'minor', 'major', 'critical'}
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')


def read_json(path):
    data = Path(path).read_bytes()
    if len(data) > 2_000_000:
        raise ValueError('INPUT_TOO_LARGE')
    return json.loads(data.decode('utf-8'))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def manifest_info(value):
    if type(value) is not dict or set(value) != {'schema_version', 'claims'} or value['schema_version'] != 'g4-claims-v1':
        raise ValueError('MANIFEST_INVALID')
    claims = value['claims']
    if type(claims) is not list or not 1 <= len(claims) <= 200:
        raise ValueError('MANIFEST_INVALID')
    identifiers = set()
    for claim in claims:
        if type(claim) is not dict or set(claim) != {'claim_id', 'claim', 'evidence', 'limitations'}:
            raise ValueError('MANIFEST_INVALID')
        if type(claim['claim_id']) is not str or not IDENTIFIER.fullmatch(claim['claim_id']) or claim['claim_id'] in identifiers:
            raise ValueError('MANIFEST_INVALID')
        identifiers.add(claim['claim_id'])
        if (type(claim['claim']) is not str or not claim['claim'].strip() or len(claim['claim']) > 2000 or
                type(claim['evidence']) is not list or not 1 <= len(claim['evidence']) <= 10 or
                type(claim['limitations']) is not str or len(claim['limitations']) > 2000):
            raise ValueError('MANIFEST_INVALID')
        for evidence in claim['evidence']:
            if (type(evidence) is not dict or set(evidence) != {'source_id', 'text'} or
                    type(evidence['source_id']) is not str or not IDENTIFIER.fullmatch(evidence['source_id']) or
                    type(evidence['text']) is not str or not evidence['text'].strip() or len(evidence['text']) > 6000):
                raise ValueError('MANIFEST_INVALID')
    return identifiers


def sheet(manifest, reviewer_id):
    manifest_info(manifest)
    if type(reviewer_id) is not str or not IDENTIFIER.fullmatch(reviewer_id):
        raise ValueError('REVIEWER_INVALID')
    return {'schema_version': 'g4-rating-v1', 'manifest_sha256': digest(manifest), 'reviewer_id': reviewer_id,
            'ratings': [{'claim_id': claim['claim_id'], 'label': None, 'severity': None, 'note': ''}
                        for claim in manifest['claims']]}


def adjudication_sheet(manifest, adjudicator_id):
    manifest_info(manifest)
    if type(adjudicator_id) is not str or not IDENTIFIER.fullmatch(adjudicator_id):
        raise ValueError('ADJUDICATOR_INVALID')
    return {'schema_version': 'g4-adjudication-v1', 'manifest_sha256': digest(manifest),
            'adjudicator_id': adjudicator_id,
            'decisions': [{'claim_id': claim['claim_id'], 'label': None, 'severity': None, 'note': ''}
                          for claim in manifest['claims']]}


def validate_items(manifest, items):
    identifiers = manifest_info(manifest)
    if type(items) is not list:
        raise ValueError('RATING_INVALID')
    seen = set()
    for item in items:
        if type(item) is not dict or set(item) != {'claim_id', 'label', 'severity', 'note'}:
            raise ValueError('RATING_INVALID')
        if (type(item['claim_id']) is not str or item['claim_id'] not in identifiers or item['claim_id'] in seen or
                type(item['label']) is not str or item['label'] not in LABELS or
                type(item['severity']) is not str or item['severity'] not in SEVERITIES or
                type(item['note']) is not str or len(item['note']) > 1000 or
                (item['label'] != 'supported' and not item['note'].strip()) or
                (item['label'] == 'supported' and item['severity'] != 'none')):
            raise ValueError('RATING_INVALID')
        seen.add(item['claim_id'])
    if seen != identifiers:
        raise ValueError('RATING_INCOMPLETE')
    return {item['claim_id']: item for item in items}


def validate_rating(manifest, rating):
    if (type(rating) is not dict or set(rating) != {'schema_version', 'manifest_sha256', 'reviewer_id', 'ratings'} or
            rating['schema_version'] != 'g4-rating-v1' or rating['manifest_sha256'] != digest(manifest) or
            type(rating['reviewer_id']) is not str or not IDENTIFIER.fullmatch(rating['reviewer_id'])):
        raise ValueError('RATING_INVALID')
    return validate_items(manifest, rating['ratings'])


def validate_adjudication(manifest, adjudication):
    if (type(adjudication) is not dict or
            set(adjudication) != {'schema_version', 'manifest_sha256', 'adjudicator_id', 'decisions'} or
            adjudication['schema_version'] != 'g4-adjudication-v1' or
            adjudication['manifest_sha256'] != digest(manifest) or
            type(adjudication['adjudicator_id']) is not str or
            not IDENTIFIER.fullmatch(adjudication['adjudicator_id'])):
        raise ValueError('ADJUDICATION_INVALID')
    return validate_items(manifest, adjudication['decisions'])


def summarize(manifest, ratings, adjudication=None):
    manifest_info(manifest)
    if not 1 <= len(ratings) <= 2:
        raise ValueError('REVIEWER_COUNT')
    validated = []
    for rating in ratings:
        items = validate_rating(manifest, rating)
        validated.append((rating['reviewer_id'], items))
    if len({reviewer for reviewer, _ in validated}) != len(validated):
        raise ValueError('REVIEWER_DUPLICATE')
    by_reviewer = dict(validated)
    ids = [claim['claim_id'] for claim in manifest['claims']]
    counts = {reviewer: dict(sorted(Counter(item['label'] for item in values.values()).items()))
              for reviewer, values in by_reviewer.items()}
    output = {'schema_version': 'g4-human-rating-summary-v1', 'manifest_sha256': digest(manifest),
              'claims': len(ids), 'reviewers': sorted(by_reviewer), 'labels_by_reviewer': counts,
              'content_quality': 'not_accepted', 'judgment': 'requires_independent_adjudication'}
    if len(ratings) == 2:
        first, second = sorted(by_reviewer)
        disputed = [claim_id for claim_id in ids if by_reviewer[first][claim_id]['label'] !=
                    by_reviewer[second][claim_id]['label']]
        output.update(exact_label_agreement=(len(ids) - len(disputed)) / len(ids),
                      disputed_claim_ids=disputed)
    else:
        output.update(exact_label_agreement=None, disputed_claim_ids=None,
                      limitation='single_reviewer')
    if adjudication is not None:
        decided = validate_adjudication(manifest, adjudication)
        label_counts = dict(sorted(Counter(item['label'] for item in decided.values()).items()))
        output.update(judgment='adjudicated_descriptive_only',
                      adjudicator_id=adjudication['adjudicator_id'],
                      adjudicator_id_distinct=adjudication['adjudicator_id'] not in by_reviewer,
                      adjudicated_labels=label_counts,
                      supported_claim_rate=label_counts.get('supported', 0) / len(ids),
                      major_or_critical_unsupported=sum(
                          item['label'] == 'unsupported' and item['severity'] in ('major', 'critical')
                          for item in decided.values()))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reviewer-id')
    parser.add_argument('--adjudicator-id')
    parser.add_argument('--ratings', type=Path, nargs='+')
    parser.add_argument('--adjudication', type=Path)
    args = parser.parse_args()
    if sum(bool(value) for value in (args.reviewer_id, args.adjudicator_id, args.ratings)) != 1:
        parser.error('Specify one of --reviewer-id, --adjudicator-id, or --ratings')
    if args.adjudication and not args.ratings:
        parser.error('--adjudication requires --ratings')
    if args.output.resolve() in {path.resolve() for path in
                                 [args.manifest, *(args.ratings or []), *([args.adjudication] if args.adjudication else [])]}:
        parser.error('Output must not overwrite a manifest, rating sheet, or adjudication sheet')
    manifest = read_json(args.manifest)
    if args.reviewer_id:
        result = sheet(manifest, args.reviewer_id)
    elif args.adjudicator_id:
        result = adjudication_sheet(manifest, args.adjudicator_id)
    else:
        result = summarize(manifest, [read_json(path) for path in args.ratings],
                           read_json(args.adjudication) if args.adjudication else None)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'manifest_sha256': digest(manifest),
                      'content_quality': result.get('content_quality', 'not_scored')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
