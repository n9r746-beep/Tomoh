"""
Phase 2 Web Application API Routes:
  - Session Auth (login/logout/me/dev-users)
  - Employee Dashboard & Per-Project Detail with Previous-Week Reference
  - Coordinator Dashboard Matrix, Review, Lock/Unlock, Deadlines, Section Settings
  - Secure Image Upload Validation (PNG/JPEG, magic bytes, <= 5 MB)
  - Missing-Submission Reminder Generator (copyable Arabic messages; zero external sends)
  - Disabled Internal-Only AI Writing Assistant Contract (feature-flagged OFF)
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Cookie, Depends, File, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, Field

from app.collaboration import section_state, participants

from app.auth import (
    AuthenticatedUser,
    get_current_user,
    require_coordinator,
    require_project_write_access,
)

phase2_router = APIRouter(prefix="/api/v1", tags=["TOMOH Phase 2 Web App API"])

STATUS_AR_MAP = {
    "not_started": "لم يبدأ",
    "draft": "مسودة",
    "submitted": "تم التسليم",
    "changes_requested": "يحتاج تعديل",
    "approved": "تمت المراجعة",
}


class LoginRequest(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None


class ReviewRequest(BaseModel):
    kpi_source_user_id: Optional[str] = None
    kpi_sources: Optional[Dict[str,str]] = None
    expected_versions: Optional[Dict[str, int]] = None
    status: Literal["approved", "changes_requested"]
    reviewer_notes_ar: Optional[str] = Field(default=None, max_length=500)


class WeekDeadlinePatch(BaseModel):
    submission_deadline: Optional[str] = Field(default=None, max_length=40)


class ProjectSettingsPatch(BaseModel):
    is_enabled: Optional[bool] = None
    owner_user_id: Optional[str] = None
    section_config: Optional[Dict[str, Any]] = None


class AiAssistRequest(BaseModel):
    text_ar: str = Field(..., min_length=3, max_length=2000)
    action: Literal["improve_grammar", "rewrite_achievement", "shorten", "standardize"] = "improve_grammar"


def _parse_section_config(proj: Dict[str, Any]) -> Dict[str, Any]:
    raw = proj.get("section_config_json")
    if not raw:
        return {"slides": [], "inputs": ["achievements", "upcoming_tasks"], "required": []}
    try:
        config = json.loads(raw)
        if proj.get("project_code") == "PLATFORM_KPI":
            config["kpi_codes"] = [code for code in config.get("kpi_codes", []) if not code.startswith("REG_COMPANIES_")]
        return config
    except Exception:
        return {"slides": [], "inputs": ["achievements", "upcoming_tasks"], "required": []}


# --- 1. Session Auth ---
@phase2_router.get("/auth/dev-users")
def list_dev_users(request: Request):
    if request.app.state.settings.auth_mode != "header_dev":
        raise HTTPException(
            status_code=404,
            detail={"code": "DEV_AUTH_DISABLED", "message": "Dev user directory is disabled in production mode."},
        )
    return {"users": request.app.state.repo.list_users(), "auth_mode": "header_dev"}


@phase2_router.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response):
    repo = request.app.state.repo
    production = request.app.state.settings.auth_mode != "header_dev"
    if production:
        import hashlib, hmac
        email = (payload.email or "").strip().lower()
        attempts = repo.db.fetch_one("SELECT count(*) AS n FROM login_attempts WHERE email = ? AND attempted_at > now() - interval '15 minutes'", (email,))
        if attempts["n"] >= 10:
            raise HTTPException(status_code=429, detail={"code":"LOGIN_RATE_LIMIT", "message":"محاولات كثيرة، حاول بعد ١٥ دقيقة."})
        repo.db.execute("INSERT INTO login_attempts(email) VALUES (?)", (email,))
        user = repo.db.fetch_one("SELECT id,email,full_name_ar,role,is_active FROM users WHERE lower(email) = ?", (email,))
        credential = repo.db.fetch_one("SELECT salt,password_hash FROM user_credentials WHERE user_id = ?", (user["id"],)) if user else None
        salt = bytes.fromhex(credential["salt"]) if credential else bytes(16)
        candidate = hashlib.pbkdf2_hmac("sha256", (payload.password or "").encode(), salt, 600000).hex()
        if not credential or not hmac.compare_digest(candidate, credential["password_hash"]):
            raise HTTPException(status_code=401, detail={"code":"INVALID_CREDENTIALS", "message":"البريد الإلكتروني أو كلمة المرور غير صحيحة."})
        repo.db.execute("DELETE FROM login_attempts WHERE email = ?", (email,))
    else:
        user = repo.get_user(payload.user_id)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail={"code": "INVALID_USER", "message": "الحساب غير موجود أو غير نشط."})
    sess = repo.create_session(user["id"])
    response.set_cookie(
        key="tomoh_session",
        value=sess["token"],
        httponly=True,
        secure=production,
        samesite="lax",
        max_age=12 * 3600,
    )
    return {
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name_ar": user["full_name_ar"],
            "role": user["role"],
        },
        "session_token": sess["token"],
        "expires_at": sess["expires_at"],
    }


@phase2_router.post("/auth/logout")
def logout(
    request: Request,
    response: Response,
    tomoh_session: Optional[str] = Cookie(default=None, alias="tomoh_session"),
    user: AuthenticatedUser = Depends(get_current_user),
):
    if tomoh_session:
        request.app.state.repo.revoke_session(tomoh_session, actor_user_id=user.id)
    response.delete_cookie("tomoh_session")
    return {"status": "logged_out"}


@phase2_router.get("/auth/me")
def get_me(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    repo = request.app.state.repo
    projects = repo.list_assigned_projects(user.id, include_all=(user.role in ("coordinator", "admin")))
    return {
        "user": user.__dict__,
        "assigned_projects": [
            {
                "id": p["id"],
                "project_code": p["project_code"],
                "title_ar": p["title_ar"],
                "category": p["category"],
                "is_enabled": bool(p.get("is_enabled", 1)),
                "section_config": _parse_section_config(p),
            }
            for p in projects
        ],
        "ai_assistant_enabled": request.app.state.settings.ai_assistant_enabled,
    }


# --- 2. Employee Homepage & Scoped Project Editor ---
@phase2_router.get("/my-dashboard")
def employee_dashboard(
    request: Request,
    week_id: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    repo = request.app.state.repo
    wk = repo.get_reporting_week(week_id) if week_id else repo.get_current_reporting_week()
    projects = repo.list_assigned_projects(user.id, include_all=(user.role in ("coordinator", "admin")))
    subs_by_proj = (
        {s["project_id"]: s for s in repo.list_submissions_for_week(wk["id"]) if s["submitted_by"] == user.id} if wk else {}
    )
    cards = []
    for p in projects:
        cfg = _parse_section_config(p)
        sub = subs_by_proj.get(p["id"])
        st = sub["status"] if sub else "not_started"
        remaining_req = 0 if st in ("submitted", "approved") else len(cfg.get("required", []))
        cards.append(
            {
                "project_id": p["id"],
                "project_code": p["project_code"],
                "title_ar": p["title_ar"],
                "category": p["category"],
                "slides": cfg.get("slides", []),
                "inputs": cfg.get("inputs", []),
                "required_fields": cfg.get("required", []),
                "remaining_required_count": remaining_req,
                "status": st,
                "status_ar": STATUS_AR_MAP.get(st, st),
                "last_updated": sub["updated_at"] if sub else None,
                "reviewer_notes_ar": sub.get("reviewer_notes_ar") if sub else None,
                "version": sub["version"] if sub else 0,
            }
        )
    return {
        "reporting_week": wk,
        "weeks": repo.list_reporting_weeks(),
        "assigned_sections": cards,
        "ai_assistant_enabled": request.app.state.settings.ai_assistant_enabled,
    }


@phase2_router.get("/weeks/{week_id}/projects/{project_id}")
def get_project_editor_data(
    week_id: str,
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    repo = request.app.state.repo
    require_project_write_access(repo, user, project_id)
    wk = repo.get_reporting_week(week_id)
    proj = repo.get_project(project_id)
    if not wk or not proj:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "الأسبوع أو المشروع غير موجود."})

    cfg = _parse_section_config(proj)
    kpi_defs = [
        d for d in repo.list_kpi_definitions()
        if not cfg.get("kpi_codes") or d["kpi_code"] in cfg["kpi_codes"]
    ] if "kpis" in cfg.get("inputs", []) else []

    current_detail = repo.get_project_week_detail(week_id, project_id, user.id)
    prev_wk = repo.get_previous_week(wk["week_number"])
    prev_detail = repo.get_project_week_detail(prev_wk["id"], project_id, user.id) if prev_wk else None

    return {
        "reporting_week": wk,
        "project": {**proj, "section_config": cfg},
        "kpi_definitions": kpi_defs,
        "current": current_detail,
        "previous_week": prev_wk,
        "previous": prev_detail,
        "editable": wk["status"] not in ("locked", "archived") and not repo.db.fetch_one("SELECT id FROM project_approvals WHERE reporting_week_id=? AND project_id=?", (week_id,project_id)),
        "ai_assistant_enabled": request.app.state.settings.ai_assistant_enabled,
    }


# --- 3. Coordinator Dashboard, Review, Lock/Unlock, Deadlines & Settings ---
@phase2_router.get("/coordinator/dashboard")
def coordinator_dashboard(
    request: Request,
    week_id: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    repo = request.app.state.repo
    wk = repo.get_reporting_week(week_id) if week_id else repo.get_current_reporting_week()
    projects = repo.list_projects()
    users_by_id = {u["id"]: u for u in repo.list_users()}
    subs_by_proj = (
        {s["project_id"]: s for s in repo.list_submissions_for_week(wk["id"]) if s["submitted_by"] == user.id} if wk else {}
    )

    matrix = []
    counts = {"not_started": 0, "draft": 0, "submitted": 0, "changes_requested": 0, "approved": 0}
    enabled_projects = [p for p in projects if p.get("is_enabled", 1)]

    for p in enabled_projects:
        collaboration = section_state(repo,wk["id"],p) if wk else {"status":"not_started","contributors":[],"submissions":[]}
        sub = max(collaboration["submissions"],key=lambda r:r["updated_at"],default=None)
        st = collaboration["status"]
        counts[st] = counts.get(st, 0) + 1
        owner = users_by_id.get(p.get("owner_user_id") or "")
        members = repo.list_project_members(p["id"])
        matrix.append(
            {
                "project_id": p["id"],
                "project_code": p["project_code"],
                "title_ar": p["title_ar"],
                "owner_name_ar": "، ".join(c["full_name_ar"] for c in collaboration["contributors"]) or (owner["full_name_ar"] if owner else "لم يحدد"),
                "contributors": collaboration["contributors"],
                "owner_user_id": p.get("owner_user_id"),
                "members": [{"user_id": m["user_id"], "full_name_ar": m["full_name_ar"], "member_role": m["member_role"]} for m in members],
                "status": st,
                "status_ar": STATUS_AR_MAP.get(st, st),
                "last_updated": sub["updated_at"] if sub else None,
                "reviewer_notes_ar": sub.get("reviewer_notes_ar") if sub else None,
                "slides": _parse_section_config(p).get("slides", []),
            }
        )

    total = len(enabled_projects)
    done = counts["submitted"] + counts["approved"]
    pct = round((done / total) * 100.0, 1) if total else 100.0
    gens = repo.list_generations(reporting_week_id=wk["id"]) if wk else []

    return {
        "reporting_week": wk,
        "weeks": repo.list_reporting_weeks(),
        "summary": {
            "total_expected": total,
            "submitted": counts["submitted"],
            "reviewed": counts["approved"],
            "draft": counts["draft"],
            "changes_requested": counts["changes_requested"],
            "missing": counts["not_started"],
            "completion_pct": pct,
        },
        "matrix": matrix,
        "generations": gens,
        "unsupported_limitations": [
            "الرسوم البيانية المرتبطة بـ Excel في الشريحة 26 تُحفظ دون تعديل آلي في المرحلة الحالية.",
            "تحريك أشرطة المخطط الزمني (Gantt) وتقسيم الجداول على شرائح إضافية غير مدعوم آلياً بعد.",
        ],
    }


@phase2_router.post("/weeks/{week_id}/submissions/{project_id}/review")
def review_project_submission(
    week_id: str,
    project_id: str,
    payload: ReviewRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    try:
        updated = request.app.state.repo.review_submission(
            reporting_week_id=week_id,
            project_id=project_id,
            status=payload.status,
            reviewer_notes_ar=payload.reviewer_notes_ar,
            reviewer_user_id=user.id,
            kpi_source_user_id=payload.kpi_source_user_id,
            expected_versions=payload.expected_versions,
            kpi_sources=payload.kpi_sources,
        )
        return {"submission": updated, "status_ar": STATUS_AR_MAP.get(updated["status"], updated["status"])}
    except ValueError as exc:
        raise HTTPException(status_code=409,detail={"code":"REVIEW_CONFLICT","message":str(exc)})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})


@phase2_router.post("/weeks/{week_id}/lock")
def lock_week(week_id: str, request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    require_coordinator(user)
    wk = request.app.state.repo.get_reporting_week(week_id)
    if not wk:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "الأسبوع غير موجود."})
    request.app.state.repo.update_week_status(week_id, "locked", actor_user_id=user.id)
    return {"reporting_week": request.app.state.repo.get_reporting_week(week_id)}


@phase2_router.post("/weeks/{week_id}/unlock")
def unlock_week(week_id: str, request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    require_coordinator(user)
    wk = request.app.state.repo.get_reporting_week(week_id)
    if not wk:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "الأسبوع غير موجود."})
    request.app.state.repo.update_week_status(week_id, "open", actor_user_id=user.id)
    return {"reporting_week": request.app.state.repo.get_reporting_week(week_id)}


@phase2_router.patch("/weeks/{week_id}")
def patch_week_deadline(
    week_id: str,
    payload: WeekDeadlinePatch,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    try:
        wk = request.app.state.repo.update_week_deadline(week_id, payload.submission_deadline, actor_user_id=user.id)
        return {"reporting_week": wk}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})


@phase2_router.get("/admin/users")
def list_all_users(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    require_coordinator(user)
    return {"users": request.app.state.repo.list_users()}


@phase2_router.patch("/projects/{project_id}")
def patch_project_settings(
    project_id: str,
    payload: ProjectSettingsPatch,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    try:
        updated = request.app.state.repo.update_project_settings(
            project_id,
            is_enabled=payload.is_enabled,
            owner_user_id=payload.owner_user_id,
            section_config=payload.section_config,
            actor_user_id=user.id,
        )
        return {"project": updated}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})


@phase2_router.delete("/projects/{project_id}/members/{member_user_id}")
def delete_project_member(
    project_id: str,
    member_user_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    request.app.state.repo.remove_project_member(project_id, member_user_id, actor_user_id=user.id)
    return {"status": "removed"}


# --- 4. Missing-Submission Reminders (Copyable Arabic Messages, Zero External Sends) ---
@phase2_router.get("/weeks/{week_id}/reminders")
def get_reminders(
    week_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    repo = request.app.state.repo
    wk = repo.get_reporting_week(week_id)
    if not wk:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "الأسبوع غير موجود."})

    users_by_id = {u["id"]: u for u in repo.list_users()}
    subs_by_proj = {s["project_id"]: s for s in repo.list_submissions_for_week(week_id)}
    deadline_txt = wk.get("submission_deadline") or wk["end_date"]

    reminders = []
    for p in repo.list_projects():
        if not p.get("is_enabled", 1):
            continue
        sub = subs_by_proj.get(p["id"])
        st = sub["status"] if sub else "not_started"
        if st in ("not_started", "draft", "changes_requested"):
            owner = users_by_id.get(p.get("owner_user_id") or "")
            owner_name = owner["full_name_ar"] if owner else "الزميل المسؤول"
            msg = (
                f"السلام عليكم أ. {owner_name}،\n"
                f"تذكير لطيف باستكمال تحديث قسم ({p['title_ar']}) للتقرير الأسبوعي رقم ({wk['week_number']}) "
                f"قبل الموعد النهائي ({deadline_txt}).\n"
                f"الحالة الحالية: {STATUS_AR_MAP.get(st, st)}."
            )
            reminders.append(
                {
                    "project_id": p["id"],
                    "project_title_ar": p["title_ar"],
                    "employee_name_ar": owner_name,
                    "employee_email": owner["email"] if owner else None,
                    "status": st,
                    "status_ar": STATUS_AR_MAP.get(st, st),
                    "deadline": deadline_txt,
                    "copyable_message_ar": msg,
                }
            )
    return {
        "reporting_week_id": week_id,
        "external_dispatch_configured": False,
        "reminders": reminders,
    }


# --- 5. Secure Image Upload (PNG/JPEG, magic bytes, <= 5 MB) ---
@phase2_router.post("/uploads/image", status_code=status.HTTP_201_CREATED)
async def upload_image(
    request: Request,
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    allowed_mimes = {"image/png", "image/jpeg"}
    if file.content_type not in allowed_mimes:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_FILE_TYPE", "message": "يُسمح برفع صور PNG أو JPEG فقط."},
        )
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail={"code": "FILE_TOO_LARGE", "message": "الحد الأقصى لحجم الصورة هو 5 ميجابايت."},
        )
    # Validate magic bytes (PNG or JPEG)
    is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpg = content.startswith(b"\xff\xd8\xff")
    if not (is_png or is_jpg):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_IMAGE_SIGNATURE", "message": "محتوى الملف لا يطابق صورة صالحة."},
        )
    ext = ".png" if is_png else ".jpg"
    uploads_dir: Path = request.app.state.settings.uploads_dir
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"upload_{uuid.uuid4().hex[:12]}{ext}"
    dest = uploads_dir / safe_name
    from app import cloud_storage
    if cloud_storage.enabled():
        cloud_storage.call("upload", "tomoh-uploads", safe_name, content, "image/png" if is_png else "image/jpeg")
    dest.write_bytes(content)
    os.chmod(dest, 0o600)
    return {"file_name": safe_name, "storage_path": str(dest), "size_bytes": len(content)}


# --- 6. Disabled Internal-Only AI Writing Assistant Contract ---
@phase2_router.post("/ai-assistant/improve")
def ai_writing_assistant(
    payload: AiAssistRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    if not request.app.state.settings.ai_assistant_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "AI_ASSISTANT_DISABLED",
                "message": "مساعد الصياغة الذكي معطّل حالياً لحين ربط خدمة ذكاء اصطناعي داخلية معتمدة (لا يتم إرسال أي بيانات خارج الجهة).",
                "details": {
                    "feature_flag": "TOMOH_AI_ASSISTANT_ENABLED",
                    "external_transmission_allowed": False,
                    "guarantees": [
                        "never_invent_achievements",
                        "never_change_numbers",
                        "require_explicit_user_approval",
                    ],
                },
            },
        )
    return {"proposed_text_ar": payload.text_ar, "requires_approval": True}
