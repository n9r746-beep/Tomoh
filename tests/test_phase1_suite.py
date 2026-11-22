"""
Comprehensive Phase 1 Automated Test Suite (unittest + pytest-compatible).
Verifies all 12 QA criteria across the OOXML engine, lifecycle/DB layer, and FastAPI endpoints.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from lxml import etree
from PIL import Image, ImageDraw
from pptx import Presentation

from app.config import BASE_DIR, Settings
from app.main import create_app
from app.schemas import ReportingWeekCreate, WeeklySubmissionPayload

TEMPLATE_PPTX = Path(__import__("os").environ.get("TOMOH_TEMPLATE_PPTX", "/vercel/master_template.pptx"))
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


class TomohPhase1TestSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="tomoh_test_")
        self.tmp_path = Path(self.tmpdir.name)
        self.settings = Settings(
            database_url=f"sqlite:///{self.tmp_path / 'test.db'}",
            template_pptx_path=TEMPLATE_PPTX,
            mapping_config_path=BASE_DIR / "config" / "mapping_config.json",
            migrations_dir=BASE_DIR / "migrations",
            output_dir=self.tmp_path / "generated",
            uploads_dir=self.tmp_path / "uploads",
            auth_mode="header_dev",
            enable_visual_validation=False,
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app, headers={"X-Requested-With":"XMLHttpRequest"})

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _create_synthetic_news_image(self) -> Path:
        (self.tmp_path / "uploads").mkdir(parents=True, exist_ok=True)
        img_path = self.tmp_path / "uploads" / "synthetic_news_photo.png"
        im = Image.new("RGB", (800, 500), (0, 112, 148))
        draw = ImageDraw.Draw(im)
        draw.rectangle([40, 40, 760, 460], outline=(255, 255, 255), width=6)
        draw.ellipse([300, 150, 500, 350], fill=(0, 176, 80))
        im.save(img_path, format="PNG")
        return img_path

    def test_01_authorization_prevents_unauthorized_project_modification(self) -> None:
        # Coordinator creates Week 45
        r_wk = self.client.post(
            "/api/v1/weeks",
            headers={"X-User-Id": "u-coord"},
            json={
                "week_number": 45,
                "fiscal_year": 2026,
                "start_date": "2026-11-15",
                "end_date": "2026-11-21",
            },
        )
        self.assertEqual(r_wk.status_code, 201)
        wk_id = r_wk.json()["reporting_week"]["id"]

        # Employee u-fahad tries to modify proj-p1-6 (owned by u-abdullah) -> 403 Forbidden
        r_forbid = self.client.post(
            f"/api/v1/weeks/{wk_id}/submissions",
            headers={"X-User-Id": "u-fahad"},
            json={"project_id": "proj-p1-6", "achievements": [{"slot_index": 1, "content_ar": "غير مصرح"}]},
        )
        self.assertEqual(r_forbid.status_code, 403)
        self.assertEqual(r_forbid.json()["error"]["code"], "FORBIDDEN_PROJECT_ACCESS")

        # Employee tries to generate PPTX (coordinator-only) -> 403 Forbidden
        r_gen = self.client.post(
            f"/api/v1/weeks/{wk_id}/generate",
            headers={"X-User-Id": "u-fahad"},
            json={},
        )
        self.assertEqual(r_gen.status_code, 403)
        self.assertEqual(r_gen.json()["error"]["code"], "FORBIDDEN_COORDINATOR_ONLY")

    def test_02_week_transitions_carry_forward_and_no_historical_overwrite(self) -> None:
        lifecycle = self.app.state.lifecycle
        repo = self.app.state.repo

        # Create Week 44 baseline
        w44 = lifecycle.create_reporting_week(
            ReportingWeekCreate(
                week_number=44, fiscal_year=2026, start_date="2026-11-08", end_date="2026-11-14"
            ),
            actor_user_id="u-coord",
        )["reporting_week"]

        # Submit Week 44 KPIs, achievement, open task, completed task, unresolved challenge, status
        lifecycle.submit_weekly_update(
            w44["id"],
            WeeklySubmissionPayload(
                project_id="proj-platform",
                kpis=[
                    {"kpi_code": "REG_COMPANIES_WEEKLY", "numeric_value": 35},
                    {"kpi_code": "REG_COMPANIES_2026", "numeric_value": 281},
                    {"kpi_code": "SMI_WEEKLY", "numeric_value": 0},  # Explicit zero!
                    {"kpi_code": "SMI1_CUMULATIVE_TOTAL", "numeric_value": 1510},
                ],
            ),
            actor_user_id="u-coord",
        )
        lifecycle.submit_weekly_update(
            w44["id"],
            WeeklySubmissionPayload(
                project_id="proj-int-ai",
                project_status="on_hold",
                achievements=[{"slot_index": 1, "content_ar": "إنجاز الأسبوع 44"}],
                upcoming_tasks=[
                    {"task_kind": "project_task", "sequence_no": 1, "title_ar": "مهمة مفتوحة", "task_status": "جاري"},
                    {"task_kind": "project_task", "sequence_no": 2, "title_ar": "مهمة مكتملة", "task_status": "مكتمل"},
                ],
                challenges=[{"challenge_ar": "تحدي قائم", "is_resolved": False}],
            ),
            actor_user_id="u-mohammed",
        )

        # Create Week 45 carrying forward from Week 44
        res45 = lifecycle.create_reporting_week(
            ReportingWeekCreate(
                week_number=45,
                fiscal_year=2026,
                start_date="2026-11-15",
                end_date="2026-11-21",
                carry_forward_from_week_id=w44["id"],
            ),
            actor_user_id="u-coord",
        )
        w45 = res45["reporting_week"]
        cf = res45["carry_forward"]

        # Verify achievements were NOT blindly duplicated!
        self.assertEqual(cf["achievements_carried"], 0)
        self.assertEqual(cf["open_tasks_carried"], 1)  # Only 'جاري', not 'مكتمل'
        self.assertEqual(cf["unresolved_challenges_carried"], 1)
        self.assertEqual(cf["project_statuses_carried"], 1)

        # Submit ONLY weekly delta REG_COMPANIES_WEEKLY=42 in Week 45;
        # REG_COMPANIES_2026 has auto_accumulate_from='REG_COMPANIES_WEEKLY' -> auto-sums 281 + 42 = 323
        # SMI1_CUMULATIVE_TOTAL has auto_accumulate_from=None -> stays 1510 (not recalculated!)
        lifecycle.submit_weekly_update(
            w45["id"],
            WeeklySubmissionPayload(
                project_id="proj-platform",
                kpis=[
                    {"kpi_code": "REG_COMPANIES_WEEKLY", "numeric_value": 42},
                    {"kpi_code": "DIAGNOSTIC_REPORTS_WEEKLY", "numeric_value": None},  # Explicit missing!
                ],
            ),
            actor_user_id="u-coord",
        )

        kpis45 = {k["kpi_code"]: k["numeric_value"] for k in repo.list_kpi_values_for_week(w45["id"])}
        self.assertEqual(kpis45["REG_COMPANIES_2026"], 323.0)
        self.assertEqual(kpis45["SMI1_CUMULATIVE_TOTAL"], 1510.0)
        self.assertIsNone(kpis45["DIAGNOSTIC_REPORTS_WEEKLY"])  # Missing NEVER converted to 0!

        # Verify Week 44 historical data was NOT overwritten!
        kpis44 = {k["kpi_code"]: k["numeric_value"] for k in repo.list_kpi_values_for_week(w44["id"])}
        self.assertEqual(kpis44["REG_COMPANIES_2026"], 281.0)
        self.assertEqual(kpis44["SMI_WEEKLY"], 0.0)

        # Verify optimistic version conflict detection on conflicting submission
        with self.assertRaises(ValueError) as ctx:
            lifecycle.submit_weekly_update(
                w45["id"],
                WeeklySubmissionPayload(project_id="proj-platform", expected_version=99, kpis=[]),
                actor_user_id="u-coord",
            )
        self.assertIn("CONFLICT", str(ctx.exception))

    def test_03_full_real_template_generation_determinism_and_integrity(self) -> None:
        dataset = json.loads((BASE_DIR / "data" / "sample_week45_dataset.json").read_text(encoding="utf-8"))
        news_img = self._create_synthetic_news_image()

        # Create Week 45 via API
        r_wk = self.client.post(
            "/api/v1/weeks",
            headers={"X-User-Id": "u-coord"},
            json=dataset["reporting_week"],
        )
        self.assertEqual(r_wk.status_code, 201)
        wk_id = r_wk.json()["reporting_week"]["id"]

        # Submit all 7 project sections via API with their assigned owners
        for sub in dataset["submissions"]:
            payload = {k: v for k, v in sub.items() if k != "actor_user_id"}
            if payload["project_id"] == "proj-news":
                payload["news"][0]["image_path"] = str(news_img)
            r_sub = self.client.post(
                f"/api/v1/weeks/{wk_id}/submissions",
                headers={"X-User-Id": sub["actor_user_id"]},
                json=payload,
            )
            self.assertEqual(r_sub.status_code, 201, msg=r_sub.text)

        # Check completeness & preview endpoints
        r_comp = self.client.get(f"/api/v1/weeks/{wk_id}/completeness", headers={"X-User-Id": "u-coord"})
        self.assertEqual(r_comp.status_code, 200)
        self.assertEqual(r_comp.json()["completion_pct"], 100.0)

        r_prev = self.client.get(f"/api/v1/weeks/{wk_id}/preview", headers={"X-User-Id": "u-coord"})
        self.assertEqual(r_prev.status_code, 200)

        # Generate PPTX twice to verify deterministic consistent output
        out1 = self.tmp_path / "run1.pptx"
        out2 = self.tmp_path / "run2.pptx"
        rs = self.app.state.report_service
        res1 = rs.generate_weekly_pptx(
            reporting_week_id=wk_id,
            actor_user_id="u-coord",
            extra_narratives=dataset["extra_narratives"],
            explicit_output_path=out1,
        )
        res2 = rs.generate_weekly_pptx(
            reporting_week_id=wk_id,
            actor_user_id="u-coord",
            extra_narratives=dataset["extra_narratives"],
            explicit_output_path=out2,
        )

        self.assertEqual(res1["generation"]["status"], "succeeded")
        self.assertTrue(res1["validation"]["structural"]["passed"])
        self.assertEqual(res1["generation"]["output_sha256"], res2["generation"]["output_sha256"])

        # Inspect generated PPTX directly for values, dynamic rows, status fill color, image, and RTL
        prs = Presentation(str(out1))
        self.assertEqual(len(prs.slides), 65)

        with zipfile.ZipFile(out1, "r") as z:
            # Verify Slide 34 status fill color (#00B050 for on_track) and text ('وفق المخطط')
            s34 = etree.fromstring(z.read("ppt/slides/slide34.xml"))
            tbl34 = s34.xpath('.//p:graphicFrame[p:nvGraphicFramePr/p:cNvPr[@id="47"]]//a:tbl', namespaces=NS)[0]
            c0 = tbl34.findall("a:tr", NS)[0].findall("a:tc", NS)[0]
            self.assertEqual("".join(t.text or "" for t in c0.findall(".//a:t", NS)).strip(), "وفق المخطط")
            self.assertEqual(c0.find("a:tcPr/a:solidFill/a:srgbClr", NS).get("val"), "00B050")

            # Verify Slide 40 dynamic row addition (original 6 data rows -> 7 data rows + 1 header = 8 rows)
            s40 = etree.fromstring(z.read("ppt/slides/slide40.xml"))
            tbl40 = s40.xpath('.//p:graphicFrame[p:nvGraphicFramePr/p:cNvPr[@id="7"]]//a:tbl', namespaces=NS)[0]
            self.assertEqual(len(tbl40.findall("a:tr", NS)), 8)

            # Verify Slide 38 isolated image injection exists in ZIP
            self.assertIn("ppt/media/tomoh_injected_s38_p10.png", z.namelist())

        # Verify Download endpoint returns valid PPTX bytes
        gen_id = res1["generation"]["id"]
        r_dl = self.client.get(f"/api/v1/generations/{gen_id}/download", headers={"X-User-Id": "u-coord"})
        self.assertEqual(r_dl.status_code, 200)
        self.assertEqual(len(r_dl.content), out1.stat().st_size)


if __name__ == "__main__":
    unittest.main()
