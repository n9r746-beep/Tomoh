"""
Phase 2 Complete Automated & 12-Step Final Acceptance Test Suite.
Covers session auth, RBAC, 3-employee isolation, draft/submit/review lifecycle,
reminders, disabled AI contract, secure image upload, PPTX generation & download,
slide data verification, editability, snapshot archiving, and historical immutability.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from lxml import etree
from PIL import Image
from pptx import Presentation

from app.config import BASE_DIR, Settings
from app.main import create_app

TEMPLATE_PPTX = Path(__import__("os").environ.get("TOMOH_TEMPLATE_PPTX", "/vercel/master_template.pptx"))
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


class TomohPhase2AcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="tomoh_p2_")
        self.tmp_path = Path(self.tmpdir.name)
        self.settings = Settings(
            database_url=f"sqlite:///{self.tmp_path / 'p2_test.db'}",
            template_pptx_path=TEMPLATE_PPTX,
            mapping_config_path=BASE_DIR / "config" / "mapping_config.json",
            migrations_dir=BASE_DIR / "migrations",
            output_dir=self.tmp_path / "generated",
            uploads_dir=self.tmp_path / "uploads",
            frontend_dir=BASE_DIR / "frontend",
            auth_mode="header_dev",
            enable_visual_validation=False,
            ai_assistant_enabled=False,
        )
        self.app = create_app(self.settings)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _login_client(self, user_id: str) -> TestClient:
        c = TestClient(self.app, headers={"X-Requested-With":"XMLHttpRequest"})
        r = c.post("/api/v1/auth/login", json={"user_id": user_id})
        self.assertEqual(r.status_code, 200, msg=r.text)
        return c

    def test_01_security_ai_disabled_and_upload_validation(self) -> None:
        coord = self._login_client("u-coord")

        # 1. Disabled AI writing assistant returns 503 and never calls external AI
        r_ai = coord.post("/api/v1/ai-assistant/improve", json={"text_ar": "تحسين نص اختباري"})
        self.assertEqual(r_ai.status_code, 503)
        self.assertEqual(r_ai.json()["error"]["code"], "AI_ASSISTANT_DISABLED")

        # 2. Invalid image upload (spoofed MIME with fake bytes) rejected with 400
        r_bad = coord.post(
            "/api/v1/uploads/image",
            files={"file": ("evil.png", b"NOT_A_REAL_PNG_FILE", "image/png")},
        )
        self.assertEqual(r_bad.status_code, 400)
        self.assertEqual(r_bad.json()["error"]["code"], "INVALID_IMAGE_SIGNATURE")

        # 3. Valid PNG upload accepted with 201
        buf = io.BytesIO()
        Image.new("RGB", (200, 120), (0, 112, 148)).save(buf, format="PNG")
        r_ok = coord.post(
            "/api/v1/uploads/image",
            files={"file": ("valid.png", buf.getvalue(), "image/png")},
        )
        self.assertEqual(r_ok.status_code, 201)
        self.assertTrue(Path(r_ok.json()["storage_path"]).exists())

        # 4. Web UI index serves Arabic RTL HTML
        r_idx = coord.get("/")
        self.assertEqual(r_idx.status_code, 200)
        self.assertIn('dir="rtl"', r_idx.text)

    def test_02_complete_12_step_final_acceptance_workflow(self) -> None:
        coord = self._login_client("u-coord")
        emp_maram = self._login_client("u-maram")
        emp_abdullah = self._login_client("u-abdullah")
        emp_mohammed = self._login_client("u-mohammed")

        # Baseline Week 44 (historical record that MUST remain unchanged!)
        r_w44 = coord.post(
            "/api/v1/weeks",
            json={"week_number": 44, "fiscal_year": 2026, "start_date": "2026-11-08", "end_date": "2026-11-14"},
        )
        self.assertEqual(r_w44.status_code, 201)
        w44_id = r_w44.json()["reporting_week"]["id"]
        emp_mohammed.post(
            f"/api/v1/weeks/{w44_id}/submissions",
            json={
                "project_id": "proj-int-ai",
                "submission_status": "submitted",
                "project_status": "on_hold",
                "challenges": [{"challenge_ar": "تحدي الأسبوع 44 التاريخي"}],
            },
        )

        # STEP 1: Coordinator creates Week 45 with carry-forward & deadline
        r_w45 = coord.post(
            "/api/v1/weeks",
            json={
                "week_number": 45,
                "fiscal_year": 2026,
                "start_date": "2026-11-15",
                "end_date": "2026-11-21",
                "carry_forward_from_week_id": w44_id,
            },
        )
        self.assertEqual(r_w45.status_code, 201)
        w45_id = r_w45.json()["reporting_week"]["id"]
        coord.patch(f"/api/v1/weeks/{w45_id}", json={"submission_deadline": "2026-11-20 14:00"})

        # STEP 2 & 3: Three employees log in and see ONLY their assigned sections
        d_maram = emp_maram.get(f"/api/v1/my-dashboard?week_id={w45_id}").json()
        d_abd = emp_abdullah.get(f"/api/v1/my-dashboard?week_id={w45_id}").json()
        d_moh = emp_mohammed.get(f"/api/v1/my-dashboard?week_id={w45_id}").json()

        self.assertEqual({s["project_code"] for s in d_maram["assigned_sections"]}, {"P1_3", "P1_4"})
        self.assertEqual({s["project_code"] for s in d_abd["assigned_sections"]}, {"P1_6"})
        self.assertEqual({s["project_code"] for s in d_moh["assigned_sections"]}, {"INT_AI_DIAGNOSTIC"})

        # Verify strict cross-employee isolation (403)
        r_unauth = emp_maram.get(f"/api/v1/weeks/{w45_id}/projects/proj-int-ai")
        self.assertEqual(r_unauth.status_code, 403)

        # STEP 4 & 5: Employees save drafts & submit distinct weekly updates
        # Employee 1 (Maram): Draft then Submit P1_3 (Slide 16) + P1_4 (Slides 7 & 20)
        r_draft = emp_maram.post(
            f"/api/v1/weeks/{w45_id}/submissions",
            json={
                "project_id": "proj-p1-3",
                "submission_status": "draft",
                "achievements": [{"slot_index": 1, "content_ar": "مسودة إنجاز الحملة الإعلامية"}],
            },
        )
        self.assertEqual(r_draft.status_code, 201)
        emp_maram.post(
            f"/api/v1/weeks/{w45_id}/submissions",
            json={
                "project_id": "proj-p1-3",
                "expected_version": 1,
                "submission_status": "submitted",
                "achievements": [
                    {"slot_index": 1, "content_ar": "[قبول نهائي] اعتماد النسخة النهائية لفيديوهات قصص النجاح."}
                ],
                "upcoming_tasks": [
                    {"task_kind": "project_task", "sequence_no": 1, "title_ar": "[قبول نهائي] إطلاق الحملة المصغرة الأسبوع القادم."}
                ],
            },
        )
        emp_maram.post(
            f"/api/v1/weeks/{w45_id}/submissions",
            json={
                "project_id": "proj-p1-4",
                "submission_status": "submitted",
                "kpis": [{"kpi_code": "BENEFICIARIES_UPDATED", "numeric_value": 1310}],
            },
        )

        # Employee 2 (Abdullah): Submit P1_6 (Slides 29 & 30)
        emp_abdullah.post(
            f"/api/v1/weeks/{w45_id}/submissions",
            json={
                "project_id": "proj-p1-6",
                "submission_status": "submitted",
                "kpis": [
                    {"kpi_code": "ENABLERS_ACTIVATED", "numeric_value": 13, "denominator_value": 15},
                    {"kpi_code": "ENABLERS_EVENTS", "numeric_value": 28, "denominator_value": 25},
                ],
                "achievements": [{"slot_index": 1, "content_ar": "[قبول نهائي] تفعيل جهتين ممكنتين جديدتين."}],
            },
        )

        # Employee 3 (Mohammed): Submit INT_AI_DIAGNOSTIC (Slide 34)
        emp_mohammed.post(
            f"/api/v1/weeks/{w45_id}/submissions",
            json={
                "project_id": "proj-int-ai",
                "submission_status": "submitted",
                "project_status": "on_track",
                "challenges": [{"challenge_ar": "[قبول نهائي] تسريع اعتماد نطاق المورد التقني"}],
            },
        )

        # STEP 6 & 7: Coordinator sees submission statuses, checks reminders, reviews updates
        cdash = coord.get(f"/api/v1/coordinator/dashboard?week_id={w45_id}").json()
        by_code = {m["project_code"]: m["status"] for m in cdash["matrix"]}
        self.assertEqual(by_code["P1_3"], "submitted")
        self.assertEqual(by_code["P1_6"], "submitted")
        self.assertEqual(by_code["INT_AI_DIAGNOSTIC"], "submitted")

        rem = coord.get(f"/api/v1/weeks/{w45_id}/reminders").json()
        self.assertFalse(rem["external_dispatch_configured"])
        self.assertGreaterEqual(len(rem["reminders"]), 1)

        r_rev = coord.post(
            f"/api/v1/weeks/{w45_id}/submissions/proj-int-ai/review",
            json={"status": "approved", "reviewer_notes_ar": "ممتاز، جاهز للعرض"},
        )
        self.assertEqual(r_rev.status_code, 200)
        self.assertEqual(r_rev.json()["status_ar"], "تمت المراجعة")

        # STEP 8 & 9: Coordinator generates PPTX and downloads it
        r_gen = coord.post(
            f"/api/v1/weeks/{w45_id}/generate",
            json={"allow_incomplete": True, "run_visual_validation": False},
        )
        self.assertEqual(r_gen.status_code, 201, msg=r_gen.text)
        gen_id = r_gen.json()["generation"]["id"]
        self.assertTrue(r_gen.json()["validation"]["structural"]["passed"])

        r_dl = coord.get(f"/api/v1/generations/{gen_id}/download")
        self.assertEqual(r_dl.status_code, 200)
        dl_pptx = self.tmp_path / "downloaded_acceptance.pptx"
        dl_pptx.write_bytes(r_dl.content)

        # STEP 10 & 11: Verify submitted data appears in exact original slides & PPTX remains editable
        prs = Presentation(str(dl_pptx))
        self.assertEqual(len(prs.slides), 65)

        with zipfile.ZipFile(dl_pptx, "r") as z:
            s16_txt = z.read("ppt/slides/slide16.xml").decode("utf-8")
            self.assertIn("[قبول نهائي] اعتماد النسخة النهائية لفيديوهات قصص النجاح.", s16_txt)
            s29_txt = z.read("ppt/slides/slide29.xml").decode("utf-8")
            self.assertIn("13/15", s29_txt)
            s34_root = etree.fromstring(z.read("ppt/slides/slide34.xml"))
            tbl34 = s34_root.xpath('.//p:graphicFrame[p:nvGraphicFramePr/p:cNvPr[@id="47"]]//a:tbl', namespaces=NS)[0]
            c0 = tbl34.findall("a:tr", NS)[0].findall("a:tc", NS)[0]
            self.assertEqual(c0.find("a:tcPr/a:solidFill/a:srgbClr", NS).get("val"), "00B050")

        # Verify snapshot archived in report_generations
        gen_row = self.app.state.repo.get_generation(gen_id)
        self.assertIsNotNone(gen_row.get("input_snapshot_json"))

        # STEP 12: Verify Week 44 historical data remained 100% unchanged!
        w44_detail = self.app.state.repo.get_project_week_detail(w44_id, "proj-int-ai")
        self.assertEqual(w44_detail["project_status"]["status_code"], "on_hold")
        self.assertEqual(w44_detail["challenges"][0]["challenge_ar"], "تحدي الأسبوع 44 التاريخي")


if __name__ == "__main__":
    unittest.main()
