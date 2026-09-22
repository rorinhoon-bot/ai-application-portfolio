"""Offline human-rating format and aggregation behavior with invented material."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from score_content import sheet, summarize, validate_rating


def invented_manifest():
    return {'schema_version': 'g4-claims-v1', 'claims': [
        {'claim_id': 'synthetic-a', 'claim': '方案甲支持离线读取。',
         'evidence': [{'source_id': 'doc-a-p1', 'text': '方案甲允许离线读取本地原创资料。'}],
         'limitations': '本机演示资料'},
        {'claim_id': 'synthetic-b', 'claim': '方案乙速度比甲快。',
         'evidence': [{'source_id': 'doc-b-p1', 'text': '方案乙处理原创资料。'}],
         'limitations': '没有速度对比实验'},
    ]}


class ContentScoringTests(unittest.TestCase):
    def test_independent_ratings_disagreement_and_no_automatic_acceptance(self):
        manifest = invented_manifest()
        first, second = sheet(manifest, 'rater-a'), sheet(manifest, 'rater-b')
        for rating in (first, second):
            rating['ratings'][0].update(label='supported', severity='none')
            rating['ratings'][1].update(label='unsupported', severity='major', note='证据未比较速度')
        second['ratings'][1].update(label='unclear', severity='minor', note='需要额外资料')
        report = summarize(manifest, [first, second])
        self.assertEqual(report['exact_label_agreement'], .5)
        self.assertEqual(report['disputed_claim_ids'], ['synthetic-b'])
        self.assertEqual(report['content_quality'], 'not_accepted')
        self.assertEqual(report['judgment'], 'requires_independent_adjudication')
        self.assertEqual(summarize(manifest, [first])['limitation'], 'single_reviewer')

    def test_rejects_missing_labels_stale_evidence_and_duplicate_reviewer(self):
        manifest = invented_manifest()
        rating = sheet(manifest, 'rater-a')
        with self.assertRaisesRegex(ValueError, 'RATING_INVALID'):
            summarize(manifest, [rating])
        for item in rating['ratings']:
            item.update(label='supported', severity='none')
        incomplete = copy.deepcopy(rating)
        incomplete['ratings'].pop()
        with self.assertRaisesRegex(ValueError, 'RATING_INCOMPLETE'):
            summarize(manifest, [incomplete])
        changed = copy.deepcopy(manifest)
        changed['claims'][0]['evidence'][0]['text'] = '新的资料内容'
        with self.assertRaisesRegex(ValueError, 'RATING_INVALID'):
            validate_rating(changed, rating)
        with self.assertRaisesRegex(ValueError, 'REVIEWER_DUPLICATE'):
            summarize(manifest, [rating, rating])

    def test_cli_prepare_and_summarize_on_local_files(self):
        with tempfile.TemporaryDirectory(prefix='g4-ratings-') as folder:
            root = Path(folder)
            manifest_path = root / 'manifest.json'
            manifest_path.write_text(json.dumps(invented_manifest(), ensure_ascii=False), encoding='utf-8')
            script = Path(__file__).resolve().parents[1] / 'score_content.py'
            for reviewer in ('rater-a', 'rater-b'):
                target = root / (reviewer + '.json')
                subprocess.run([sys.executable, '-B', str(script), '--manifest', str(manifest_path),
                                '--reviewer-id', reviewer, '--output', str(target)], check=True, capture_output=True)
                rating = json.loads(target.read_text(encoding='utf-8'))
                rating['ratings'][0].update(label='supported', severity='none')
                rating['ratings'][1].update(label='unsupported', severity='major', note='缺少测速证据')
                target.write_text(json.dumps(rating, ensure_ascii=False), encoding='utf-8')
            result = root / 'summary.json'
            subprocess.run([sys.executable, '-B', str(script), '--manifest', str(manifest_path), '--ratings',
                            str(root / 'rater-a.json'), str(root / 'rater-b.json'), '--output', str(result)],
                           check=True, capture_output=True)
            self.assertEqual(json.loads(result.read_text(encoding='utf-8'))['exact_label_agreement'], 1.0)
            self.assertEqual(json.loads(result.read_text(encoding='utf-8'))['content_quality'], 'not_accepted')
