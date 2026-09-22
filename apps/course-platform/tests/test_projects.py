"""Frozen project contracts tested through persistence and real HTTP boundaries."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain import AppError
from library import Library
from projects import ResearchProjects
from store import Store
import test_library as fixtures
source = fixtures.source


def project(version, **updates):
    return {'request_id': uuid.uuid4().hex, 'title': '恢复技术选型',
            'question': '比较项目所选资料中的断点恢复设计及其限制。',
            'constraints': ['仅本机离线运行'], 'version_ids': [version], 'confirmed': True, **updates}


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'state'
        self.store = Store(self.root)
        self.library = Library(self.store)
        self.projects = ResearchProjects(self.store)
        self.original = self.library.import_text(source(content='retiredword 原始恢复设计'))
        self.payload = project(self.original['version_id'])

    def tearDown(self):
        self.temp.cleanup()

    def test_create_reopen_and_audit(self):
        saved = self.projects.create(self.payload)
        reopened = ResearchProjects(Store(self.root)).get(saved['project_id'])
        self.assertEqual(saved, {k: v for k, v in reopened.items() if k != 'events'})
        self.assertEqual(reopened['events'][0]['details']['contract_hash'], saved['contract_hash'])
        self.assertFalse(saved['engine_started'])
        self.assertFalse(saved['report_bound'])
        self.assertEqual(saved['manifest'][0]['content_hash'], self.original['content_hash'])
        self.assertEqual(self.store.list_tasks(), [])

    def test_repeat_conflict_and_concurrency(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(self.projects.create, [self.payload, self.payload]))
        self.assertEqual(replies[0], replies[1])
        self.assertEqual(len(self.projects.list()), 1)
        self.assertEqual(len(self.projects.get(replies[0]['project_id'])['events']), 1)
        with self.assertRaisesRegex(AppError, 'PROJECT_CONFLICT'):
            self.projects.create({**self.payload, 'constraints': ['不同项目约束']})

    def test_frozen_search_does_not_drift_after_source_update(self):
        saved = self.projects.create(self.payload)
        self.library.import_text(source(content='updatedword 新版策略', expected_version=self.original['version_id']))
        result = self.projects.search(saved['project_id'], {'query': 'retiredword', 'top_k': 5})
        self.assertEqual(result['results'][0]['version_id'], self.original['version_id'])
        self.assertEqual(result['contract_hash'], saved['contract_hash'])
        self.assertEqual(self.projects.search(saved['project_id'], {'query': 'updatedword', 'top_k': 5})['results'], [])
        self.assertEqual(self.projects.get(saved['project_id'])['manifest'], saved['manifest'])
        self.assertEqual(self.library.search({'query': 'retiredword', 'document_ids': [], 'top_k': 5})['results'], [])

    def test_binding_rejects_outside_version_wrong_chunk_and_hash(self):
        saved = self.projects.create(self.payload)
        chunk = self.original['chunks'][0]
        valid = {key: chunk[key] for key in ('chunk_id', 'content_hash')}
        valid['version_id'] = self.original['version_id']
        result = self.projects.evidence(saved['project_id'], valid)
        self.assertEqual(result['evidence']['text'], chunk['text'])
        self.assertTrue(result['binding_verified'])
        self.assertFalse(result['content_quality_accepted'])
        for change in ({'version_id': 'ver-' + 'a' * 64}, {'content_hash': 'b' * 64}, {'chunk_id': 'missing'}):
            with self.subTest(change=change), self.assertRaisesRegex(AppError, 'PROJECT_EVIDENCE'):
                self.projects.evidence(saved['project_id'], {**valid, **change})
        with self.assertRaises(AppError):
            self.projects.evidence(saved['project_id'], {**valid, 'text': '伪造引文'})

    def test_bad_contracts_leave_no_rows(self):
        for change in ({'confirmed': False}, {'confirmed': 1}, {'extra': 'field'}, {'title': '\ud800x'},
                       {'question': 'invalid\x01 question'}, {'constraints': ['重复约束', ' 重复约束 ']},
                       {'constraints': [1]}, {'constraints': ['合法约束'] * 9}, {'version_ids': []},
                       {'version_ids': [True]}, {'version_ids': [self.original['version_id']] * 2},
                       {'version_ids': ['../../data']}, {'version_ids': ['ver-' + 'a' * 64]}):
            with self.subTest(change=change), self.assertRaises(AppError):
                self.projects.create({**self.payload, **change})
        self.assertEqual(self.projects.list(), [])

    def test_same_document_multiple_versions_rejected(self):
        newer = self.library.import_text(source(content='新版内容', expected_version=self.original['version_id']))
        with self.assertRaisesRegex(AppError, 'PROJECT_CONTRACT'):
            self.projects.create({**self.payload, 'version_ids': [self.original['version_id'], newer['version_id']]})

    def test_capacity_does_not_break_retry_or_add_audit(self):
        saved = self.projects.create(self.payload)
        with patch('projects.MAX_PROJECTS', 1):
            self.assertEqual(self.projects.create(self.payload), saved)
            with self.assertRaisesRegex(AppError, 'PROJECT_LIMIT'):
                self.projects.create({**self.payload, 'request_id': uuid.uuid4().hex})
        self.assertEqual(len(self.projects.list()), 1)

    def test_scope_hash_and_source_integrity_fail_closed(self):
        saved = self.projects.create(self.payload)
        with self.store.transaction() as connection:
            connection.execute('UPDATE research_projects SET title=?', ('未经授权改名',))
        with self.assertRaisesRegex(AppError, 'PROJECT_INTEGRITY'):
            self.projects.get(saved['project_id'])

    def test_modified_source_body_and_chunks_rejected(self):
        saved = self.projects.create(self.payload)
        with self.store.transaction() as connection:
            connection.execute('UPDATE library_versions SET content=?', ('损坏内容',))
        with self.assertRaisesRegex(AppError, 'PROJECT_INTEGRITY'):
            self.projects.search(saved['project_id'], {'query': '恢复', 'top_k': 3})
        with self.store.transaction() as connection:
            connection.execute('UPDATE library_versions SET content=?,chunks_json=?', (self.original['content'], '[]'))
        with self.assertRaisesRegex(AppError, 'PROJECT_INTEGRITY'):
            self.projects.search(saved['project_id'], {'query': '恢复', 'top_k': 3})

    def test_empty_search_and_invalid_inputs(self):
        saved = self.projects.create(self.payload)
        for query in ('', 'zzzz-no-evidence'):
            self.assertEqual(self.projects.search(saved['project_id'], {'query': query, 'top_k': 2})['results'], [])
        for payload in ({'query': '恢复', 'top_k': True}, {'query': '恢复', 'top_k': 21},
                        {'query': '\ud800', 'top_k': 2}, {'query': '恢复', 'top_k': 2, 'version_ids': []}):
            with self.assertRaises(AppError):
                self.projects.search(saved['project_id'], payload)

    def test_contract_hash_is_order_independent_for_sources(self):
        other = self.library.import_text(source(source_ref='original:other'))
        one = self.projects.create({**self.payload, 'version_ids': [other['version_id'], self.original['version_id']]})
        two = self.projects.create({**self.payload, 'version_ids': [self.original['version_id'], other['version_id']]})
        self.assertEqual(one, two)


class ProjectHTTPTests(unittest.TestCase):
    setUp = fixtures.LibraryHTTPTests.setUp
    tearDown = fixtures.LibraryHTTPTests.tearDown
    call = fixtures.LibraryHTTPTests.call

    def test_create_detail_search_and_verify_without_engine(self):
        item = json.loads(self.call('/api/library/import', source())[1])
        status, raw = self.call('/api/projects', project(item['version_id']))
        self.assertEqual(status, 201)
        saved = json.loads(raw)
        url = '/api/projects/' + saved['project_id']
        self.assertEqual(self.call(url)[0], 200)
        self.assertEqual(len(json.loads(self.call('/api/projects')[1])['projects']), 1)
        result = json.loads(self.call(url + '/search', {'query': '断点恢复', 'top_k': 2})[1])
        record = result['results'][0]
        verified = self.call(url + '/evidence', {key: record[key] for key in ('version_id', 'chunk_id', 'content_hash')})
        self.assertTrue(json.loads(verified[1])['binding_verified'])
        self.assertEqual(self.service.store.list_tasks(), [])
        self.assertEqual(self.call('/projects.js')[0], 200)

    def test_mutation_guards_and_stable_errors(self):
        item = json.loads(self.call('/api/library/import', source())[1])
        payload = project(item['version_id'])
        self.assertEqual(self.call('/api/projects', payload, {'X-CSRF-Token': 'bad'})[0], 403)
        self.assertEqual(self.call('/api/projects', payload, {'Origin': 'https://attacker.invalid'})[0], 403)
        self.assertEqual(self.call('/api/projects', {**payload, 'confirmed': 1})[0], 400)
        self.assertEqual(self.call('/api/projects', {**payload, 'question': 'a' * 9000})[0], 400)
        self.assertEqual(self.call('/api/projects/../../workspace.sqlite3')[0], 404)
        self.assertEqual(json.loads(self.call('/api/projects')[1])['projects'], [])


if __name__ == '__main__':
    unittest.main()
