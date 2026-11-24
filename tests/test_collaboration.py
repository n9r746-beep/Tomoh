import os,tempfile,unittest,zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from pptx import Presentation
from app.main import create_app
from app.config import BASE_DIR,Settings

class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        settings=Settings(database_url='sqlite:///'+self.tmp.name+'/test.db',template_pptx_path=Path(os.environ.get('TOMOH_TEMPLATE_PPTX','/vercel/master_template.pptx')),mapping_config_path=BASE_DIR/'config/mapping_config.json',migrations_dir=BASE_DIR/'migrations',output_dir=Path(self.tmp.name)/'out',auth_mode='header_dev')
        self.app=create_app(settings);self.c=TestClient(self.app);self.coord={'X-User-Id':'u-coord'}
        r=self.c.post('/api/v1/admin/users',headers=self.coord,json={'email':'third@example.test','full_name_ar':'الموظف الثالث','role':'employee'})
        self.assertEqual(r.status_code,201,r.text);self.ids=['u-abdullah','u-fahad',r.json()['user']['id']]
        r=self.c.put('/api/v1/projects/proj-p1-6/contributors',headers=self.coord,json={'user_ids':self.ids});self.assertEqual(r.status_code,200,r.text)
        r=self.c.post('/api/v1/weeks',headers=self.coord,json={'week_number':45,'fiscal_year':2026,'start_date':'2026-11-22','end_date':'2026-11-26'})
        self.wk=r.json()['reporting_week']['id']
    def tearDown(self):self.tmp.cleanup()
    def save(self,uid,text,version=None,kpis=None):
        return self.c.put(f'/api/v1/weeks/{self.wk}/submissions/proj-p1-6',headers={'X-User-Id':uid},json={'project_id':'proj-p1-6','expected_version':version,'submission_status':'draft','achievements':[{'slot_index':1,'content_ar':text}],'upcoming_tasks':[{'sequence_no':1,'title_ar':text+' task','task_status':'جاري'}],'kpis':kpis or []})
    def review(self,**kwargs):return self.c.post(f'/api/v1/weeks/{self.wk}/submissions/proj-p1-6/review',headers=self.coord,json={'status':'approved',**kwargs})
    def detail(self,uid):return self.c.get(f'/api/v1/weeks/{self.wk}/projects/proj-p1-6',headers={'X-User-Id':uid}).json()['current']
    def test_three_independent_updates_approval_freeze_and_export(self):
        for i,uid in enumerate(self.ids):self.assertEqual(self.save(uid,f'UniqueEmployee{i}').status_code,200)
        for i,uid in enumerate(self.ids):
            d=self.detail(uid);self.assertEqual([a['content_ar'] for a in d['achievements']],[f'UniqueEmployee{i}']);self.assertEqual(d['submission']['version'],1)
        self.assertEqual(self.save(self.ids[1],'SecondRevised',1).status_code,200)
        self.assertEqual(self.detail(self.ids[0])['submission']['version'],1)
        review=self.c.get(f'/api/v1/weeks/{self.wk}/projects/proj-p1-6/contributions',headers=self.coord).json()
        self.assertEqual(len(review['contributors']),3)
        self.assertEqual(self.c.get(f'/api/v1/weeks/{self.wk}/projects/proj-p1-6/contributions',headers={'X-User-Id':self.ids[0]}).status_code,403)
        approved=self.review(expected_versions=review['expected_versions']);self.assertEqual(approved.status_code,200,approved.text)
        self.assertEqual(approved.json()['submission']['reviewed_count'],3)
        self.assertEqual(self.save(self.ids[0],'ForbiddenOverwrite',1).status_code,409)
        report=self.c.post(f'/api/v1/weeks/{self.wk}/generate',headers=self.coord,json={'allow_incomplete':True})
        self.assertEqual(report.status_code,201,report.text)
        text='\n'.join(sh.text for sl in Presentation(report.json()['generation']['output_pptx_path']).slides for sh in sl.shapes if sh.has_text_frame)
        for expected in ['UniqueEmployee0','SecondRevised','UniqueEmployee2']:self.assertIn(expected,text)
        reopened=self.c.post(f'/api/v1/weeks/{self.wk}/submissions/proj-p1-6/review',headers=self.coord,json={'status':'changes_requested','reviewer_notes_ar':'استكمال التحديث'})
        self.assertEqual(reopened.status_code,200,reopened.text)
        self.assertEqual(self.save(self.ids[0],'AfterReopen',1).status_code,200)
        self.assertEqual(self.detail(self.ids[1])['achievements'][0]['content_ar'],'SecondRevised')
    def test_concurrent_saves_and_stale_review_are_rejected(self):
        for uid in self.ids:self.assertEqual(self.save(uid,'Initial').status_code,200)
        before=self.c.get(f'/api/v1/weeks/{self.wk}/projects/proj-p1-6/contributions',headers=self.coord).json()['expected_versions']
        with ThreadPoolExecutor(2) as pool:
            outcomes=list(pool.map(lambda t:self.save(self.ids[0],t,1).status_code,['FirstWinner','SecondWinner']))
        self.assertEqual(sorted(outcomes),[200,409])
        self.assertEqual(self.review(expected_versions=before).status_code,409)
        self.assertEqual(self.detail(self.ids[1])['submission']['version'],1)
    def test_numbers_are_independent_and_conflicts_require_explicit_source(self):
        for i,uid in enumerate(self.ids):
            r=self.save(uid,f'KpiUser{i}',kpis=[{'kpi_code':'ENABLERS_EVENTS','numeric_value':i+1,'denominator_value':25}]);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual([self.detail(uid)['kpis'][0]['numeric_value'] for uid in self.ids],[1,2,3])
        self.assertEqual(self.review().status_code,409)
        approved=self.review(kpi_source_user_id=self.ids[1]);self.assertEqual(approved.status_code,200,approved.text)
        bundle=self.app.state.repo.get_week_bundle(self.wk)
        self.assertEqual(next(k for k in bundle['kpis'] if k['kpi_code']=='ENABLERS_EVENTS')['numeric_value'],2)
        self.assertEqual(len(bundle['individual_kpis']),3)
    def test_transaction_rollback_and_author_preserving_carry_forward(self):
        self.assertEqual(self.save(self.ids[0],'KeepMe').status_code,200)
        bad=self.save(self.ids[0],'ShouldRollback',1,kpis=[{'kpi_code':'INVALID_CODE','numeric_value':1}])
        self.assertGreaterEqual(bad.status_code,400)
        self.assertEqual(self.detail(self.ids[0])['submission']['version'],1)
        self.assertEqual(self.detail(self.ids[0])['achievements'][0]['content_ar'],'KeepMe')
        self.assertEqual(self.save(self.ids[1],'OtherOwner').status_code,200)
        r=self.c.post('/api/v1/weeks',headers=self.coord,json={'week_number':46,'fiscal_year':2026,'start_date':'2026-11-29','end_date':'2026-12-03','carry_forward_from_week_id':self.wk})
        self.assertEqual(r.status_code,201,r.text);new_id=r.json()['reporting_week']['id']
        for uid,expected in [(self.ids[0],'KeepMe task'),(self.ids[1],'OtherOwner task')]:
            d=self.c.get(f'/api/v1/weeks/{new_id}/projects/proj-p1-6',headers={'X-User-Id':uid}).json()['current']
            self.assertEqual([t['title_ar'] for t in d['upcoming_tasks']],[expected]);self.assertEqual(d['achievements'],[])
    def test_attraction_section_has_inputs_and_real_slide_mapping(self):
        project=self.app.state.repo.get_project('proj-p1-1');self.assertEqual(project['project_code'],'P1_1')
        cfg=__import__('json').loads(project['section_config_json']);self.assertEqual(cfg['slides'],[11,12,13])
        assignment=self.c.put('/api/v1/projects/proj-p1-1/contributors',headers=self.coord,json={'user_ids':[self.ids[0]]});self.assertEqual(assignment.status_code,200)
        r=self.c.put(f'/api/v1/weeks/{self.wk}/submissions/proj-p1-1',headers={'X-User-Id':self.ids[0]},json={'project_id':'proj-p1-1','achievements':[{'slot_index':1,'content_ar':'AttractionVerified'}],'upcoming_tasks':[{'sequence_no':1,'title_ar':'AttractionNextTask','task_status':'جاري'}],'kpis':[{'kpi_code':'ATTRACTION_DIRECT_WEEKLY','numeric_value':77}]})
        self.assertEqual(r.status_code,200,r.text)
        report=self.c.post(f'/api/v1/weeks/{self.wk}/generate',headers=self.coord,json={'allow_incomplete':True});self.assertEqual(report.status_code,201,report.text)
        presentation=Presentation(report.json()['generation']['output_pptx_path']);slide13=' '.join(t.text for t in presentation.slides[12]._element.xpath('.//a:t') if t.text)
        self.assertIn('AttractionVerified',slide13);self.assertIn('77',slide13)
        all_text=' '.join(s.text for sl in presentation.slides for s in sl.shapes if s.has_text_frame);self.assertIn('AttractionNextTask',all_text)

    def test_multiple_news_authors_keep_their_own_entries(self):
        assigned=self.c.put('/api/v1/projects/proj-news/contributors',headers=self.coord,json={'user_ids':self.ids});self.assertEqual(assigned.status_code,200)
        for i,uid in enumerate(self.ids):
            r=self.c.put(f'/api/v1/weeks/{self.wk}/submissions/proj-news',headers={'X-User-Id':uid},json={'project_id':'proj-news','news':[{'slot_index':1,'body_ar':f'NewsAuthor{i}'}]})
            self.assertEqual(r.status_code,200,r.text)
            detail=self.c.get(f'/api/v1/weeks/{self.wk}/projects/proj-news',headers={'X-User-Id':uid}).json()['current']
            self.assertEqual([n['body_ar'] for n in detail['news']],[f'NewsAuthor{i}'])
        report=self.c.post(f'/api/v1/weeks/{self.wk}/generate',headers=self.coord,json={'allow_incomplete':True});self.assertEqual(report.status_code,201,report.text)
        presentation=Presentation(report.json()['generation']['output_pptx_path'])
        text=' '.join(t.text for sl in presentation.slides for t in sl._element.xpath('.//a:t') if t.text)
        for i in range(3):self.assertIn(f'NewsAuthor{i}',text)

    def test_each_conflicting_kpi_can_use_a_different_source(self):
        for i,uid in enumerate(self.ids):
            r=self.save(uid,f'Conflicting{i}',kpis=[{'kpi_code':'ENABLERS_EVENTS','numeric_value':i+1,'denominator_value':25},{'kpi_code':'ENABLERS_ACTIVATED','numeric_value':i+5,'denominator_value':15}]);self.assertEqual(r.status_code,200)
        r=self.review(kpi_sources={'ENABLERS_EVENTS':self.ids[0],'ENABLERS_ACTIVATED':self.ids[1]})
        self.assertEqual(r.status_code,200,r.text)
        values={r['kpi_code']:r['numeric_value'] for r in self.app.state.repo.get_week_bundle(self.wk)['kpis']}
        self.assertEqual(values['ENABLERS_EVENTS'],1);self.assertEqual(values['ENABLERS_ACTIVATED'],6)
