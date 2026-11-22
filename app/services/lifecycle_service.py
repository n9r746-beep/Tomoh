"""
Weekly Reporting Lifecycle Service (Hardened Phase 3: Safe Image Path Validation).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.db.repository import TomohRepository
from app.schemas import ReportingWeekCreate, WeeklySubmissionPayload


def _validate_safe_image_path(image_path: str, uploads_dir: Optional[Path]) -> str:
    """Prevent arbitrary file read / path traversal via news image_path."""
    p = Path(image_path).resolve()
    if uploads_dir is not None:
        allowed_root = Path(uploads_dir).resolve()
        try:
            p.relative_to(allowed_root)
        except ValueError:
            raise ValueError(
                "INVALID_IMAGE_PATH: image_path must reside inside the authorized uploads directory."
            )
    if not p.exists() and uploads_dir is not None:
        from app import cloud_storage
        if cloud_storage.enabled():
            cloud_storage.restore_image(p, uploads_dir)
    if not p.exists() or not p.is_file():
        raise ValueError("INVALID_IMAGE_PATH: referenced image file does not exist.")
    if p.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise ValueError("INVALID_IMAGE_PATH: only PNG and JPEG images are permitted.")
    return str(p)


class LifecycleService:
    def __init__(self, repo: TomohRepository):
        self.repo = repo

    def create_reporting_week(
        self, payload: ReportingWeekCreate, actor_user_id: str
    ) -> Dict[str, Any]:
        title = (
            payload.report_title_ar
            or f"التقرير الأسبوعي رقم ({payload.week_number}) لإدارة علاقات نمو المنشآت"
        )
        new_week = self.repo.create_reporting_week(
            week_number=payload.week_number,
            fiscal_year=payload.fiscal_year,
            start_date=payload.start_date,
            end_date=payload.end_date,
            report_title_ar=title,
            created_by=actor_user_id,
        )

        carried_summary = {
            "open_tasks_carried": 0,
            "unresolved_challenges_carried": 0,
            "project_statuses_carried": 0,
            "cumulative_kpis_initialized": 0,
            "achievements_carried": 0,  # Explicitly ALWAYS 0
        }

        if payload.carry_forward_from_week_id:
            prev_bundle = self.repo.get_week_bundle(payload.carry_forward_from_week_id)

            tasks_by_proj: Dict[str, List[Dict[str, Any]]] = {}
            for t in prev_bundle["upcoming_tasks"]:
                if t["task_status"] not in ("مكتمل", "ملغي") and t.get("project_id"):
                    tasks_by_proj.setdefault(t["project_id"], []).append(
                        {
                            "task_kind": t["task_kind"],
                            "sequence_no": t["sequence_no"],
                            "title_ar": t["title_ar"],
                            "owner_label_ar": t.get("owner_label_ar"),
                            "expected_due_date": t.get("expected_due_date"),
                            "weekly_update_ar": None,
                            "task_status": t["task_status"],
                            "carried_from_id": t["id"],
                        }
                    )
            for pid, tlist in tasks_by_proj.items():
                self.repo.replace_tasks_for_project_week(
                    reporting_week_id=new_week["id"],
                    project_id=pid,
                    responsible_user_id=actor_user_id,
                    submission_status="draft",
                    tasks=tlist,
                )
                carried_summary["open_tasks_carried"] += len(tlist)

            ch_by_proj: Dict[str, List[Dict[str, Any]]] = {}
            for c in prev_bundle["challenges"]:
                if not c["is_resolved"]:
                    ch_by_proj.setdefault(c["project_id"], []).append(
                        {
                            "challenge_ar": c["challenge_ar"],
                            "support_needed_ar": c.get("support_needed_ar"),
                            "is_resolved": False,
                        }
                    )
            for pid, clist in ch_by_proj.items():
                self.repo.replace_challenges_for_project_week(
                    reporting_week_id=new_week["id"],
                    project_id=pid,
                    responsible_user_id=actor_user_id,
                    submission_status="draft",
                    challenges=clist,
                )
                carried_summary["unresolved_challenges_carried"] += len(clist)

            for ps in prev_bundle["project_statuses"]:
                self.repo.upsert_project_status(
                    reporting_week_id=new_week["id"],
                    project_id=ps["project_id"],
                    responsible_user_id=actor_user_id,
                    submission_status="draft",
                    status_code=ps["status_code"],
                    progress_note_ar=ps.get("progress_note_ar"),
                    deliverables_override_ar=ps.get("deliverables_override_ar"),
                )
                carried_summary["project_statuses_carried"] += 1

            for kv in prev_bundle["kpis"]:
                if kv["aggregation_type"] in ("ytd_cumulative", "all_time_cumulative", "annual_target", "ratio", "percentage"):
                    self.repo.upsert_kpi_value(
                        reporting_week_id=new_week["id"],
                        project_id=kv.get("project_id"),
                        kpi_definition_id=kv["kpi_definition_id"],
                        responsible_user_id=actor_user_id,
                        submission_status="draft",
                        numeric_value=kv["numeric_value"],
                        denominator_value=kv.get("denominator_value"),
                        is_unchanged=True,
                    )
                    carried_summary["cumulative_kpis_initialized"] += 1

        return {"reporting_week": new_week, "carry_forward": carried_summary}

    def submit_weekly_update(
        self,
        reporting_week_id: str,
        payload: WeeklySubmissionPayload,
        actor_user_id: str,
        uploads_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        week = self.repo.get_reporting_week(reporting_week_id)
        if not week:
            raise KeyError(f"Reporting week '{reporting_week_id}' not found")
        if week["status"] in ("locked", "archived"):
            raise PermissionError(f"Reporting week '{reporting_week_id}' is {week['status']} and cannot be modified")

        project = self.repo.get_project(payload.project_id)
        if not project:
            raise KeyError(f"Project '{payload.project_id}' not found")

        # Validate any news image_path BEFORE mutating DB records
        validated_news_paths: Dict[int, str] = {}
        for nw in payload.news:
            if nw.image_path:
                validated_news_paths[nw.slot_index] = _validate_safe_image_path(nw.image_path, uploads_dir)

        submission = self.repo.upsert_submission(
            reporting_week_id=reporting_week_id,
            project_id=payload.project_id,
            submitted_by=actor_user_id,
            status=payload.submission_status,
            expected_version=payload.expected_version,
        )

        saved_kpis = []
        submitted_weekly_deltas: Dict[str, float] = {}
        for item in payload.kpis:
            kd = self.repo.get_kpi_definition_by_code(item.kpi_code)
            if not kd:
                raise ValueError(f"Unknown KPI code: '{item.kpi_code}'")
            saved = self.repo.upsert_kpi_value(
                reporting_week_id=reporting_week_id,
                project_id=payload.project_id,
                kpi_definition_id=kd["id"],
                responsible_user_id=actor_user_id,
                submission_status=payload.submission_status,
                numeric_value=item.numeric_value,
                denominator_value=item.denominator_value,
                is_unchanged=item.is_unchanged,
            )
            saved_kpis.append(saved)
            if kd["aggregation_type"] == "weekly_delta" and item.numeric_value is not None:
                submitted_weekly_deltas[item.kpi_code] = item.numeric_value

        manually_supplied_codes = {k.kpi_code for k in payload.kpis}
        all_defs = self.repo.list_kpi_definitions()
        existing_week_kpis = {kv["kpi_code"]: kv for kv in self.repo.list_kpi_values_for_week(reporting_week_id)}
        for kd in all_defs:
            src_code = kd.get("auto_accumulate_from")
            if (
                src_code
                and src_code in submitted_weekly_deltas
                and kd["kpi_code"] not in manually_supplied_codes
            ):
                base_row = existing_week_kpis.get(kd["kpi_code"])
                if base_row and base_row.get("numeric_value") is not None and base_row.get("is_unchanged"):
                    new_cum = float(base_row["numeric_value"]) + float(submitted_weekly_deltas[src_code])
                    self.repo.upsert_kpi_value(
                        reporting_week_id=reporting_week_id,
                        project_id=kd.get("project_id"),
                        kpi_definition_id=kd["id"],
                        responsible_user_id=actor_user_id,
                        submission_status=payload.submission_status,
                        numeric_value=new_cum,
                        is_unchanged=False,
                    )

        for ach in payload.achievements:
            self.repo.upsert_achievement(
                reporting_week_id=reporting_week_id,
                project_id=payload.project_id,
                responsible_user_id=actor_user_id,
                submission_status=payload.submission_status,
                slot_index=ach.slot_index,
                content_ar=ach.content_ar,
            )

        if payload.upcoming_tasks:
            self.repo.replace_tasks_for_project_week(
                reporting_week_id=reporting_week_id,
                project_id=payload.project_id,
                responsible_user_id=actor_user_id,
                submission_status=payload.submission_status,
                tasks=[t.dict() for t in payload.upcoming_tasks],
            )

        if payload.challenges:
            self.repo.replace_challenges_for_project_week(
                reporting_week_id=reporting_week_id,
                project_id=payload.project_id,
                responsible_user_id=actor_user_id,
                submission_status=payload.submission_status,
                challenges=[c.dict() for c in payload.challenges],
            )

        if payload.project_status is not None:
            self.repo.upsert_project_status(
                reporting_week_id=reporting_week_id,
                project_id=payload.project_id,
                responsible_user_id=actor_user_id,
                submission_status=payload.submission_status,
                status_code=payload.project_status,
                progress_note_ar=payload.progress_note_ar,
                deliverables_override_ar=payload.deliverables_override_ar,
            )

        for ev in payload.events:
            self.repo.upsert_event(
                reporting_week_id=reporting_week_id,
                project_id=payload.project_id,
                responsible_user_id=actor_user_id,
                submission_status=payload.submission_status,
                slot_key=ev.slot_key,
                title_ar=ev.title_ar,
                event_date_label=ev.event_date_label,
                lead_names_ar=ev.lead_names_ar,
                event_status=ev.event_status,
                beneficiaries_count=ev.beneficiaries_count,
            )

        for nw in payload.news:
            att_id = None
            safe_img = validated_news_paths.get(nw.slot_index)
            if safe_img:
                att = self.repo.create_attachment(
                    reporting_week_id=reporting_week_id,
                    entity_type="news",
                    entity_id=f"{reporting_week_id}:slot:{nw.slot_index}",
                    file_name=Path(safe_img).name,
                    mime_type="image/png" if safe_img.lower().endswith(".png") else "image/jpeg",
                    storage_path=safe_img,
                    uploaded_by=actor_user_id,
                )
                att_id = att["id"]
            self.repo.upsert_news(
                reporting_week_id=reporting_week_id,
                project_id=payload.project_id,
                responsible_user_id=actor_user_id,
                submission_status=payload.submission_status,
                slot_index=nw.slot_index,
                headline_ar=nw.headline_ar,
                body_ar=nw.body_ar,
                attachment_id=att_id,
            )

        return {"submission": submission, "kpis_saved": len(saved_kpis)}

    def compute_completeness(self, reporting_week_id: str) -> Dict[str, Any]:
        bundle = self.repo.get_week_bundle(reporting_week_id)
        projects = [p for p in bundle["projects"] if p.get("is_enabled", 1)]
        subs_by_proj = {s["project_id"]: s for s in bundle["submissions"]}
        kpis_by_code = {k["kpi_code"]: k for k in bundle["kpis"]}
        all_defs = self.repo.list_kpi_definitions()

        submitted_projects = []
        missing_projects = []
        for p in projects:
            sub = subs_by_proj.get(p["id"])
            if sub and sub["status"] in ("submitted", "approved"):
                submitted_projects.append({"project_id": p["id"], "project_code": p["project_code"], "status": sub["status"]})
            else:
                missing_projects.append({"project_id": p["id"], "project_code": p["project_code"], "status": sub["status"] if sub else "not_started"})

        missing_kpis = []
        null_kpis = []
        zero_kpis = []
        for kd in all_defs:
            kv = kpis_by_code.get(kd["kpi_code"])
            if not kv:
                missing_kpis.append(kd["kpi_code"])
            elif kv["numeric_value"] is None:
                null_kpis.append(kd["kpi_code"])
            elif float(kv["numeric_value"]) == 0.0:
                zero_kpis.append(kd["kpi_code"])

        total_p = len(projects)
        pct = round((len(submitted_projects) / total_p) * 100.0, 1) if total_p else 100.0
        return {
            "reporting_week_id": reporting_week_id,
            "week_number": bundle["reporting_week"]["week_number"],
            "completion_pct": pct,
            "submitted_projects": submitted_projects,
            "missing_projects": missing_projects,
            "missing_kpis": missing_kpis,
            "null_kpis": null_kpis,
            "explicit_zero_kpis": zero_kpis,
            "is_complete": len(missing_projects) == 0 and len(missing_kpis) == 0 and len(null_kpis) == 0,
        }
