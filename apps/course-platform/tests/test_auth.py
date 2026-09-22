"""Identity-mode HTTP behavior against new private state only; all data synthetic."""
import hashlib
import http.client
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain import AppError
from server import Server
from service import Service
from test_library import source
from test_platform import settled


class IdentityHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='course-auth-')
        self.root = Path(self.temp.name) / 'state'
        self.service = Service(self.root, auth_required=True)
        self.passwords = {}
        self.users = {}
        for username, role in (('localadmin','admin'),('alice','researcher'),('bobby','researcher'),
                               ('reviewa','reviewer'),('reviewb','reviewer')):
            password = secrets.token_urlsafe(18)
            self.passwords[username] = password
            self.users[username] = self.service.auth.create_user(username, password, role)
        self.server = Server(0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.sessions = {}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.service.close()
        self.temp.cleanup()

    def call(self, path, payload=None, who=None, *, token=None, csrf=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=20)
        attrs = dict(headers or {})
        if who:
            item = self.sessions[who]
            attrs.setdefault('Cookie', 'cp_session=' + (token or item['token']))
        if payload is not None:
            attrs.update({'Origin':f'http://127.0.0.1:{self.port}', 'Content-Type':'application/json',
                          'X-CSRF-Token':csrf if csrf is not None else
                          (self.sessions[who]['csrf'] if who else self.server.csrf)})
        connection.request('GET' if payload is None else 'POST', path,
                           None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8'), attrs)
        response = connection.getresponse()
        body = response.read()
        result = (response.status, dict(response.getheaders()),
                  json.loads(body) if body and response.getheader('Content-Type','').startswith('application/json') else body)
        connection.close()
        return result

    def login(self, who):
        status, headers, body = self.call('/api/auth/login',
            {'username':who,'password':self.passwords[who]})
        self.assertEqual(status, 200, body)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        token = headers['Set-Cookie'].split(';',1)[0].split('=',1)[1]
        session = self.call('/api/auth/session', who=None,
            headers={'Cookie':'cp_session='+token})[2]
        self.sessions[who] = {'token':token, 'csrf':session['csrf_token']}
        return session

    def import_doc(self, who, name):
        data = source(request_id=uuid.uuid4().hex,title=name,filename=name+'.md',
            source_ref='original:'+name,content=name+' tool calling human approval interrupt recovery checkpoint. '
            '工具调用经人工审批，故障恢复使用checkpoint。')
        status, _, item = self.call('/api/library/import', data, who)
        self.assertEqual(status, 200, item)
        return item

    def project(self, who='alice', reviewer='reviewa'):
        versions = [self.import_doc(who, who+'-甲'),self.import_doc(who, who+'-乙')]
        payload = {'request_id':uuid.uuid4().hex,'title':'合成项目 '+who,
            'question':'比较两个方案的工具调用、人工审批与故障恢复，明确证据和限制。',
            'constraints':['仅离线原创资料'], 'version_ids':[v['version_id'] for v in versions],
            'reviewer_id':self.users[reviewer]['user_id'], 'confirmed':True}
        status, _, project = self.call('/api/projects', payload, who)
        self.assertEqual(status, 201, project)
        return project, versions, payload

    def test_project_creation_rolls_back_access_failure_and_retry_is_idempotent(self):
        self.login('alice')
        versions = [self.import_doc('alice', '原子甲'), self.import_doc('alice', '原子乙')]
        payload = {'request_id': uuid.uuid4().hex, 'title': '原子创建验证',
                   'question': '比较两个方案的资料版本与审批边界，并说明离线演示限制。',
                   'constraints': ['原创合成资料'], 'version_ids': [v['version_id'] for v in versions],
                   'reviewer_id': self.users['reviewa']['user_id'], 'confirmed': True}
        with patch.object(self.service.auth, 'bind_project_in_transaction', side_effect=AppError('ACCESS_DENIED')):
            status, _, body = self.call('/api/projects', payload, 'alice')
        self.assertEqual(status, 403, body)
        with self.service.store.transaction() as connection:
            for table in ('research_projects', 'research_project_scopes', 'research_project_events', 'project_access'):
                self.assertEqual(connection.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0, table)
        status, _, project = self.call('/api/projects', payload, 'alice')
        self.assertEqual(status, 201, project)
        self.assertEqual(self.call('/api/projects', payload, 'alice')[2]['project_id'], project['project_id'])
        changed = {**payload, 'reviewer_id': self.users['reviewb']['user_id']}
        self.assertEqual(self.call('/api/projects', changed, 'alice')[2]['error']['code'], 'NOT_FOUND')
        with self.service.store.transaction() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM research_projects').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT count(*) FROM project_access').fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM access_audit WHERE action='project_bound'").fetchone()[0], 1)

    def test_auth_session_csrf_lockout_logout_and_workspace_marker(self):
        self.assertEqual(self.call('/api/tasks')[0], 401)
        self.assertEqual(self.call('/api/auth/session')[2]['authenticated'], False)
        for _ in range(5):
            self.assertEqual(self.call('/api/auth/login',{'username':'alice','password':'wrong'})[0], 401)
        self.assertEqual(self.call('/api/auth/login',
            {'username':'alice','password':self.passwords['alice']})[2]['error']['code'], 'LOGIN_LOCKED')
        session = self.login('bobby')
        self.assertEqual(session['identity']['role'], 'researcher')
        self.assertEqual(self.call('/api/projects',{'request_id':uuid.uuid4().hex},'bobby',csrf='wrong')[0],403)
        self.assertEqual(self.call('/api/tasks',who='bobby',headers={'Cookie':'cp_session=bad; cp_session=again'})[0],401)
        self.assertEqual(self.call('/api/auth/logout',{},'bobby')[0],200)
        self.assertEqual(self.call('/api/tasks',who='bobby')[0],401)
        self.login('reviewa')
        with self.service.store.transaction() as connection:
            connection.execute('UPDATE sessions SET absolute_until=? WHERE user_id=?',
                               (int(time.time())-1,self.users['reviewa']['user_id']))
        self.assertEqual(self.call('/api/tasks',who='reviewa')[0],401)
        with self.assertRaisesRegex(AppError,'STATE_UNSAFE'):
            Service(self.root)

    def test_project_document_and_task_authorization(self):
        for who in ('alice','bobby','reviewa','reviewb','localadmin'):
            self.login(who)
        project, versions, payload = self.project()
        self.assertEqual(self.call('/api/projects/'+project['project_id'],who='bobby')[0],404)
        self.assertEqual(self.call('/api/projects/'+project['project_id'],who='reviewb')[0],404)
        self.assertEqual(self.call('/api/projects/'+project['project_id'],who='reviewa')[0],200)
        self.assertEqual(self.call('/api/library/versions/'+versions[0]['version_id'],who='reviewa')[0],200)
        self.assertEqual(self.call('/api/library/versions/'+versions[0]['version_id'],who='reviewb')[0],404)
        self.assertEqual(self.call('/api/library/search',
            {'query':'checkpoint','document_ids':[versions[0]['document_id']],'top_k':5},'bobby')[0],404)
        self.assertEqual(self.call('/api/library/import',source(source_ref='original:alice-甲'), 'bobby')[0],404)
        invalid = source(request_id=uuid.uuid4().hex, source_ref='original:rollback-check')
        invalid['filename'] = '../invalid.md'
        self.assertEqual(self.call('/api/library/import', invalid, 'bobby')[0], 400)
        with self.service.store.transaction() as connection:
            self.assertIsNone(connection.execute('SELECT 1 FROM document_owners WHERE document_id=?',
                ('doc-' + hashlib.sha256(b'original:rollback-check').hexdigest()[:32],)).fetchone())
        self.assertEqual(self.call('/api/projects',payload,'bobby')[0],404)
        self.assertEqual(self.call('/api/projects',{**payload,'reviewer_id':self.users['reviewb']['user_id']},'alice')[0],404)
        self.assertEqual(self.call('/api/projects',payload,'reviewa')[0],403)
        task_payload={'request_id':uuid.uuid4().hex,'expected_contract_hash':project['contract_hash'],
            'candidates':[{'name':'方案甲','version_id':versions[0]['version_id']},
                          {'name':'方案乙','version_id':versions[1]['version_id']}], 'confirmed':True}
        status, _, task = self.call('/api/projects/'+project['project_id']+'/tasks',task_payload,'alice')
        self.assertEqual(status,202,task)
        item = settled(self.service,task['id'],180)
        self.assertEqual(item['status'],'NEEDS_HUMAN',item['last_error'])
        action={'request_id':uuid.uuid4().hex,'action':'approve','expected_hash':item['state']['request_hash'],
                'note':'审核者核对冻结范围'}
        self.assertEqual(self.call('/api/tasks/'+task['id']+'/actions',action,'alice')[0],403)
        self.assertEqual(self.call('/api/tasks/'+task['id']+'/actions',action,'reviewb')[0],404)
        self.assertEqual(self.call('/api/tasks/'+task['id']+'/revisions',{},'reviewa')[0],403)
        self.assertEqual(self.call('/api/tasks/'+task['id']+'/download',who='bobby')[0],404)
        self.assertEqual(self.call('/api/tasks/'+task['id'],who='reviewa')[0],200)
        self.assertEqual(self.call('/api/tasks',who='reviewb')[2]['tasks'],[])
        self.assertEqual(self.call('/api/tasks/'+task['id']+'/actions',action,'reviewa')[0],202)
        item = settled(self.service,task['id'],180)
        self.assertEqual(item['status'],'REPORT_NEEDS_HUMAN',item['last_error'])
        self.assertEqual(item['events'][-2]['details'].get('actor'),self.users['reviewa']['user_id'])
        with self.service.store.transaction() as connection:
            denied = connection.execute("SELECT count(*) FROM access_audit WHERE outcome IN ('ACCESS_DENIED','NOT_FOUND')").fetchone()[0]
        self.assertGreaterEqual(denied,7)
        self.assertEqual(self.call('/api/security/audit',who='reviewa')[0],403)
        status, _, audit = self.call('/api/security/audit',who='localadmin')
        self.assertEqual(status,200)
        self.assertGreaterEqual(len(audit['events']),denied)
        self.assertNotIn(self.passwords['alice'],json.dumps(audit))
        self.assertNotIn(self.sessions['reviewa']['token'],json.dumps(audit))
        self.assertEqual(self.call('/api/library/search',
            {'query':'x','document_ids':[{}],'top_k':5},'alice')[0],400)

    def test_reviewer_finishes_real_offline_delivery(self):
        self.login('alice')
        self.login('reviewa')
        project, versions, _ = self.project()
        status, _, task = self.call('/api/projects/'+project['project_id']+'/tasks',
            {'request_id':uuid.uuid4().hex,'expected_contract_hash':project['contract_hash'],
             'candidates':[{'name':'方案甲','version_id':versions[0]['version_id']},
                           {'name':'方案乙','version_id':versions[1]['version_id']}], 'confirmed':True},'alice')
        self.assertEqual(status,202,task)
        task = settled(self.service,task['id'],180)
        self.assertEqual(task['state']['model_call_count'],0)
        self.assertEqual(task['state']['tool_events'],[])
        def approve(item):
            return self.call('/api/tasks/'+item['id']+'/actions',
                {'request_id':uuid.uuid4().hex,'action':'approve',
                 'expected_hash':item['state']['request_hash' if item['status']=='NEEDS_HUMAN' else 'report_hash'],
                 'note':'审核者核对当前指纹与证据'}, 'reviewa')
        self.assertEqual(approve(task)[0],202)
        task = settled(self.service,task['id'],180)
        self.assertEqual(task['status'],'REPORT_NEEDS_HUMAN',task['last_error'])
        self.assertGreater(len(task['state']['tool_events']),0)
        old = task['state']['report_hash']
        revision={'request_id':uuid.uuid4().hex,'expected_hash':old,
            'summary':'人工修订：两方案证据仅支持本机离线设计演示，不能推断真实生产性能。',
            'limitations':['资料为合成示例，仍需独立内容评分。'],
            'note':'保留证据矩阵，仅修订摘要限制','confirmed':True}
        self.assertEqual(self.call('/api/tasks/'+task['id']+'/revisions',revision,'alice')[0],202)
        task=settled(self.service,task['id'],180)
        self.assertNotEqual(task['state']['report_hash'],old)
        self.assertEqual(self.call('/api/tasks/'+task['id']+'/actions',
            {'request_id':uuid.uuid4().hex,'action':'approve','expected_hash':old,
             'note':'旧版报告不应批准'},'reviewa')[2]['error']['code'],'STALE_APPROVAL')
        self.assertEqual(approve(task)[0],202)
        task=settled(self.service,task['id'],180)
        self.assertEqual(task['status'],'COMPLETED',task['last_error'])
        status, headers, archive = self.call('/api/tasks/'+task['id']+'/download',who='reviewa')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/zip')
        self.assertIn('attachment', headers['Content-Disposition'])
        owner_status, _, owner_archive = self.call('/api/tasks/'+task['id']+'/download',who='alice')
        self.assertEqual(owner_status, 200)
        self.assertEqual(hashlib.sha256(archive).digest(), hashlib.sha256(owner_archive).digest())
        bundle = Path(self.temp.name) / 'http-delivery.zip'
        bundle.write_bytes(archive)
        self.assertEqual(bundle.read_bytes(), archive)
        verifier = Path(__file__).resolve().parents[1] / 'frozen_bundle_cli.py'
        verified = subprocess.run([sys.executable, '-B', str(verifier), str(bundle)],
                                  capture_output=True, text=True, timeout=20)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertTrue(json.loads(verified.stdout)['bundle_consistent'])
        with self.service.store.transaction() as connection:
            downloaded_by = {row['user_id'] for row in connection.execute(
                "SELECT user_id FROM access_audit WHERE action='download' AND resource=?",
                ('/api/tasks/' + task['id'] + '/download',))}
        self.assertEqual(downloaded_by, {self.users['alice']['user_id'], self.users['reviewa']['user_id']})
        actors = [e['details'].get('actor') for e in task['events'] if e['kind']=='operation_requested']
        self.assertIn(self.users['alice']['user_id'],actors)
        self.assertIn(self.users['reviewa']['user_id'],actors)


if __name__ == '__main__':
    unittest.main()
