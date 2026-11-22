"""Phase 2 repository extension methods (sessions, reviews, project toggles, snapshots, reminders)."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.db.repository import TomohRepository, _now_iso


def attach_phase2_methods(repo_cls: type[TomohRepository]) -> None:
    def create_session(self: TomohRepository, user_id: str, ttl_hours: int = 12) -> Dict[str, Any]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        exp = now + timedelta(hours=ttl_hours)
        self.db.execute(
            "INSERT INTO user_sessions (token, user_id, created_at, expires_at, revoked) VALUES (?, ?, ?, ?, 0)",
            (token, user_id, now.isoformat(), exp.isoformat()),
        )
        self.record_audit(entity_type="session", entity_id=token[:12], action="login", actor_user_id=user_id)
        return {"token": token, "expires_at": exp.isoformat()}

    def revoke_session(self: TomohRepository, token: str, actor_user_id: str) -> None:
        self.db.execute("UPDATE user_sessions SET revoked = 1 WHERE token = ?", (token,))
        self.record_audit(entity_type="session", entity_id=token[:12], action="logout", actor_user_id=actor_user_id)

    def get_user_by_session(self: TomohRepository, token: str) -> Optional[Dict[str, Any]]:
        row = self.db.fetch_one(
            """
            SELECT u.*, s.expires_at, s.revoked
            FROM user_sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        )
        if not row or row.get("revoked"):
            return None
        if row["expires_at"] < _now_iso():
            return None
        return row

    def list_users(self: TomohRepository) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT id, email, full_name_ar, full_name_en, team_id, role, is_active FROM users WHERE is_active = 1 ORDER BY role, full_name_ar"
        )

    def list_assigned_projects(self: TomohRepository, user_id: str, include_all: bool = False) -> List[Dict[str, Any]]:
        if include_all:
            return self.db.fetch_all("SELECT * FROM projects WHERE is_active = 1 ORDER BY project_code")
        return self.db.fetch_all(
            """
            SELECT DISTINCT p.*
            FROM projects p
            LEFT JOIN project_members pm ON pm.project_id = p.id
            WHERE p.is_active = 1 AND p.is_enabled = 1
              AND (p.owner_user_id = ? OR (pm.user_id = ? AND pm.member_role IN ('manager', 'contributor')))
            ORDER BY p.project_code
            """,
            (user_id, user_id),
        )

    def remove_project_member(self: TomohRepository, project_id: str, user_id: str, actor_user_id: str) -> None:
        self.db.execute(
            "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
        self.record_audit(
            entity_type="project_member",
            entity_id=f"{project_id}:{user_id}",
            action="remove",
            actor_user_id=actor_user_id,
        )

    def update_project_settings(
        self: TomohRepository,
        project_id: str,
        *,
        is_enabled: Optional[bool] = None,
        owner_user_id: Optional[str] = None,
        section_config: Optional[Dict[str, Any]] = None,
        actor_user_id: str,
    ) -> Dict[str, Any]:
        old = self.get_project(project_id)
        if not old:
            raise KeyError(f"Project '{project_id}' not found")
        new_enabled = (1 if is_enabled else 0) if is_enabled is not None else old.get("is_enabled", 1)
        new_owner = owner_user_id if owner_user_id is not None else old.get("owner_user_id")
        new_cfg = (
            json.dumps(section_config, ensure_ascii=False)
            if section_config is not None
            else old.get("section_config_json")
        )
        self.db.execute(
            "UPDATE projects SET is_enabled = ?, owner_user_id = ?, section_config_json = ?, updated_at = ? WHERE id = ?",
            (new_enabled, new_owner, new_cfg, _now_iso(), project_id),
        )
        updated = self.get_project(project_id)
        self.record_audit(
            entity_type="project",
            entity_id=project_id,
            action="update_settings",
            actor_user_id=actor_user_id,
            old_value=old,
            new_value=updated,
        )
        return updated  # type: ignore

    def update_week_deadline(
        self: TomohRepository, week_id: str, deadline: Optional[str], actor_user_id: str
    ) -> Dict[str, Any]:
        old = self.get_reporting_week(week_id)
        if not old:
            raise KeyError(f"Reporting week '{week_id}' not found")
        self.db.execute(
            "UPDATE reporting_weeks SET submission_deadline = ?, updated_at = ? WHERE id = ?",
            (deadline, _now_iso(), week_id),
        )
        updated = self.get_reporting_week(week_id)
        self.record_audit(
            entity_type="reporting_week",
            entity_id=week_id,
            action="update_deadline",
            actor_user_id=actor_user_id,
            reporting_week_id=week_id,
            old_value={"submission_deadline": old.get("submission_deadline")},
            new_value={"submission_deadline": deadline},
        )
        return updated  # type: ignore

    def review_submission(
        self: TomohRepository,
        *,
        reporting_week_id: str,
        project_id: str,
        status: str,
        reviewer_notes_ar: Optional[str],
        reviewer_user_id: str,
    ) -> Dict[str, Any]:
        sub = self.get_submission(reporting_week_id, project_id)
        if not sub:
            raise KeyError("No submission found for this project and reporting week")
        self.db.execute(
            """
            UPDATE weekly_submissions
            SET status = ?, reviewed_by = ?, reviewer_notes_ar = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, reviewer_user_id, reviewer_notes_ar, _now_iso(), sub["id"]),
        )
        updated = self.get_submission(reporting_week_id, project_id)
        self.record_audit(
            entity_type="weekly_submission",
            entity_id=sub["id"],
            action=f"review:{status}",
            actor_user_id=reviewer_user_id,
            reporting_week_id=reporting_week_id,
            old_value={"status": sub["status"], "reviewer_notes_ar": sub.get("reviewer_notes_ar")},
            new_value={"status": status, "reviewer_notes_ar": reviewer_notes_ar},
        )
        return updated  # type: ignore

    def get_previous_week(self: TomohRepository, week_number: int) -> Optional[Dict[str, Any]]:
        return self.db.fetch_one(
            "SELECT * FROM reporting_weeks WHERE week_number < ? ORDER BY week_number DESC LIMIT 1",
            (week_number,),
        )

    def get_project_week_detail(
        self: TomohRepository, reporting_week_id: str, project_id: str
    ) -> Dict[str, Any]:
        sub = self.get_submission(reporting_week_id, project_id)
        kpis = self.db.fetch_all(
            """
            SELECT kv.*, kd.kpi_code, kd.label_ar, kd.aggregation_type, kd.annual_target, kd.unit_format
            FROM kpi_values kv JOIN kpi_definitions kd ON kd.id = kv.kpi_definition_id
            WHERE kv.reporting_week_id = ? AND (kv.project_id = ? OR kd.project_id = ?)
            """,
            (reporting_week_id, project_id, project_id),
        )
        achievements = self.db.fetch_all(
            "SELECT * FROM achievements WHERE reporting_week_id = ? AND project_id = ? ORDER BY slot_index",
            (reporting_week_id, project_id),
        )
        tasks = self.db.fetch_all(
            "SELECT * FROM upcoming_tasks WHERE reporting_week_id = ? AND project_id = ? ORDER BY task_kind, sequence_no",
            (reporting_week_id, project_id),
        )
        challenges = self.db.fetch_all(
            "SELECT * FROM challenges WHERE reporting_week_id = ? AND project_id = ?",
            (reporting_week_id, project_id),
        )
        pstatus = self.db.fetch_one(
            "SELECT * FROM project_statuses WHERE reporting_week_id = ? AND project_id = ?",
            (reporting_week_id, project_id),
        )
        events = self.db.fetch_all(
            "SELECT * FROM events WHERE reporting_week_id = ? AND project_id = ? ORDER BY slot_key",
            (reporting_week_id, project_id),
        )
        news = self.db.fetch_all(
            """
            SELECT n.*, att.storage_path AS image_path, att.file_name AS image_file_name
            FROM news n LEFT JOIN attachments att ON att.id = n.attachment_id
            WHERE n.reporting_week_id = ? AND n.project_id = ? ORDER BY n.slot_index
            """,
            (reporting_week_id, project_id),
        )
        return {
            "submission": sub,
            "kpis": kpis,
            "achievements": achievements,
            "upcoming_tasks": tasks,
            "challenges": challenges,
            "project_status": pstatus,
            "events": events,
            "news": news,
        }

    def save_generation_snapshot(
        self: TomohRepository, generation_id: str, snapshot: Dict[str, Any]
    ) -> None:
        self.db.execute(
            "UPDATE report_generations SET input_snapshot_json = ? WHERE id = ?",
            (json.dumps(snapshot, ensure_ascii=False), generation_id),
        )

    repo_cls.create_session = create_session  # type: ignore
    repo_cls.revoke_session = revoke_session  # type: ignore
    repo_cls.get_user_by_session = get_user_by_session  # type: ignore
    repo_cls.list_users = list_users  # type: ignore
    repo_cls.list_assigned_projects = list_assigned_projects  # type: ignore
    repo_cls.remove_project_member = remove_project_member  # type: ignore
    repo_cls.update_project_settings = update_project_settings  # type: ignore
    repo_cls.update_week_deadline = update_week_deadline  # type: ignore
    repo_cls.review_submission = review_submission  # type: ignore
    repo_cls.get_previous_week = get_previous_week  # type: ignore
    repo_cls.get_project_week_detail = get_project_week_detail  # type: ignore
    repo_cls.save_generation_snapshot = save_generation_snapshot  # type: ignore
