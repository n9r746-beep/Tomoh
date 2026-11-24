"""Data access repository across all 18 TOMOH entities with immutable audit logging."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.database import Database


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class TomohRepository:
    def __init__(self, db: Database):
        self.db = db

    # --- Audit History (append-only) ---
    def record_audit(
        self,
        *,
        entity_type: str,
        entity_id: str,
        action: str,
        actor_user_id: str,
        reporting_week_id: Optional[str] = None,
        old_value: Optional[Dict[str, Any]] = None,
        new_value: Optional[Dict[str, Any]] = None,
    ) -> str:
        aid = _uid("aud")
        self.db.execute(
            """
            INSERT INTO audit_history
              (id, reporting_week_id, entity_type, entity_id, action, actor_user_id, old_value_json, new_value_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aid,
                reporting_week_id,
                entity_type,
                entity_id,
                action,
                actor_user_id,
                json.dumps(old_value, ensure_ascii=False) if old_value is not None else None,
                json.dumps(new_value, ensure_ascii=False) if new_value is not None else None,
                _now_iso(),
            ),
        )
        return aid

    # --- Users & Permissions ---
    def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))

    def user_can_edit_project(self, user_id: str, project_id: str) -> bool:
        proj = self.db.fetch_one("SELECT owner_user_id FROM projects WHERE id = ?", (project_id,))
        if proj and proj.get("owner_user_id") == user_id:
            return True
        mem = self.db.fetch_one(
            "SELECT member_role FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
        return mem is not None and mem["member_role"] in ("manager", "contributor")

    # --- Projects & Assignments ---
    def list_projects(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM projects WHERE is_active = 1 ORDER BY project_code")

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))

    def create_project(self, data: Dict[str, Any], actor_user_id: str) -> Dict[str, Any]:
        pid = _uid("proj")
        now = _now_iso()
        self.db.execute(
            """
            INSERT INTO projects
              (id, project_code, title_ar, category, fiscal_year, description_ar, deliverables_ar,
               owner_user_id, team_id, estimated_budget_ar, linked_kpi_ar, rfp_linked,
               service_providers_ar, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                pid,
                data["project_code"],
                data["title_ar"],
                data["category"],
                data["fiscal_year"],
                data.get("description_ar"),
                data.get("deliverables_ar"),
                data.get("owner_user_id"),
                data.get("team_id"),
                data.get("estimated_budget_ar"),
                data.get("linked_kpi_ar"),
                1 if data.get("rfp_linked") else 0,
                data.get("service_providers_ar"),
                now,
                now,
            ),
        )
        created = self.get_project(pid)
        self.record_audit(
            entity_type="project",
            entity_id=pid,
            action="create",
            actor_user_id=actor_user_id,
            new_value=created,
        )
        return created  # type: ignore

    def assign_project_member(
        self, project_id: str, user_id: str, member_role: str, actor_user_id: str
    ) -> Dict[str, Any]:
        existing = self.db.fetch_one(
            "SELECT * FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
        if existing:
            self.db.execute(
                "UPDATE project_members SET member_role = ? WHERE id = ?",
                (member_role, existing["id"]),
            )
            mid = existing["id"]
        else:
            mid = _uid("pm")
            self.db.execute(
                "INSERT INTO project_members (id, project_id, user_id, member_role, assigned_at) VALUES (?, ?, ?, ?, ?)",
                (mid, project_id, user_id, member_role, _now_iso()),
            )
        row = self.db.fetch_one("SELECT * FROM project_members WHERE id = ?", (mid,))
        self.record_audit(
            entity_type="project_member",
            entity_id=mid,
            action="assign",
            actor_user_id=actor_user_id,
            old_value=existing,
            new_value=row,
        )
        return row  # type: ignore

    def list_project_members(self, project_id: str) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            """
            SELECT pm.*, u.full_name_ar, u.email, u.role
            FROM project_members pm JOIN users u ON u.id = pm.user_id
            WHERE pm.project_id = ?
            """,
            (project_id,),
        )

    # --- Reporting Weeks ---
    def create_reporting_week(
        self,
        *,
        week_number: int,
        fiscal_year: int,
        start_date: str,
        end_date: str,
        report_title_ar: str,
        created_by: str,
    ) -> Dict[str, Any]:
        wid = _uid("wk")
        now = _now_iso()
        self.db.execute(
            """
            INSERT INTO reporting_weeks
              (id, week_number, fiscal_year, start_date, end_date, report_title_ar, status, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (wid, week_number, fiscal_year, start_date, end_date, report_title_ar, created_by, now, now),
        )
        wk = self.get_reporting_week(wid)
        self.record_audit(
            entity_type="reporting_week",
            entity_id=wid,
            action="create",
            actor_user_id=created_by,
            reporting_week_id=wid,
            new_value=wk,
        )
        return wk  # type: ignore

    def get_reporting_week(self, week_id: str) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one("SELECT * FROM reporting_weeks WHERE id = ?", (week_id,))

    def get_current_reporting_week(self) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one(
            "SELECT * FROM reporting_weeks ORDER BY week_number DESC LIMIT 1"
        )

    def list_reporting_weeks(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM reporting_weeks ORDER BY week_number DESC")

    def update_week_status(self, week_id: str, new_status: str, actor_user_id: str) -> None:
        old = self.get_reporting_week(week_id)
        self.db.execute(
            "UPDATE reporting_weeks SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, _now_iso(), week_id),
        )
        self.record_audit(
            entity_type="reporting_week",
            entity_id=week_id,
            action="status_change",
            actor_user_id=actor_user_id,
            reporting_week_id=week_id,
            old_value={"status": old["status"] if old else None},
            new_value={"status": new_status},
        )

    # --- KPI Definitions & Values ---
    def list_kpi_definitions(self) -> List[Dict[str, Any]]:
        return self.db.fetch_all("SELECT * FROM kpi_definitions WHERE is_active = 1")

    def get_kpi_definition_by_code(self, kpi_code: str) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one("SELECT * FROM kpi_definitions WHERE kpi_code = ?", (kpi_code,))

    def upsert_kpi_value(
        self,
        *,
        reporting_week_id: str,
        project_id: Optional[str],
        kpi_definition_id: str,
        responsible_user_id: str,
        submission_status: str,
        numeric_value: Optional[float],
        denominator_value: Optional[float] = None,
        is_unchanged: bool = False,
    ) -> Dict[str, Any]:
        now = _now_iso()
        existing = self.db.fetch_one(
            "SELECT * FROM kpi_values WHERE reporting_week_id = ? AND kpi_definition_id = ? AND responsible_user_id = ?",
            (reporting_week_id, kpi_definition_id, responsible_user_id),
        )
        if existing:
            self.db.execute(
                """
                UPDATE kpi_values
                SET numeric_value = ?, denominator_value = ?, is_unchanged = ?,
                    responsible_user_id = ?, submission_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    numeric_value,
                    denominator_value,
                    1 if is_unchanged else 0,
                    responsible_user_id,
                    submission_status,
                    now,
                    existing["id"],
                ),
            )
            kid = existing["id"]
        else:
            kid = _uid("kv")
            self.db.execute(
                """
                INSERT INTO kpi_values
                  (id, reporting_week_id, project_id, kpi_definition_id, responsible_user_id,
                   submission_status, numeric_value, denominator_value, is_unchanged, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kid,
                    reporting_week_id,
                    project_id,
                    kpi_definition_id,
                    responsible_user_id,
                    submission_status,
                    numeric_value,
                    denominator_value,
                    1 if is_unchanged else 0,
                    now,
                    now,
                ),
            )
        row = self.db.fetch_one("SELECT * FROM kpi_values WHERE id = ?", (kid,))
        self.record_audit(
            entity_type="kpi_value",
            entity_id=kid,
            action="upsert",
            actor_user_id=responsible_user_id,
            reporting_week_id=reporting_week_id,
            old_value=existing,
            new_value=row,
        )
        return row  # type: ignore

    def list_kpi_values_for_week(self, reporting_week_id: str) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            """
            SELECT kv.*, kd.kpi_code, kd.label_ar, kd.aggregation_type,
                   kd.auto_accumulate_from, kd.annual_target, kd.unit_format
            FROM kpi_values kv
            JOIN kpi_definitions kd ON kd.id = kv.kpi_definition_id
            WHERE kv.reporting_week_id = ?
            """,
            (reporting_week_id,),
        )

    # --- Submissions & Weekly Entities ---
    def get_submission(self, reporting_week_id: str, project_id: str, submitted_by: Optional[str] = None) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM weekly_submissions WHERE reporting_week_id = ? AND project_id = ?"
        params = (reporting_week_id, project_id)
        if submitted_by is not None:
            sql += " AND submitted_by = ?"
            params += (submitted_by,)
        return self.db.fetch_one(sql + " ORDER BY created_at, id LIMIT 1", params)

    def list_submissions_for_week(self, reporting_week_id: str) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            """
            SELECT ws.*, p.project_code, p.title_ar, u.full_name_ar AS submitted_by_name
            FROM weekly_submissions ws
            JOIN projects p ON p.id = ws.project_id
            JOIN users u ON u.id = ws.submitted_by
            WHERE ws.reporting_week_id = ?
            ORDER BY p.project_code
            """,
            (reporting_week_id,),
        )

    def upsert_submission(
        self,
        *,
        reporting_week_id: str,
        project_id: str,
        submitted_by: str,
        status: str,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        now = _now_iso()
        existing = self.get_submission(reporting_week_id, project_id, submitted_by)
        if existing:
            if expected_version is not None and existing["version"] != expected_version:
                raise ValueError(
                    f"CONFLICT: submission version mismatch (expected {expected_version}, actual {existing['version']})"
                )
            new_ver = existing["version"] + 1
            self.db.execute(
                """
                UPDATE weekly_submissions
                SET submitted_by = ?, status = ?, version = ?, updated_at = ?
                WHERE id = ?
                """,
                (submitted_by, status, new_ver, now, existing["id"]),
            )
            sid = existing["id"]
        else:
            sid = _uid("sub")
            self.db.execute(
                """
                INSERT INTO weekly_submissions
                  (id, reporting_week_id, project_id, submitted_by, status, version, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (sid, reporting_week_id, project_id, submitted_by, status, now, now),
            )
        row = self.db.fetch_one("SELECT * FROM weekly_submissions WHERE id = ?", (sid,))
        self.record_audit(
            entity_type="weekly_submission",
            entity_id=sid,
            action="upsert",
            actor_user_id=submitted_by,
            reporting_week_id=reporting_week_id,
            old_value=existing,
            new_value=row,
        )
        return row  # type: ignore

    def upsert_achievement(
        self,
        *,
        reporting_week_id: str,
        project_id: str,
        responsible_user_id: str,
        submission_status: str,
        slot_index: int,
        content_ar: str,
    ) -> Dict[str, Any]:
        now = _now_iso()
        existing = self.db.fetch_one(
            "SELECT * FROM achievements WHERE reporting_week_id = ? AND project_id = ? AND slot_index = ? AND responsible_user_id = ?",
            (reporting_week_id, project_id, slot_index, responsible_user_id),
        )
        if existing:
            self.db.execute(
                "UPDATE achievements SET content_ar = ?, responsible_user_id = ?, submission_status = ?, updated_at = ? WHERE id = ?",
                (content_ar, responsible_user_id, submission_status, now, existing["id"]),
            )
            aid = existing["id"]
        else:
            aid = _uid("ach")
            self.db.execute(
                """
                INSERT INTO achievements
                  (id, reporting_week_id, project_id, responsible_user_id, submission_status, slot_index, content_ar, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (aid, reporting_week_id, project_id, responsible_user_id, submission_status, slot_index, content_ar, now, now),
            )
        return self.db.fetch_one("SELECT * FROM achievements WHERE id = ?", (aid,))  # type: ignore

    def replace_tasks_for_project_week(
        self,
        *,
        reporting_week_id: str,
        project_id: str,
        responsible_user_id: str,
        submission_status: str,
        tasks: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        now = _now_iso()
        # Only replaces tasks for THIS reporting_week_id (never touches historical weeks!)
        self.db.execute(
            "DELETE FROM upcoming_tasks WHERE reporting_week_id = ? AND project_id = ? AND responsible_user_id = ?",
            (reporting_week_id, project_id, responsible_user_id),
        )
        created = []
        for t in tasks:
            tid = _uid("tsk")
            self.db.execute(
                """
                INSERT INTO upcoming_tasks
                  (id, reporting_week_id, project_id, responsible_user_id, submission_status,
                   task_kind, sequence_no, title_ar, owner_label_ar, expected_due_date,
                   weekly_update_ar, task_status, carried_from_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tid,
                    reporting_week_id,
                    project_id,
                    responsible_user_id,
                    submission_status,
                    t.get("task_kind", "project_task"),
                    t["sequence_no"],
                    t["title_ar"],
                    t.get("owner_label_ar"),
                    t.get("expected_due_date"),
                    t.get("weekly_update_ar"),
                    t.get("task_status", "جاري"),
                    t.get("carried_from_id"),
                    now,
                    now,
                ),
            )
            created.append(self.db.fetch_one("SELECT * FROM upcoming_tasks WHERE id = ?", (tid,)))
        return created  # type: ignore

    def replace_challenges_for_project_week(
        self,
        *,
        reporting_week_id: str,
        project_id: str,
        responsible_user_id: str,
        submission_status: str,
        challenges: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        now = _now_iso()
        self.db.execute(
            "DELETE FROM challenges WHERE reporting_week_id = ? AND project_id = ? AND responsible_user_id = ?",
            (reporting_week_id, project_id, responsible_user_id),
        )
        out = []
        for c in challenges:
            cid = _uid("chg")
            self.db.execute(
                """
                INSERT INTO challenges
                  (id, reporting_week_id, project_id, responsible_user_id, submission_status,
                   challenge_ar, support_needed_ar, is_resolved, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cid,
                    reporting_week_id,
                    project_id,
                    responsible_user_id,
                    submission_status,
                    c["challenge_ar"],
                    c.get("support_needed_ar"),
                    1 if c.get("is_resolved") else 0,
                    now,
                    now,
                ),
            )
            out.append(self.db.fetch_one("SELECT * FROM challenges WHERE id = ?", (cid,)))
        return out  # type: ignore

    def upsert_project_status(
        self,
        *,
        reporting_week_id: str,
        project_id: str,
        responsible_user_id: str,
        submission_status: str,
        status_code: str,
        progress_note_ar: Optional[str] = None,
        deliverables_override_ar: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = _now_iso()
        existing = self.db.fetch_one(
            "SELECT * FROM project_statuses WHERE reporting_week_id = ? AND project_id = ? AND responsible_user_id = ?",
            (reporting_week_id, project_id, responsible_user_id),
        )
        if existing:
            self.db.execute(
                """
                UPDATE project_statuses
                SET status_code = ?, progress_note_ar = ?, deliverables_override_ar = ?,
                    responsible_user_id = ?, submission_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status_code,
                    progress_note_ar,
                    deliverables_override_ar,
                    responsible_user_id,
                    submission_status,
                    now,
                    existing["id"],
                ),
            )
            psid = existing["id"]
        else:
            psid = _uid("ps")
            self.db.execute(
                """
                INSERT INTO project_statuses
                  (id, reporting_week_id, project_id, responsible_user_id, submission_status,
                   status_code, progress_note_ar, deliverables_override_ar, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    psid,
                    reporting_week_id,
                    project_id,
                    responsible_user_id,
                    submission_status,
                    status_code,
                    progress_note_ar,
                    deliverables_override_ar,
                    now,
                    now,
                ),
            )
        return self.db.fetch_one("SELECT * FROM project_statuses WHERE id = ?", (psid,))  # type: ignore

    def upsert_event(
        self,
        *,
        reporting_week_id: str,
        project_id: Optional[str],
        responsible_user_id: str,
        submission_status: str,
        slot_key: str,
        title_ar: str,
        event_date_label: Optional[str],
        lead_names_ar: Optional[str],
        event_status: str,
        beneficiaries_count: Optional[int],
    ) -> Dict[str, Any]:
        now = _now_iso()
        existing = self.db.fetch_one(
            "SELECT * FROM events WHERE reporting_week_id = ? AND slot_key = ? AND responsible_user_id = ?",
            (reporting_week_id, slot_key, responsible_user_id),
        )
        if existing:
            self.db.execute(
                """
                UPDATE events
                SET title_ar = ?, event_date_label = ?, lead_names_ar = ?, event_status = ?,
                    beneficiaries_count = ?, responsible_user_id = ?, submission_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    title_ar,
                    event_date_label,
                    lead_names_ar,
                    event_status,
                    beneficiaries_count,
                    responsible_user_id,
                    submission_status,
                    now,
                    existing["id"],
                ),
            )
            eid = existing["id"]
        else:
            eid = _uid("evt")
            self.db.execute(
                """
                INSERT INTO events
                  (id, reporting_week_id, project_id, responsible_user_id, submission_status,
                   slot_key, title_ar, event_date_label, lead_names_ar, event_status,
                   beneficiaries_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eid,
                    reporting_week_id,
                    project_id,
                    responsible_user_id,
                    submission_status,
                    slot_key,
                    title_ar,
                    event_date_label,
                    lead_names_ar,
                    event_status,
                    beneficiaries_count,
                    now,
                    now,
                ),
            )
        return self.db.fetch_one("SELECT * FROM events WHERE id = ?", (eid,))  # type: ignore

    def upsert_news(
        self,
        *,
        reporting_week_id: str,
        project_id: Optional[str],
        responsible_user_id: str,
        submission_status: str,
        slot_index: int,
        headline_ar: Optional[str],
        body_ar: str,
        attachment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = _now_iso()
        existing = self.db.fetch_one(
            "SELECT * FROM news WHERE reporting_week_id = ? AND slot_index = ? AND responsible_user_id = ?",
            (reporting_week_id, slot_index, responsible_user_id),
        )
        if existing:
            self.db.execute(
                """
                UPDATE news
                SET headline_ar = ?, body_ar = ?, attachment_id = ?,
                    responsible_user_id = ?, submission_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (headline_ar, body_ar, attachment_id, responsible_user_id, submission_status, now, existing["id"]),
            )
            nid = existing["id"]
        else:
            nid = _uid("nws")
            self.db.execute(
                """
                INSERT INTO news
                  (id, reporting_week_id, project_id, responsible_user_id, submission_status,
                   slot_index, headline_ar, body_ar, attachment_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (nid, reporting_week_id, project_id, responsible_user_id, submission_status, slot_index, headline_ar, body_ar, attachment_id, now, now),
            )
        return self.db.fetch_one("SELECT * FROM news WHERE id = ?", (nid,))  # type: ignore

    def create_attachment(
        self,
        *,
        reporting_week_id: str,
        entity_type: str,
        entity_id: str,
        file_name: str,
        mime_type: str,
        storage_path: str,
        uploaded_by: str,
    ) -> Dict[str, Any]:
        atid = _uid("att")
        self.db.execute(
            """
            INSERT INTO attachments
              (id, reporting_week_id, entity_type, entity_id, file_name, mime_type, storage_path, uploaded_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (atid, reporting_week_id, entity_type, entity_id, file_name, mime_type, storage_path, uploaded_by, _now_iso()),
        )
        return self.db.fetch_one("SELECT * FROM attachments WHERE id = ?", (atid,))  # type: ignore

    # --- Report Generations ---
    def record_generation(
        self,
        *,
        reporting_week_id: str,
        triggered_by: str,
        template_sha256: str,
        output_pptx_path: str,
        output_sha256: Optional[str],
        status: str,
        validation_summary: Dict[str, Any],
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        gid = _uid("gen")
        self.db.execute(
            """
            INSERT INTO report_generations
              (id, reporting_week_id, triggered_by, template_sha256, output_pptx_path,
               output_sha256, status, validation_json, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gid,
                reporting_week_id,
                triggered_by,
                template_sha256,
                output_pptx_path,
                output_sha256,
                status,
                json.dumps(validation_summary, ensure_ascii=False),
                error_message,
                _now_iso(),
            ),
        )
        row = self.db.fetch_one("SELECT * FROM report_generations WHERE id = ?", (gid,))
        self.record_audit(
            entity_type="report_generation",
            entity_id=gid,
            action="generate",
            actor_user_id=triggered_by,
            reporting_week_id=reporting_week_id,
            new_value={"status": status, "output_pptx_path": output_pptx_path},
        )
        return row  # type: ignore

    def get_generation(self, generation_id: str) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one("SELECT * FROM report_generations WHERE id = ?", (generation_id,))

    def list_generations(self, reporting_week_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if reporting_week_id:
            return self.db.fetch_all(
                "SELECT * FROM report_generations WHERE reporting_week_id = ? ORDER BY created_at DESC",
                (reporting_week_id,),
            )
        return self.db.fetch_all("SELECT * FROM report_generations ORDER BY created_at DESC")

    def get_week_bundle(self, reporting_week_id: str) -> Dict[str, Any]:
        """Collect all weekly entities for a reporting week into a single structured dict."""
        week = self.get_reporting_week(reporting_week_id)
        if not week:
            raise KeyError(f"Reporting week '{reporting_week_id}' not found")
        return {
            "reporting_week": week,
            "projects": self.list_projects(),
            "submissions": self.list_submissions_for_week(reporting_week_id),
            "kpis": self.list_kpi_values_for_week(reporting_week_id),
            "achievements": self.db.fetch_all(
                """
                SELECT a.*, p.project_code FROM achievements a
                JOIN projects p ON p.id = a.project_id
                WHERE a.reporting_week_id = ? ORDER BY p.project_code, a.slot_index
                """,
                (reporting_week_id,),
            ),
            "upcoming_tasks": self.db.fetch_all(
                """
                SELECT t.*, p.project_code FROM upcoming_tasks t
                LEFT JOIN projects p ON p.id = t.project_id
                WHERE t.reporting_week_id = ? ORDER BY t.task_kind, t.sequence_no
                """,
                (reporting_week_id,),
            ),
            "challenges": self.db.fetch_all(
                """
                SELECT c.*, p.project_code FROM challenges c
                JOIN projects p ON p.id = c.project_id
                WHERE c.reporting_week_id = ?
                """,
                (reporting_week_id,),
            ),
            "project_statuses": self.db.fetch_all(
                """
                SELECT ps.*, p.project_code FROM project_statuses ps
                JOIN projects p ON p.id = ps.project_id
                WHERE ps.reporting_week_id = ?
                """,
                (reporting_week_id,),
            ),
            "events": self.db.fetch_all(
                "SELECT * FROM events WHERE reporting_week_id = ? ORDER BY slot_key",
                (reporting_week_id,),
            ),
            "news": self.db.fetch_all(
                """
                SELECT n.*, att.storage_path AS image_path
                FROM news n LEFT JOIN attachments att ON att.id = n.attachment_id
                WHERE n.reporting_week_id = ? ORDER BY n.slot_index
                """,
                (reporting_week_id,),
            ),
        }
