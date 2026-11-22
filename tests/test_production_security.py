import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.config import BASE_DIR, Settings
from app.main import create_app

class ProductionSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.cfg=Settings(database_url='sqlite:///'+str(Path(self.temp.name)/'test.db'),template_pptx_path=Path('/vercel/master_template.pptx'),mapping_config_path=BASE_DIR/'config/mapping_config.json',migrations_dir=BASE_DIR/'migrations',output_dir=Path(self.temp.name)/'output',auth_mode='session_password')
        self.app=create_app(self.cfg)
        self.client=TestClient(self.app,base_url='https://testserver')
    def tearDown(self):
        self.temp.cleanup()
    def test_production_rejects_identity_header_and_hides_directory(self):
        self.assertEqual(self.client.get('/api/v1/auth/me',headers={'X-User-Id':'u-coord'}).status_code,401)
        self.assertEqual(self.client.get('/api/v1/auth/dev-users').status_code,404)
        self.assertEqual(self.client.get('/api/v1/projects').status_code,401)
    def test_session_requires_csrf_header_and_same_origin(self):
        self.client.cookies.set('tomoh_session',self.app.state.repo.create_session('u-coord')['token'])
        self.assertEqual(self.client.post('/api/v1/weeks',json={}).status_code,403)
        self.assertEqual(self.client.post('/api/v1/weeks',headers={'X-Requested-With':'XMLHttpRequest','Origin':'https://attacker.example'},json={}).status_code,403)
        self.assertEqual(self.client.post('/api/v1/weeks',headers={'X-Requested-With':'XMLHttpRequest','Origin':'https://testserver'},json={}).status_code,422)
