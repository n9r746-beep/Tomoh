"""
Phase 3 End-to-End QA, Security Hardening, Multi-Week Integrity, Concurrency,
Backup/Restore, and Full Synthetic Pilot Test Suite.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from lxml import etree
from PIL import Image, ImageDraw
from pptx import Presentation

from app.config import BASE_DIR, Settings
from app.main import create_app

TEMPLATE_PPTX = Path(__import__("os").environ.get("TOMOH_TEMPLATE_PPTX", "/vercel/master_template.pptx"))
NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


class TomohPhase3HardeningAndPilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="tomoh_p3_")
        self.tmp_path = Path(self.tmpdir.name)
        self.db_file = self.tmp_path / "p3_test.db"
        self.settings = Settings(
            database_url=f"sqlite:///{self.db_file}",
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

    def _login(self, uid: str) -> TestClient:
        c = TestClient(self.app, headers={"X-Requested-With":"XMLHttpRequest"})
        r = c.post("/api/v1/auth/login", json={"user_id": uid})
        self.assertEqual(r.status_code, 200)
        return c

    def test_01_horizontal_rbac_security_headers_and_path_traversal(self) -> None:
        coord = self._login("u-coord")
        fahad = self._login("u-fahad")
        moh = self._login("u-mohammed")

        wk = coord.post(
            "/api/v1/weeks",
            json={"week_number": 45, "fiscal_year": 2026, "start_date": "2026-11-15", "end_date": "2026-11-21"},
        ).json()["reporting_week"]

        # Mohammed submits INT_AI_DIAGNOSTIC
        moh.post(
            f"/api/v1/weeks/{wk['id']}/submissions",
            json={"project_id": "proj-int-ai", "project_status": "on_track", "challenges": [{"challenge_ar": "سري لمحمد"}]},
        )

        # Horizontal RBAC: Fahad calls GET /projects, /submissions, /kpis -> MUST NOT see Mohammed's project/data!
        r_proj = fahad.get("/api/v1/projects")
        self.assertEqual(r_proj.status_code, 200)
        self.assertEqual({p["project_code"] for p in r_proj.json()["projects"]}, {"INT_RELATIONSHIP"})

        r_subs = fahad.get(f"/api/v1/weeks/{wk['id']}/submissions")
        self.assertEqual(r_subs.status_code, 200)
        self.assertEqual(r_subs.json()["submissions"], [])

        r_comp = fahad.get(f"/api/v1/weeks/{wk['id']}/completeness")
        self.assertEqual(r_comp.status_code, 403)

        # Security headers verified on API response
        self.assertEqual(r_subs.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r_subs.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(r_subs.headers.get("Cache-Control"), "no-store")
        self.assertIn("default-src 'self'", r_subs.headers.get("Content-Security-Policy", ""))

        # Path Traversal attack via news[].image_path blocked with 400
        r_trav = coord.post(
            f"/api/v1/weeks/{wk['id']}/submissions",
            json={
                "project_id": "proj-news",
                "news": [{"slot_index": 1, "body_ar": "محاولة اختراق", "image_path": "/etc/passwd"}],
            },
        )
        self.assertEqual(r_trav.status_code, 400)
        self.assertEqual(r_trav.json()["error"]["code"], "INVALID_IMAGE_PATH")

        # Cross-origin CSRF POST with cookie blocked
        r_csrf = fahad.post(
            f"/api/v1/weeks/{wk['id']}/submissions",
            headers={"Origin": "evil://attacker.example"},
            json={"project_id": "proj-int-rel"},
        )
        self.assertEqual(r_csrf.status_code, 403)
        self.assertEqual(r_csrf.json()["error"]["code"], "CSRF_BLOCKED")

    def test_02_multi_week_integrity_reopen_archive_and_concurrency(self) -> None:
        coord = self._login("u-coord")
        moh = self._login("u-mohammed")

        # 3 Consecutive Weeks: W44 -> W45 -> W46
        w44 = coord.post(
            "/api/v1/weeks",
            json={"week_number": 44, "fiscal_year": 2026, "start_date": "2026-11-08", "end_date": "2026-11-14"},
        ).json()["reporting_week"]
        coord.post(
            f"/api/v1/weeks/{w44['id']}/submissions",
            json={
                "project_id": "proj-platform",
                "kpis": [
                    {"kpi_code": "REG_COMPANIES_WEEKLY", "numeric_value": 30},
                    {"kpi_code": "REG_COMPANIES_2026", "numeric_value": 250},
                    {"kpi_code": "SMI_WEEKLY", "numeric_value": 0},
                ],
            },
        )
        moh.post(
            f"/api/v1/weeks/{w44['id']}/submissions",
            json={
                "project_id": "proj-int-ai",
                "project_status": "on_hold",
                "achievements": [{"slot_index": 1, "content_ar": "إنجاز W44"}],
                "challenges": [{"challenge_ar": "تحدي W44"}],
            },
        )

        # W45 carries from W44
        w45_res = coord.post(
            "/api/v1/weeks",
            json={
                "week_number": 45,
                "fiscal_year": 2026,
                "start_date": "2026-11-15",
                "end_date": "2026-11-21",
                "carry_forward_from_week_id": w44["id"],
            },
        ).json()
        w45 = w45_res["reporting_week"]
        self.assertEqual(w45_res["carry_forward"]["achievements_carried"], 0)
        coord.post(
            f"/api/v1/weeks/{w45['id']}/submissions",
            json={"project_id": "proj-platform", "kpis": [{"kpi_code": "REG_COMPANIES_WEEKLY", "numeric_value": 20}]},
        )

        # W46 carries from W45 -> REG_COMPANIES_2026 should start at 270 and become 285 after +15
        w46 = coord.post(
            "/api/v1/weeks",
            json={
                "week_number": 46,
                "fiscal_year": 2026,
                "start_date": "2026-11-22",
                "end_date": "2026-11-28",
                "carry_forward_from_week_id": w45["id"],
            },
        ).json()["reporting_week"]
        coord.post(
            f"/api/v1/weeks/{w46['id']}/submissions",
            json={
                "project_id": "proj-platform",
                "kpis": [
                    {"kpi_code": "REG_COMPANIES_WEEKLY", "numeric_value": 15},
                    {"kpi_code": "DIAGNOSTIC_REPORTS_WEEKLY", "numeric_value": None},
                ],
            },
        )

        k44 = {k["kpi_code"]: k["numeric_value"] for k in self.app.state.repo.list_kpi_values_for_week(w44["id"])}
        k45 = {k["kpi_code"]: k["numeric_value"] for k in self.app.state.repo.list_kpi_values_for_week(w45["id"])}
        k46 = {k["kpi_code"]: k["numeric_value"] for k in self.app.state.repo.list_kpi_values_for_week(w46["id"])}
        self.assertEqual(k44["REG_COMPANIES_2026"], 250.0)
        self.assertEqual(k45["REG_COMPANIES_2026"], 270.0)
        self.assertEqual(k46["REG_COMPANIES_2026"], 285.0)
        self.assertEqual(k44["SMI_WEEKLY"], 0.0)
        self.assertIsNone(k46["DIAGNOSTIC_REPORTS_WEEKLY"])

        # Archive W45 -> employee edit rejected (409) -> reopen -> audit trail recorded
        r_arch = coord.post(f"/api/v1/weeks/{w45['id']}/archive")
        self.assertEqual(r_arch.status_code, 200)
        self.assertEqual(r_arch.json()["reporting_week"]["status"], "archived")
        r_blocked = moh.post(f"/api/v1/weeks/{w45['id']}/submissions", json={"project_id": "proj-int-ai"})
        self.assertEqual(r_blocked.status_code, 409)

        r_reopen = coord.post(f"/api/v1/weeks/{w45['id']}/unlock")
        self.assertEqual(r_reopen.status_code, 200)
        aud = self.app.state.db.fetch_all(
            "SELECT action, new_value_json FROM audit_history WHERE reporting_week_id = ? AND action = 'status_change'",
            (w45["id"],),
        )
        self.assertGreaterEqual(len(aud), 2)

        # Per-week concurrency lock test: holding lock triggers 409 GENERATION_IN_PROGRESS
        wk_lock = self.app.state.report_service._get_week_lock(w46["id"])
        wk_lock.acquire()
        try:
            r_dup = coord.post(f"/api/v1/weeks/{w46['id']}/generate", json={"allow_incomplete": True})
            self.assertEqual(r_dup.status_code, 409)
            self.assertEqual(r_dup.json()["error"]["code"], "GENERATION_IN_PROGRESS")
        finally:
            wk_lock.release()

    def test_03_real_backup_and_restore_cycle(self) -> None:
        coord = self._login("u-coord")
        wk = coord.post(
            "/api/v1/weeks",
            json={"week_number": 47, "fiscal_year": 2026, "start_date": "2026-11-29", "end_date": "2026-12-05"},
        ).json()["reporting_week"]

        backup_root = self.tmp_path / "backups"
        env = {
            **os.environ,
            "TOMOH_DATABASE_URL": f"sqlite:///{self.db_file}",
            "TOMOH_UPLOADS_DIR": str(self.settings.uploads_dir),
            "TOMOH_OUTPUT_DIR": str(self.settings.output_dir),
        }
        subprocess.run(["bash", str(BASE_DIR / "scripts" / "backup.sh"), str(backup_root)], env=env, check=True, capture_output=True)
        bdirs = list(backup_root.glob("tomoh_backup_*"))
        self.assertEqual(len(bdirs), 1)
        self.assertTrue((bdirs[0] / "SHA256SUMS.txt").exists())

        # Simulate catastrophic DB wipe, then run restore.sh
        self.db_file.unlink()
        self.assertFalse(self.db_file.exists())
        subprocess.run(["bash", str(BASE_DIR / "scripts" / "restore.sh"), str(bdirs[0])], env=env, check=True, capture_output=True)
        self.assertTrue(self.db_file.exists())

        # Verify Week 47 survived restore intact
        restored_wk = self.app.state.repo.get_reporting_week(wk["id"])
        self.assertIsNotNone(restored_wk)
        self.assertEqual(restored_wk["week_number"], 47)

    def test_04_full_synthetic_pilot_and_pptx_generation(self) -> None:
        coord = self._login("u-coord")
        maram = self._login("u-maram")
        abd = self._login("u-abdullah")
        moh = self._login("u-mohammed")
        fahad = self._login("u-fahad")

        dataset = json.loads((BASE_DIR / "data" / "sample_week45_dataset.json").read_text(encoding="utf-8"))
        wk = coord.post("/api/v1/weeks", json=dataset["reporting_week"]).json()["reporting_week"]

        # Upload real valid synthetic PNG via /uploads/image for Slide 38
        buf = io.BytesIO()
        im = Image.new("RGB", (800, 450), (0, 112, 148))
        ImageDraw.Draw(im).ellipse([310, 135, 490, 315], fill=(0, 176, 80))
        im.save(buf, format="PNG")
        up = coord.post("/api/v1/uploads/image", files={"file": ("pilot_news.png", buf.getvalue(), "image/png")}).json()

        clients = {"u-coord": coord, "u-maram": maram, "u-abdullah": abd, "u-mohammed": moh, "u-fahad": fahad}
        for sub in dataset["submissions"]:
            payload = {k: v for k, v in sub.items() if k != "actor_user_id"}
            if payload["project_id"] == "proj-news":
                payload["news"][0]["image_path"] = up["storage_path"]
            r = clients[sub["actor_user_id"]].post(f"/api/v1/weeks/{wk['id']}/submissions", json=payload)
            self.assertEqual(r.status_code, 201, msg=r.text)

        # Simulate correction workflow: Coordinator requests revision on P1_3 -> Maram resubmits -> Coordinator approves
        coord.post(
            f"/api/v1/weeks/{wk['id']}/submissions/proj-p1-3/review",
            json={"status": "changes_requested", "reviewer_notes_ar": "يرجى توضيح تاريخ الإطلاق"},
        )
        r_fix = maram.put(
            f"/api/v1/weeks/{wk['id']}/submissions/proj-p1-3",
            json={
                "project_id": "proj-p1-3",
                "expected_version": 1,
                "submission_status": "submitted",
                "achievements": [
                    {"slot_index": 1, "content_ar": "[تجربة قياسية] اعتماد النسخة النهائية لفيديوهات قصص النجاح."},
                    {"slot_index": 2, "content_ar": "[تجربة قياسية] اعتماد الجدول الزمني النهائي للحملة المصغرة."},
                    {"slot_index": 3, "content_ar": "[تجربة قياسية] مواءمة المحتوى التعريفي للربع الرابع."},
                ],
                "upcoming_tasks": [
                    {"task_kind": "project_task", "sequence_no": 1, "title_ar": "[تجربة قياسية] إطلاق الحملة المصغرة بتاريخ 24 نوفمبر."}
                ],
            },
        )
        self.assertEqual(r_fix.status_code, 200)
        coord.post(f"/api/v1/weeks/{wk['id']}/submissions/proj-p1-3/review", json={"status": "approved"})

        # Generate official Phase 3 Synthetic Pilot PPTX
        pilot_out = Path("/working_dir/c_cc067088a25be814/artifacts/file_generation/ttl=63d/output/generated-phase3-pilot.pptx")
        res = self.app.state.report_service.generate_weekly_pptx(
            reporting_week_id=wk["id"],
            actor_user_id="u-coord",
            extra_narratives=dataset["extra_narratives"],
            explicit_output_path=pilot_out,
        )
        self.assertEqual(res["generation"]["status"], "succeeded")
        self.assertTrue(res["validation"]["structural"]["passed"])
        self.assertEqual(res["validation"]["engine"]["operations_failed"], 0)
        self.assertEqual(res["validation"]["structural"]["zip_identical_parts"], 408)
        self.assertTrue(pilot_out.exists())


if __name__ == "__main__":
    unittest.main()
