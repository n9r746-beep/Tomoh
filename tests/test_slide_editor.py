import tempfile, unittest,json
from unittest.mock import patch
from pathlib import Path
from fastapi.testclient import TestClient
from app.config import Settings,BASE_DIR
from app.main import create_app
from app.api import slide_routes

class SlideEditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        geometry={"width":1600,"height":900,"slides":{"29":{"number":29,"fields":[]},"30":{"number":30,"fields":[{"key":"achievement.P1_6.1","x":10,"y":10,"w":20,"h":10}]},"11":{"number":11,"fields":[]},"12":{"number":12,"fields":[]},"13":{"number":13,"fields":[{"key":"kpi.ATTRACTION_DIRECT_WEEKLY","x":10,"y":10,"w":10,"h":5}]}}}
        self.asset_patch=patch.object(slide_routes,"asset",side_effect=lambda name:json.dumps(geometry).encode() if name=="manifest.json" else b"RIFFtestWEBP")
        self.asset_patch.start();slide_routes.manifest.cache_clear()
        self.app=create_app(Settings(database_url="sqlite:///"+self.tmp.name+"/db.sqlite",template_pptx_path=Path("/vercel/master_template.pptx"),mapping_config_path=BASE_DIR/"config/mapping_config.json",migrations_dir=BASE_DIR/"migrations",output_dir=Path(self.tmp.name)/"out",auth_mode="header_dev"))
        self.c=TestClient(self.app);self.coord={"X-User-Id":"u-coord"}
        self.wk=self.c.post("/api/v1/weeks",headers=self.coord,json={"week_number":45,"fiscal_year":2026,"start_date":"2026-11-22","end_date":"2026-11-26"}).json()["reporting_week"]["id"]
        self.c.put("/api/v1/projects/proj-p1-6/contributors",headers=self.coord,json={"user_ids":["u-abdullah"]})
        self.base=f"/api/v1/weeks/{self.wk}/projects/proj-p1-6/slides"
    def tearDown(self):
        self.asset_patch.stop();slide_routes.manifest.cache_clear();self.tmp.cleanup()
    def test_private_background_and_geometry_permissions(self):
        self.assertEqual(self.c.get(self.base).status_code,401)
        self.assertEqual(self.c.get(self.base+"/30/background").status_code,401)
        self.assertEqual(self.c.get(self.base,headers={"X-User-Id":"u-mohammed"}).status_code,403)
        r=self.c.get(self.base,headers={"X-User-Id":"u-abdullah"});self.assertEqual(r.status_code,200,r.text)
        pages=r.json()["slides"];self.assertTrue(pages)
        fields=[f for p in pages for f in p["fields"]]
        self.assertIn("achievement.P1_6.1",[f["key"] for f in fields])
        self.assertTrue(all(f["w"]>0 and f["h"]>0 for f in fields))
        image=self.c.get(self.base+"/30/background",headers={"X-User-Id":"u-abdullah"})
        self.assertEqual(image.status_code,200);self.assertEqual(image.headers["content-type"],"image/webp")
        self.assertIn("no-store",image.headers["cache-control"])
        self.assertEqual(self.c.get(self.base+"/13/background",headers={"X-User-Id":"u-abdullah"}).status_code,404)
    def test_attraction_and_template_assets_are_not_static(self):
        r=self.c.get(f"/api/v1/weeks/{self.wk}/projects/proj-p1-1/slides",headers=self.coord)
        self.assertEqual(r.status_code,200)
        self.assertTrue(any(f["key"]=="kpi.ATTRACTION_DIRECT_WEEKLY" for p in r.json()["slides"] for f in p["fields"]))
        self.assertEqual(self.c.get("/static/slide_assets/slide-30.webp").status_code,404)
        self.assertEqual(self.c.get("/app/slide_assets/slide-30.webp").status_code,404)
