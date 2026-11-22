"""Configurable slide-field mapping loader, value formatter, and bundle resolver."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class FieldMapping:
    slide_number: int
    object_type: str  # shape | table_cell | status_table_cell | table_rows | image_replace
    object_id: str
    field_key: str
    data_type: str
    format_rule: str
    validation: Dict[str, Any]
    fallback_behavior: str = "preserve_template"
    row: Optional[int] = None
    col: Optional[int] = None
    resizable: bool = False
    columns: Optional[List[str]] = None


class MappingRegistry:
    def __init__(self, config_path: Path):
        raw = json.loads(Path(config_path).read_text(encoding="utf-8"))
        self.schema_version: str = raw["schema_version"]
        self.template_name: str = raw["template_name"]
        self.expected_slide_count: int = int(raw["expected_slide_count"])
        self.expected_dimensions_emu: Dict[str, int] = raw["expected_dimensions_emu"]
        self.status_visual_styles: Dict[str, Dict[str, str]] = raw["status_visual_styles"]
        self.mappings: List[FieldMapping] = [
            FieldMapping(
                slide_number=int(m["slide_number"]),
                object_type=m["object_type"],
                object_id=str(m["object_id"]),
                field_key=m["field_key"],
                data_type=m["data_type"],
                format_rule=m["format_rule"],
                validation=m.get("validation", {}),
                fallback_behavior=m.get("fallback_behavior", "preserve_template"),
                row=m.get("row"),
                col=m.get("col"),
                resizable=bool(m.get("resizable", False)),
                columns=m.get("columns"),
            )
            for m in raw["mappings"]
        ]

    def format_value(self, mapping: FieldMapping, raw_value: Any) -> Tuple[Optional[Any], Optional[str]]:
        """
        Validate & format a mapped value.
        Returns (formatted_value, warning_or_error).
        Explicitly returns (None, None) when raw_value is None so missing data is NEVER coerced to 0.
        """
        if raw_value is None:
            return None, None

        if mapping.object_type == "table_rows":
            if not isinstance(raw_value, list):
                return None, f"{mapping.field_key}: expected list of row dicts"
            return raw_value, None

        if mapping.object_type == "image_replace":
            return str(raw_value), None

        if mapping.object_type == "status_table_cell":
            code = str(raw_value)
            allowed = mapping.validation.get("enum", list(self.status_visual_styles.keys()))
            if code not in allowed:
                return None, f"{mapping.field_key}: invalid status '{code}'"
            return self.status_visual_styles[code], None

        # Ratio KPI: expects dict {"numeric_value": x, "denominator_value": y} or "x/y" string
        if mapping.format_rule == "ratio":
            if isinstance(raw_value, dict):
                num = raw_value.get("numeric_value")
                den = raw_value.get("denominator_value")
                if num is None or den is None:
                    return None, None
                return f"{int(round(num))}/{int(round(den))}", None
            return str(raw_value), None

        # Numeric formatting
        if mapping.data_type in ("integer", "percentage"):
            val = float(raw_value)
            vmin = mapping.validation.get("min")
            vmax = mapping.validation.get("max")
            if vmin is not None and val < vmin:
                return None, f"{mapping.field_key}: value {val} below min {vmin}"
            if vmax is not None and val > vmax:
                return None, f"{mapping.field_key}: value {val} above max {vmax}"
            ival = int(round(val))
            if mapping.format_rule == "int":
                return str(ival), None
            if mapping.format_rule == "comma_int":
                return f"{ival:,}", None
            if mapping.format_rule == "percent_prefix":
                return f"%{ival}", None
            if mapping.format_rule.startswith("prefix:"):
                prefix = mapping.format_rule[len("prefix:") :]
                return f"{prefix}{ival}", None
            return str(ival), None

        # Plain string
        text = str(raw_value)
        if text == "":
            return None, None
        return text, None

    def resolve_bundle_to_fields(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        """Map a structured week bundle from the DB into logical field_key values."""
        fields: Dict[str, Any] = {}
        wk = bundle["reporting_week"]
        fields["metadata.report_title_ar"] = wk["report_title_ar"]
        fields["metadata.week_number"] = wk["week_number"]
        fields["metadata.fiscal_year"] = wk["fiscal_year"]

        # KPIs (preserve explicit None!)
        for kv in bundle.get("kpis", []):
            code = kv["kpi_code"]
            if kv["aggregation_type"] == "ratio":
                if kv["numeric_value"] is not None and kv.get("denominator_value") is not None:
                    fields[f"kpi.{code}"] = {
                        "numeric_value": kv["numeric_value"],
                        "denominator_value": kv["denominator_value"],
                    }
            else:
                fields[f"kpi.{code}"] = kv["numeric_value"]

        # Achievements
        for ach in bundle.get("achievements", []):
            fields[f"achievement.{ach['project_code']}.{ach['slot_index']}"] = ach["content_ar"]

        # Upcoming tasks (project tasks vs meeting action items)
        action_rows = []
        for t in bundle.get("upcoming_tasks", []):
            if t["task_kind"] == "project_task":
                fields[f"task.{t['project_code']}.{t['sequence_no']}"] = t["title_ar"]
            elif t["task_kind"] == "meeting_action_item":
                action_rows.append(
                    {
                        "status": t.get("task_status") or "جاري",
                        "weekly_update": t.get("weekly_update_ar") or "",
                        "expected_due_date": t.get("expected_due_date") or "",
                        "owner_label": t.get("owner_label_ar") or "",
                        "title_ar": t.get("title_ar") or "",
                        "sequence_no": str(t.get("sequence_no", "")),
                    }
                )
        if action_rows:
            fields["action_items.ACTIVE_MEETING"] = action_rows

        # Challenges & support
        by_proj_ch: Dict[str, List[str]] = {}
        for c in bundle.get("challenges", []):
            if not c.get("is_resolved"):
                by_proj_ch.setdefault(c["project_code"], []).append(c["challenge_ar"])
        for pcode, lines in by_proj_ch.items():
            fields[f"challenge.{pcode}"] = "\n".join(lines)

        # Project statuses & deliverables overrides
        for ps in bundle.get("project_statuses", []):
            fields[f"status.{ps['project_code']}"] = ps["status_code"]
            if ps.get("deliverables_override_ar"):
                fields[f"deliverables.{ps['project_code']}"] = ps["deliverables_override_ar"]

        # Events
        for ev in bundle.get("events", []):
            date_lbl = ev.get("event_date_label") or ""
            lead = f" ({ev['lead_names_ar']})" if ev.get("lead_names_ar") else ""
            text = f"{date_lbl}\n{ev['title_ar']}{lead}" if date_lbl else f"{ev['title_ar']}{lead}"
            fields[f"event.{ev['slot_key']}"] = text

        # News & optional images
        for nw in bundle.get("news", []):
            slot = nw["slot_index"]
            body = nw["body_ar"]
            if nw.get("headline_ar"):
                body = f"{nw['headline_ar']} — {body}"
            fields[f"news.ITEM_{slot}"] = body
            if nw.get("image_path"):
                fields[f"news.IMAGE_{slot}"] = nw["image_path"]

        # Extra optional narrative keys (e.g. SMI 2 month label & axes)
        for k, v in bundle.get("narratives", {}).items():
            fields[f"narrative.{k}"] = v

        return fields
