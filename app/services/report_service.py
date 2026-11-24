"""
9-Stage Report Generation Pipeline Service (Phase 3 Hardened: Per-Week Concurrency Lock,
Atomic File Writes, Restrictive Permissions, Failed-Job Isolation).
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import Settings
from app.collaboration import atomic_report
from app.db.repository import TomohRepository
from app.engine.mapping import MappingRegistry
from app.engine.ooxml_editor import PowerPointEngine
from app.engine.validator import run_visual_comparison, validate_structure
from app.services.lifecycle_service import LifecycleService

logger = logging.getLogger("tomoh.report_service")


class ReportService:
    def __init__(
        self,
        *,
        settings: Settings,
        repo: TomohRepository,
        lifecycle: LifecycleService,
        registry: MappingRegistry,
    ):
        self.settings = settings
        self.repo = repo
        self.lifecycle = lifecycle
        self.registry = registry
        self.engine = PowerPointEngine(registry)
        self._locks_guard = threading.Lock()
        self._week_locks: Dict[str, threading.Lock] = {}

    def _get_week_lock(self, week_id: str) -> threading.Lock:
        with self._locks_guard:
            if week_id not in self._week_locks:
                self._week_locks[week_id] = threading.Lock()
            return self._week_locks[week_id]

    def preview_week_report(self, reporting_week_id: str) -> Dict[str, Any]:
        bundle = self.repo.get_week_bundle(reporting_week_id)
        completeness = self.lifecycle.compute_completeness(reporting_week_id)
        field_values = self.registry.resolve_bundle_to_fields(bundle)
        mapped_preview = []
        for m in self.registry.mappings:
            raw = field_values.get(m.field_key)
            formatted, err = self.registry.format_value(m, raw)
            mapped_preview.append(
                {
                    "slide_number": m.slide_number,
                    "field_key": m.field_key,
                    "object_type": m.object_type,
                    "object_id": m.object_id,
                    "status": "error" if err else ("missing" if formatted is None else "ready"),
                    "formatted_value": formatted if m.object_type != "table_rows" else f"{len(formatted)} rows" if formatted else None,
                    "error": err,
                }
            )
        return {
            "reporting_week": bundle["reporting_week"],
            "completeness": completeness,
            "mapped_fields": mapped_preview,
        }

    @atomic_report
    def generate_weekly_pptx(
        self,
        *,
        reporting_week_id: str,
        actor_user_id: str,
        allow_incomplete: bool = True,
        run_visual_validation: bool = False,
        extra_narratives: Optional[Dict[str, str]] = None,
        explicit_output_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        wk_lock = self._get_week_lock(reporting_week_id)
        if not wk_lock.acquire(blocking=False):
            raise RuntimeError(
                f"GENERATION_IN_PROGRESS: Report generation for week '{reporting_week_id}' is already running."
            )

        try:
            from app.collaboration import require_approved_contributions
            require_approved_contributions(self.repo,reporting_week_id)
            bundle = self.repo.get_week_bundle(reporting_week_id)
            if extra_narratives:
                bundle["narratives"] = extra_narratives

            completeness = self.lifecycle.compute_completeness(reporting_week_id)
            if not allow_incomplete and not completeness["is_complete"]:
                raise ValueError(
                    f"Reporting week {bundle['reporting_week']['week_number']} is incomplete "
                    f"({completeness['completion_pct']}%). Set allow_incomplete=true to override."
                )

            from app import cloud_storage
            if cloud_storage.enabled():
                cloud_storage.ensure_template(self.settings.template_pptx_path)
                for news in bundle.get("news", []):
                    if news.get("image_path"):
                        cloud_storage.restore_image(news["image_path"], self.settings.uploads_dir)
            field_values = self.registry.resolve_bundle_to_fields(bundle)

            from app.engine.continuations import overflow_entries, append_continuations
            overflow = overflow_entries(self.registry, bundle, field_values)

            wk_num = bundle["reporting_week"]["week_number"]
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out_path = (
                explicit_output_path
                if explicit_output_path is not None
                else self.settings.output_dir / f"TOMOH_Weekly_Report_W{wk_num}_{ts}.pptx"
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(out_path.parent, 0o700)
            except OSError:
                pass

            # Atomic temp-file write so failed generation never leaves a corrupt PPTX
            tmp_out = out_path.with_suffix(".pptx.tmp")
            try:
                engine_res = self.engine.generate(
                    template_pptx=self.settings.template_pptx_path,
                    field_values=field_values,
                    output_pptx=tmp_out,
                )
                structural = validate_structure(
                    original_pptx=self.settings.template_pptx_path,
                    generated_pptx=tmp_out,
                    expected_modified_slides=engine_res.slides_modified,
                )
                structural["continuation_slides"] = append_continuations(tmp_out, overflow)
                import hashlib
                engine_res.output_sha256 = hashlib.sha256(tmp_out.read_bytes()).hexdigest()
                os.replace(tmp_out, out_path)
                try:
                    os.chmod(out_path, 0o600)
                except OSError:
                    pass
            except Exception as exc:
                if tmp_out.exists():
                    tmp_out.unlink(missing_ok=True)
                self.repo.record_generation(
                    reporting_week_id=reporting_week_id,
                    triggered_by=actor_user_id,
                    template_sha256="failed_before_completion",
                    output_pptx_path=str(out_path),
                    output_sha256=None,
                    status="failed",
                    validation_summary={"error": str(exc)},
                    error_message=str(exc),
                )
                raise

            visual: Optional[Dict[str, Any]] = None
            if run_visual_validation:
                visual = run_visual_comparison(
                    original_pptx=self.settings.template_pptx_path,
                    generated_pptx=out_path,
                    slides_to_compare=engine_res.slides_modified,
                    output_dir=self.settings.output_dir / f"visual_W{wk_num}_{ts}",
                )

            status = "succeeded" if (engine_res.operations_failed == 0 and structural["passed"]) else "failed"
            validation_summary = {
                "completeness": completeness,
                "engine": {
                    "slides_modified": engine_res.slides_modified,
                    "slides_untouched": engine_res.slides_untouched,
                    "operations_updated": engine_res.operations_updated,
                    "operations_skipped_missing": engine_res.operations_skipped_missing,
                    "operations_failed": engine_res.operations_failed,
                    "warnings": engine_res.warnings,
                },
                "structural": structural,
                "visual": visual,
            }

            from app import cloud_storage
            stored_path = cloud_storage.persist_report(out_path) if cloud_storage.enabled() else str(out_path)
            gen_record = self.repo.record_generation(
                reporting_week_id=reporting_week_id,
                triggered_by=actor_user_id,
                template_sha256=engine_res.template_sha256,
                output_pptx_path=stored_path,
                output_sha256=engine_res.output_sha256,
                status=status,
                validation_summary=validation_summary,
                error_message=None if status == "succeeded" else "Validation or operation error occurred",
            )
            if status == "succeeded":
                self.repo.update_week_status(reporting_week_id, "generated", actor_user_id)

            logger.info(
                "Generated weekly report",
                extra={"extra_data": {"generation_id": gen_record["id"], "week": wk_num, "status": status}},
            )

            return {
                "generation": gen_record,
                "validation": validation_summary,
                "engine_operations": [o.__dict__ for o in engine_res.operations],
            }
        finally:
            wk_lock.release()
