"""Prepare and check an evidence-bound human review of report-wide coverage.

This tool does not grade the report or establish reviewer independence.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from score_content import IDENTIFIER, digest, read_json


CHECKS = (
    ('summary_support', '逐句核对摘要：每个可核验陈述是否有对应来源？记录矩阵外主张。'),
    ('recommendation', '推荐和决策状态是否与已读证据一致？'),
    ('omissions_conflicts', '对照冻结资料与研究问题，是否遗漏关键证据、冲突或反例？'),
    ('unknown_scope', '未知单元、证据缺失和资料外内容是否被过度推断？'),
    ('limitations', '来源范围、脚本模型与适用限制是否充分披露？'),
)
STATUSES = {'adequate', 'concern', 'unclear'}


def material_from_bundle(bundle):
    from frozen_bundle_cli import verified_content

    content, bundle_hash, _ = verified_content(bundle)
    state = json.loads(content['state.json'])
    report = state['report']
    cells = [
        {'cell_id': f'cell-{index:03d}',
         **{key: cell[key] for key in ('candidate_id', 'dimension_id', 'status', 'claim', 'caveat', 'evidence_ids')}}
        for index, cell in enumerate(report['evidence_cells'], 1)
    ]
    cited = {evidence_id for cell in cells for evidence_id in cell['evidence_ids']}
    evidence = sorted(state['evidence'], key=lambda item: item['evidence_id'])
    return {
        'schema_version': 'g4-report-material-v1', 'delivery_sha256': bundle_hash,
        'report_hash': state['report_hash'], 'research_question': state['request']['research_question'],
        'report': {key: report[key] for key in
                   ('executive_summary', 'recommendation', 'decision_status', 'limitations')},
        'cells': cells,
        'evidence': [{key: item[key] for key in
                      ('evidence_id', 'source_id', 'candidate_id', 'locator', 'excerpt', 'content_sha256')}
                     for item in evidence],
        'uncited_evidence_ids': sorted({item['evidence_id'] for item in evidence} - cited),
        'review_criteria': [{'check_id': check_id, 'question': question} for check_id, question in CHECKS],
    }


def prepare(bundle, reviewer_id):
    if type(reviewer_id) is not str or not IDENTIFIER.fullmatch(reviewer_id):
        raise ValueError('REVIEWER_INVALID')
    material = material_from_bundle(bundle)
    return {'schema_version': 'g4-coverage-review-v1', 'material_sha256': digest(material),
            'material': material, 'reviewer_id': reviewer_id,
            'answers': [{'check_id': check_id, 'status': None, 'note': ''} for check_id, _ in CHECKS]}


def validate(review, bundle):
    if (type(review) is not dict or set(review) !=
            {'schema_version', 'material_sha256', 'material', 'reviewer_id', 'answers'} or
            review['schema_version'] != 'g4-coverage-review-v1' or
            type(review['reviewer_id']) is not str or not IDENTIFIER.fullmatch(review['reviewer_id'])):
        raise ValueError('REVIEW_INVALID')
    material = material_from_bundle(bundle)
    if review['material'] != material or review['material_sha256'] != digest(material):
        raise ValueError('BUNDLE_MISMATCH')
    answers = review['answers']
    if type(answers) is not list or len(answers) != len(CHECKS):
        raise ValueError('REVIEW_INCOMPLETE')
    expected = {check_id for check_id, _ in CHECKS}
    seen = set()
    for item in answers:
        if type(item) is not dict or set(item) != {'check_id', 'status', 'note'}:
            raise ValueError('REVIEW_INVALID')
        if (type(item['check_id']) is not str or item['check_id'] not in expected or
                item['check_id'] in seen or type(item['status']) is not str or
                item['status'] not in STATUSES or type(item['note']) is not str or
                len(item['note']) > 2000 or
                (item['status'] != 'adequate' and not item['note'].strip())):
            raise ValueError('REVIEW_INVALID')
        seen.add(item['check_id'])
    if seen != expected:
        raise ValueError('REVIEW_INCOMPLETE')
    counts = Counter(item['status'] for item in answers)
    return {'schema_version': 'g4-coverage-summary-v1', 'material_sha256': digest(material),
            'delivery_sha256': material['delivery_sha256'], 'reviewer_id': review['reviewer_id'],
            'reviewer_identity_verified': False, 'source_binding': 'verified_bundle',
            'checks': len(CHECKS), 'status_counts': dict(sorted(counts.items())),
            'concern_check_ids': [item['check_id'] for item in answers if item['status'] == 'concern'],
            'content_quality': 'not_accepted', 'judgment': 'human_worksheet_descriptive_only'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--reviewer-id')
    group.add_argument('--review', type=Path)
    args = parser.parse_args()
    if args.output.resolve() in {path.resolve() for path in (args.bundle, args.review) if path}:
        parser.error('Output must not overwrite an input file')
    result = prepare(args.bundle, args.reviewer_id) if args.reviewer_id else validate(
        read_json(args.review), args.bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'content_quality': 'not_accepted'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
