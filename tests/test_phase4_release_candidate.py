"""
Phase 4 Release-Candidate Verification Tests:
  - Passwordless user provisioning & activation (RBAC enforced)
  - Multi-project employee assignment
  - Coordinator week-over-week diff preview
  - Safe archive guard (prevents archiving without generated PPTX)
  - Idempotent first-reporting-cycle bootstrap CLI
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import BASE_DIR, Settings
from app.main import create_app

TEMPLATE_PPTX = Path(__import__("os").environ.get("TOMOH_TEMPLATE_PPTX", "/vercel/master_template.pptx"))


class TomohPhase4ReleaseCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory(prefix="tomoh_p4_")
        self.tmp_path = Path(self.tmpdir.name)
        self.db_file = self.tmp_path / "p4_rc.db"
        self.settings = Settings(
            database_url=f"sqlite:///{self.db_file}",
            template_pptx_path=TEMPLATE_PPTX,
            mapping_config_path=BASE_DIR / "config" / "mapping_config.json",
            migrations_dir=BASE_DIR / "migrations",
            output_dir=self.tmp_path / "generated",
            uploads_dir=self.tmp_path / "uploads",
            frontend_dir=BASE_DIR / "frontend",
            auth_mode="header_dev",
        )
        self.app = create_app(self.settings)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _login(self, uid: str) -> TestClient:
        c = TestClient(self.app, headers={"X-Requested-With":"XMLHttpRequest"})
        r = c.post("/api/v1/auth/login", json={"user_id": uid})
        self.assertEqual(r.status_code, 200)
        return c

    def test_01_passwordless_user_management_and_multi_project_assignment(self) -> None:
        coord = self._login("u-coord")
        emp = self._login("u-fahad")

        # Employee cannot create users
        r_deny = emp.post("/api/v1/admin/users", json={"email": "new@tomoh.internal", "full_name_ar": "موظف جديد"})
        self.assertEqual(r_deny.status_code, 403)

        # Coordinator creates new employee without any password
        r_new = coord.post(
            "/api/v1/admin/users",
            json={"email": "sara.m@tomoh.internal", "full_name_ar": "سارة المنصور", "role": "employee"},
        )
        self.assertEqual(r_new.status_code, 201)
        new_uid = r_new.json()["user"]["id"]

        # Assign new employee to 2 projects
        for pid in ("proj-p1-3", "proj-p1-4"):
            r_asgn = coord.post(f"/api/v1/projects/{pid}/members", json={"user_id": new_uid, "member_role": "contributor"})
            self.assertEqual(r_asgn.status_code, 201)

        sara = self._login(new_uid)
        r_projs = sara.get("/api/v1/projects")
        self.assertEqual({p["project_code"] for p in r_projs.json()["projects"]}, {"P1_3", "P1_4"})

        # Deactivating user immediately blocks access
        r_deact = coord.patch(f"/api/v1/admin/users/{new_uid}", json={"is_active": False})
        self.assertEqual(r_deact.status_code, 200)
        self.assertEqual(sara.get("/api/v1/projects").status_code, 401)

    def test_02_coordinator_diff_preview_and_safe_archive_guard(self) -> None:
        coord = self._login("u-coord")
        moh = self._login("u-mohammed")

        w44 = coord.post(
            "/api/v1/weeks",
            json={"week_number": 44, "fiscal_year": 2026, "start_date": "2026-11-08", "end_date": "2026-11-14"},
        ).json()["reporting_week"]
        moh.post(f"/api/v1/weeks/{w44['id']}/submissions", json={"project_id": "proj-int-ai", "project_status": "on_hold"})

        w45 = coord.post(
            "/api/v1/weeks",
            json={
                "week_number": 45,
                "fiscal_year": 2026,
                "start_date": "2026-11-15",
                "end_date": "2026-11-21",
                "carry_forward_from_week_id": w44["id"],
            },
        ).json()["reporting_week"]
        moh.post(f"/api/v1/weeks/{w45['id']}/submissions", json={"project_id": "proj-int-ai", "project_status": "on_track"})

        # Diff preview shows status transition on_hold -> on_track
        r_diff = coord.get(f"/api/v1/weeks/{w45['id']}/diff")
        self.assertEqual(r_diff.status_code, 200)
        self.assertEqual(
            r_diff.json()["status_changes"],
            [{"project_code": "INT_AI_DIAGNOSTIC", "previous_status": "on_hold", "current_status": "on_track"}],
        )

        # Safe archive blocks archiving before any PPTX has been generated
        r_blk = coord.post(f"/api/v1/weeks/{w45['id']}/safe-archive", json={"force": False})
        self.assertEqual(r_blk.status_code, 409)
        self.assertEqual(r_blk.json()["error"]["code"], "ARCHIVE_REQUIRES_GENERATION")

        # After generating PPTX, safe archive succeeds
        coord.post(f"/api/v1/weeks/{w45['id']}/generate", json={"allow_incomplete": True})
        r_ok = coord.post(f"/api/v1/weeks/{w45['id']}/safe-archive", json={"force": False})
        self.assertEqual(r_ok.status_code, 200)
        self.assertEqual(r_ok.json()["reporting_week"]["status"], "archived")

    def test_03_idempotent_first_cycle_bootstrap_cli(self) -> None:
        env = {**os.environ, "PYTHONPATH": ".", "TOMOH_DATABASE_URL": f"sqlite:///{self.db_file}"}
        cmd = [
            sys.executable,
            str(BASE_DIR / "scripts" / "init_first_cycle.py"),
            "--week-number", "45",
            "--start-date", "2026-11-15",
            "--end-date", "2026-11-21",
            "--deadline", "2026-11-20 14:00",
        ]
        r1 = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
        d1 = json.loads(r1.stdout)
        self.assertEqual(d1["status"], "created")
        self.assertEqual(d1["reporting_week"]["week_number"], 45)

        # Re-running is idempotent and does not duplicate
        r2 = subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
        d2 = json.loads(r2.stdout)
        self.assertEqual(d2["status"], "already_exists")


if __name__ == "__main__":
    unittest.main()
