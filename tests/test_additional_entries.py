import hashlib
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from fastapi.testclient import TestClient
from lxml import etree
from pptx import Presentation
from app.config import BASE_DIR,Settings
from app.main import create_app
from app.engine.continuations import overflow_entries,append_continuations
from app.engine.mapping import MappingRegistry
from app.engine.ooxml_editor import PowerPointEngine

TEMPLATE=Path(os.environ.get('TOMOH_TEMPLATE_PPTX','/vercel/master_template.pptx'))

class AdditionalEntriesTests(unittest.TestCase):
    def test_employee_saves_reloads_and_exports_five_achievements_and_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=Settings(database_url='sqlite:///'+tmp+'/db.sqlite',template_pptx_path=TEMPLATE,mapping_config_path=BASE_DIR/'config/mapping_config.json',migrations_dir=BASE_DIR/'migrations',output_dir=Path(tmp)/'output',auth_mode='header_dev')
            app=create_app(cfg);c=TestClient(app)
            coord={'X-User-Id':'u-coord'};employee={'X-User-Id':'u-abdullah'}
            r=c.post('/api/v1/weeks',headers=coord,json={'week_number':45,'fiscal_year':2026,'start_date':'2026-11-22','end_date':'2026-11-26'})
            self.assertEqual(r.status_code,201);wk=r.json()['reporting_week']['id']
            payload={'project_id':'proj-p1-6','submission_status':'draft','achievements':[{'slot_index':i,'content_ar':f'UniqueAchievement{i}'} for i in range(1,6)],'upcoming_tasks':[{'sequence_no':i,'title_ar':f'UniqueTask{i}','task_status':'جاري'} for i in range(1,6)]}
            saved=c.put(f'/api/v1/weeks/{wk}/submissions/proj-p1-6',headers=employee,json=payload)
            self.assertEqual(saved.status_code,200,saved.text)
            loaded=c.get(f'/api/v1/weeks/{wk}/projects/proj-p1-6',headers=employee).json()['current']
            self.assertEqual(len(loaded['achievements']),5);self.assertEqual(len(loaded['upcoming_tasks']),5)
            self.assertEqual(c.put(f'/api/v1/weeks/{wk}/submissions/proj-p1-3',headers=employee,json={**payload,'project_id':'proj-p1-3'}).status_code,403)
            generated=c.post(f'/api/v1/weeks/{wk}/generate',headers=coord,json={'allow_incomplete':True})
            self.assertEqual(generated.status_code,201,generated.text)
            data=generated.json();self.assertEqual(data['generation']['status'],'succeeded')
            self.assertEqual(data['validation']['structural']['continuation_slides'],2)
            path=Path(data['generation']['output_pptx_path'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),data['generation']['output_sha256'])
            presentation=Presentation(str(path));self.assertEqual(len(presentation.slides),67)
            text='\n'.join(shape.text for slide in presentation.slides for shape in slide.shapes if shape.has_text_frame)
            for i in range(1,6):
                self.assertIn(f'UniqueAchievement{i}',text);self.assertIn(f'UniqueTask{i}',text)

    def test_continuation_preserves_existing_slide_and_asset_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'base.pptx';path.write_bytes(TEMPLATE.read_bytes())
            with zipfile.ZipFile(path) as z:before={n:z.read(n) for n in z.namelist()}
            groups=[(30,'الجهات الممكنة','achievement',[(i,'إنجاز إضافي '+str(i)) for i in range(3,11)])]
            self.assertEqual(append_continuations(path,groups),2)
            with zipfile.ZipFile(path) as z:
                for name,content in before.items():
                    if name not in ('ppt/presentation.xml','ppt/_rels/presentation.xml.rels','[Content_Types].xml'):
                        self.assertEqual(z.read(name),content,name)
            self.assertEqual(len(Presentation(str(path)).slides),67)
