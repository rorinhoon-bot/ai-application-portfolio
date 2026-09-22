"""Real offline P1 tokenizer, P2 graph and P3 MCP through application jobs."""
import io
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain import AppError
from score_content import manifest_from_bundle, sheet, summarize, verify_manifest_bundle
from service import Service
from test_platform import settled
from test_library import source


class FrozenWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='frozen-workflow-')
        self.service = Service(Path(self.temp.name) / 'state')

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def prepare(self):
        versions = []
        for n in ('甲方案','乙方案'):
            doc = self.service.library.import_text(source(
                request_id=uuid.uuid4().hex, title=n, filename=f'{n}.md', source_ref=f'original:{n}',
                content=f'{n} tool calling human approval interrupt recovery checkpoint. '
                        '工具调用经人工审批，故障恢复使用checkpoint。'))
            versions.append(doc['version_id'])
        project = self.service.projects.create({'request_id':uuid.uuid4().hex,'title':'两个方案研究',
            'question':'比较两个方案的工具调用、人工审批与故障恢复，明确证据和限制。',
            'constraints':['仅离线原创资料'], 'version_ids':versions, 'confirmed':True})
        payload = {'request_id':uuid.uuid4().hex,'expected_contract_hash':project['contract_hash'],
            'candidates':[{'name':n,'version_id':v} for n,v in zip(('方案甲','方案乙'),versions)],'confirmed':True}
        return project,payload

    def action(self, task, action='approve'):
        return {'request_id':uuid.uuid4().hex,'action':action,
            'expected_hash':task['state']['request_hash' if task['status']=='NEEDS_HUMAN' else 'report_hash']
              if action!='recover' else '', 'note':'本机操作员核对当前范围或报告'}

    def test_real_offline_approval_revision_and_bundle(self):
        project,payload=self.prepare()
        created=self.service.create_project_task(project['project_id'],payload)
        task=settled(self.service,created['id'],180)
        self.assertIsNone(task['last_error'],task)
        self.assertEqual(task['status'],'NEEDS_HUMAN')
        self.assertEqual(task['state']['model_call_count'],0)
        self.assertEqual(task['state']['tool_events'],[])
        self.assertEqual(self.service.create_project_task(project['project_id'],payload)['id'],task['id'])
        self.service.operate(task['id'],self.action(task))
        task=settled(self.service,task['id'],180)
        self.assertIsNone(task['last_error'],task)
        self.assertEqual(task['status'],'REPORT_NEEDS_HUMAN')
        self.assertGreater(len(task['state']['tool_events']),0)
        old=task['state']['report_hash']
        revision={'request_id':uuid.uuid4().hex,'expected_hash':old,
            'summary':'人工修订：两方案证据仅支持本机离线设计演示，不能推断真实生产性能。',
            'limitations':['资料是原创合成示例，仍需独立内容评分。'],
            'note':'保留证据矩阵，只修改摘要和限制','confirmed':True}
        self.service.revise(task['id'],revision)
        task=settled(self.service,task['id'],180)
        self.assertIsNone(task['last_error'],task)
        self.assertEqual(task['state']['human_revision_count'],1)
        self.assertEqual(task['state']['report_revision'],2)
        self.assertNotEqual(task['state']['report_hash'],old)
        with self.assertRaisesRegex(AppError,'STALE_APPROVAL'):
            self.service.operate(task['id'],{'request_id':uuid.uuid4().hex,'action':'approve',
                'expected_hash':old,'note':'已经失效的旧报告'})
        self.service.operate(task['id'],self.action(task))
        task=settled(self.service,task['id'],180)
        self.assertIsNone(task['last_error'],task)
        self.assertEqual(task['status'],'COMPLETED')
        data=self.service.download(task['id'])
        self.assertEqual(data,self.service.download(task['id']))
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(archive.testzip(),None)
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['execution_hash'],task['execution']['execution_hash'])
            self.assertFalse(manifest['content_quality_passed'])
            self.assertEqual(json.loads(archive.read('state.json'))['report_hash'],task['state']['report_hash'])
            files={name:archive.read(name) for name in archive.namelist()}
        bundle=Path(self.temp.name)/'delivery.zip'
        bundle.write_bytes(data)
        verifier=Path(__file__).resolve().parents[1]/'frozen_bundle_cli.py'
        valid=subprocess.run([sys.executable,'-B',str(verifier),str(bundle)],capture_output=True,text=True,timeout=20)
        self.assertEqual(valid.returncode,0,valid.stdout+valid.stderr)
        self.assertTrue(json.loads(valid.stdout)['bundle_consistent'])
        bound=manifest_from_bundle(bundle)
        self.assertEqual(bound['report_hash'],task['state']['report_hash'])
        self.assertEqual(len(bound['claims']),len(task['state']['report']['evidence_cells']))
        self.assertTrue(any(claim['evidence'] for claim in bound['claims']))
        verify_manifest_bundle(bound,bundle)
        with self.assertRaisesRegex(ValueError,'BUNDLE_REQUIRED'):
            sheet(bound,'rater-a')
        changed=copy.deepcopy(bound)
        changed['claims'][0]['claim']='伪造的报告主张'
        with self.assertRaisesRegex(ValueError,'BUNDLE_MISMATCH'):
            sheet(changed,'rater-a',bundle)
        changed=copy.deepcopy(bound)
        with_evidence=next(claim for claim in changed['claims'] if claim['evidence'])
        with_evidence['evidence'][0]['text']='伪造的引用原文'
        with self.assertRaisesRegex(ValueError,'BUNDLE_MISMATCH'):
            sheet(changed,'rater-a',bundle)
        changed=copy.deepcopy(bound)
        changed['claims'].pop()
        with self.assertRaisesRegex(ValueError,'BUNDLE_MISMATCH'):
            sheet(changed,'rater-a',bundle)
        rating=sheet(bound,'rater-a',bundle)
        for item in rating['ratings']:
            item.update(label='unclear',severity='minor',note='合成材料只用于工具验证')
        self.assertEqual(summarize(bound,[rating],bundle=bundle)['source_binding'],'verified_bundle')
        scoring=Path(__file__).resolve().parents[1]/'score_content.py'
        bound_file=Path(self.temp.name)/'bound.json'
        prepared=subprocess.run([sys.executable,'-B',str(scoring),'--prepare-from-bundle',
                                 '--bundle',str(bundle),'--output',str(bound_file)],
                                capture_output=True,text=True,timeout=20)
        self.assertEqual(prepared.returncode,0,prepared.stderr)
        self.assertEqual(json.loads(bound_file.read_text(encoding='utf-8')),bound)
        rating_file=Path(self.temp.name)/'rating.json'
        ready=subprocess.run([sys.executable,'-B',str(scoring),'--manifest',str(bound_file),
                              '--bundle',str(bundle),'--reviewer-id','rater-a','--output',str(rating_file)],
                             capture_output=True,text=True,timeout=20)
        self.assertEqual(ready.returncode,0,ready.stderr)
        files['report.md']=b'tampered\n'
        altered=Path(self.temp.name)/'altered.zip'
        with zipfile.ZipFile(altered,'w') as archive:
            for name,content in files.items():archive.writestr(name,content)
        invalid=subprocess.run([sys.executable,'-B',str(verifier),str(altered)],capture_output=True,text=True,timeout=20)
        self.assertEqual(invalid.returncode,2)
        with self.assertRaisesRegex(AppError,'ENGINE_FAILED'):
            verify_manifest_bundle(bound,altered)
        self.service.operate(task['id'],self.action(task,'recover'))
        again=settled(self.service,task['id'],180)
        self.assertIsNone(again['last_error'],again)
        self.assertEqual(again['state']['report_hash'],task['state']['report_hash'])
        audit = next((self.service.root / 'tasks' / task['id'] / ('run-'+task['id'][5:]) / 'mcp-audit').glob('*-end.json'))
        audit.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(AppError,'ENGINE_FAILED'):
            self.service.download(task['id'])

    def test_invalid_candidate_and_stale_scope_leave_no_task(self):
        project,payload=self.prepare()
        bad=[{**payload,'confirmed':False},{**payload,'expected_contract_hash':'f'*64},
             {**payload,'candidates':payload['candidates'][:1]},
             {**payload,'candidates':[payload['candidates'][0]]*2},
             {**payload,'candidates':[{**payload['candidates'][0],'version_id':'ver-'+'f'*64},payload['candidates'][1]]}]
        for value in bad:
            with self.subTest(value=value),self.assertRaises(AppError):
                self.service.create_project_task(project['project_id'],value)
        self.assertEqual(self.service.store.list_tasks(),[])

    def test_unrelated_sources_fail_without_mcp_evidence(self):
        versions=[]
        for n in ('苹果','香蕉'):
            doc=self.service.library.import_text(source(request_id=uuid.uuid4().hex,title=n,
                filename=n+'.md',source_ref='original:'+n,content=n+' 水果甜度、储存温度与颜色。'))
            versions.append(doc['version_id'])
        project=self.service.projects.create({'request_id':uuid.uuid4().hex,'title':'无法支持的比较',
            'question':'比较工具调用和人工审批以及故障恢复的实现。','constraints':[],
            'version_ids':versions,'confirmed':True})
        task=self.service.create_project_task(project['project_id'],{'request_id':uuid.uuid4().hex,
            'expected_contract_hash':project['contract_hash'],'candidates':[
                {'name':'方案甲','version_id':versions[0]},{'name':'方案乙','version_id':versions[1]}], 'confirmed':True})
        task=settled(self.service,task['id'],180)
        self.assertEqual(task['status'],'NEEDS_HUMAN')
        self.service.operate(task['id'],self.action(task))
        task=settled(self.service,task['id'],180)
        self.assertEqual(task['status'],'FAILED')
        self.assertEqual(task['state']['tool_events'],[])
        self.assertIn('NO_VALID_EVIDENCE',task['state']['errors'])


if __name__=='__main__':
    unittest.main()
