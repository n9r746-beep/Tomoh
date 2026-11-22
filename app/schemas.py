"""Type-safe Pydantic v1 schemas for TOMOH Weekly Report Automation API & Engine."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, validator

ProjectCategory = Literal["operational_track", "internal_priority", "department_kpi", "news_and_events"]
ProjectStatusCode = Literal["on_track", "delayed", "critically_delayed", "on_hold", "completed", "not_started"]
TaskStatusAr = Literal["جاري", "مكتمل", "متأخر", "معلق", "ملغي"]
SubmissionStatus = Literal["draft", "submitted", "changes_requested", "approved"]
MemberRole = Literal["manager", "contributor", "viewer"]


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ProjectCreate(BaseModel):
    project_code: str = Field(..., min_length=2, max_length=40)
    title_ar: str = Field(..., min_length=2, max_length=200)
    category: ProjectCategory
    fiscal_year: int = Field(..., ge=2024, le=2035)
    description_ar: Optional[str] = None
    deliverables_ar: Optional[str] = None
    owner_user_id: Optional[str] = None
    team_id: Optional[str] = None
    estimated_budget_ar: Optional[str] = None
    linked_kpi_ar: Optional[str] = None
    rfp_linked: bool = False
    service_providers_ar: Optional[str] = None


class ProjectAssignmentCreate(BaseModel):
    user_id: str
    member_role: MemberRole = "contributor"


class ReportingWeekCreate(BaseModel):
    week_number: int = Field(..., ge=1, le=200)
    fiscal_year: int = Field(..., ge=2024, le=2035)
    start_date: str = Field(..., description="ISO date YYYY-MM-DD")
    end_date: str = Field(..., description="ISO date YYYY-MM-DD")
    report_title_ar: Optional[str] = None
    carry_forward_from_week_id: Optional[str] = None


class KpiInputItem(BaseModel):
    kpi_code: str
    numeric_value: Optional[float] = None  # Explicit None = missing; 0.0 = real zero
    denominator_value: Optional[float] = None
    is_unchanged: bool = False

    @validator("numeric_value")
    def validate_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("KPI numeric_value cannot be negative")
        return v


class AchievementInputItem(BaseModel):
    slot_index: int = Field(..., ge=1, le=10)
    content_ar: str = Field(..., min_length=1, max_length=400)


class TaskInputItem(BaseModel):
    task_kind: Literal["project_task", "meeting_action_item"] = "project_task"
    sequence_no: int = Field(..., ge=1, le=20)
    title_ar: str = Field(..., min_length=1, max_length=300)
    owner_label_ar: Optional[str] = None
    expected_due_date: Optional[str] = None
    weekly_update_ar: Optional[str] = None
    task_status: TaskStatusAr = "جاري"


class ChallengeInputItem(BaseModel):
    challenge_ar: str = Field(..., min_length=1, max_length=400)
    support_needed_ar: Optional[str] = None
    is_resolved: bool = False


class EventInputItem(BaseModel):
    slot_key: str = Field(..., min_length=2, max_length=60)
    title_ar: str = Field(..., min_length=1, max_length=250)
    event_date_label: Optional[str] = None
    lead_names_ar: Optional[str] = None
    event_status: str = "على المسار"
    beneficiaries_count: Optional[int] = Field(None, ge=0)


class NewsInputItem(BaseModel):
    slot_index: int = Field(..., ge=1, le=5)
    headline_ar: Optional[str] = None
    body_ar: str = Field(..., min_length=1, max_length=500)
    image_path: Optional[str] = None


class WeeklySubmissionPayload(BaseModel):
    project_id: str
    expected_version: Optional[int] = None  # Optimistic locking against conflicting submissions
    submission_status: SubmissionStatus = "submitted"
    project_status: Optional[ProjectStatusCode] = None
    progress_note_ar: Optional[str] = None
    deliverables_override_ar: Optional[str] = None
    kpis: List[KpiInputItem] = Field(default_factory=list)
    achievements: List[AchievementInputItem] = Field(default_factory=list)
    upcoming_tasks: List[TaskInputItem] = Field(default_factory=list)
    challenges: List[ChallengeInputItem] = Field(default_factory=list)
    events: List[EventInputItem] = Field(default_factory=list)
    news: List[NewsInputItem] = Field(default_factory=list)
    narratives: Dict[str, str] = Field(default_factory=dict)


class GenerateReportRequest(BaseModel):
    run_visual_validation: bool = False
    allow_incomplete: bool = True
