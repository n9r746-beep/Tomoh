"""
Phase 4 Release-Candidate Routes:
  - Coordinator-only User Provisioning & Activation (zero passwords; SSO email identity)
  - Coordinator Week-over-Week Diff Preview (compare Current Week vs. Previous Week)
  - Safe Archive Guard (prevents silently archiving a week with zero generated PPTX unless forced)
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import AuthenticatedUser, get_current_user, require_coordinator
from app.db.repository import _now_iso

phase4_router = APIRouter(prefix="/api/v1", tags=["TOMOH Phase 4 Release Candidate API"])


class UserCreateRequest(BaseModel):
    password: Optional[str] = Field(default=None, min_length=12, max_length=200)
    email: str = Field(..., min_length=5, max_length=150)
    full_name_ar: str = Field(..., min_length=2, max_length=120)
    full_name_en: Optional[str] = Field(default=None, max_length=120)
    team_id: Optional[str] = None
    role: Literal["employee", "coordinator", "admin"] = "employee"


class UserStatusPatch(BaseModel):
    is_active: Optional[bool] = None
    role: Optional[Literal["employee", "coordinator", "admin"]] = None


class ArchiveWeekRequest(BaseModel):
    force: bool = False


@phase4_router.post("/admin/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Provision an internal user account bound to corporate email (no password stored)."""
    require_coordinator(user)
    repo = request.app.state.repo
    if request.app.state.settings.auth_mode != "header_dev" and not payload.password:
        raise HTTPException(status_code=422, detail={"code":"PASSWORD_REQUIRED","message":"أدخل كلمة مرور من ١٢ حرفًا على الأقل."})
    uid = f"u-{uuid.uuid4().hex[:8]}"
    now = _now_iso()
    try:
        repo.db.execute(
            """
            INSERT INTO users (id, email, full_name_ar, full_name_en, team_id, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (uid, payload.email.strip().lower(), payload.full_name_ar.strip(), payload.full_name_en, payload.team_id, payload.role, now, now),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "USER_CREATE_FAILED", "message": f"تعذر إنشاء الحساب: {exc}"},
        )
    if payload.password:
        from app.passwords import save
        save(repo, uid, payload.password)
    created = repo.get_user(uid)
    repo.record_audit(entity_type="user", entity_id=uid, action="create_user", actor_user_id=user.id, new_value=created)
    return {"user": created}


@phase4_router.patch("/admin/users/{target_user_id}")
def update_user_status(
    target_user_id: str,
    payload: UserStatusPatch,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    repo = request.app.state.repo
    existing = repo.get_user(target_user_id)
    if not existing:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "المستخدم غير موجود."})
    new_active = (1 if payload.is_active else 0) if payload.is_active is not None else existing["is_active"]
    new_role = payload.role if payload.role is not None else existing["role"]
    repo.db.execute(
        "UPDATE users SET is_active = ?, role = ?, updated_at = ? WHERE id = ?",
        (new_active, new_role, _now_iso(), target_user_id),
    )
    updated = repo.get_user(target_user_id)
    repo.record_audit(
        entity_type="user",
        entity_id=target_user_id,
        action="update_user",
        actor_user_id=user.id,
        old_value=existing,
        new_value=updated,
    )
    return {"user": updated}


@phase4_router.get("/weeks/{week_id}/diff")
def get_week_diff_vs_previous(
    week_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Compare current week's KPIs and project statuses against the immediately preceding week."""
    require_coordinator(user)
    repo = request.app.state.repo
    wk = repo.get_reporting_week(week_id)
    if not wk:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "الأسبوع غير موجود."})

    cur_bundle = repo.get_week_bundle(week_id)
    prev_wk = repo.get_previous_week(wk["week_number"])
    prev_bundle = repo.get_week_bundle(prev_wk["id"]) if prev_wk else None

    prev_kpis = {k["kpi_code"]: k["numeric_value"] for k in (prev_bundle["kpis"] if prev_bundle else [])}
    kpi_diffs: List[Dict[str, Any]] = []
    for k in cur_bundle["kpis"]:
        code = k["kpi_code"]
        old_v = prev_kpis.get(code)
        new_v = k["numeric_value"]
        if old_v != new_v:
            kpi_diffs.append({"kpi_code": code, "label_ar": k["label_ar"], "previous": old_v, "current": new_v})

    prev_statuses = {ps["project_code"]: ps["status_code"] for ps in (prev_bundle["project_statuses"] if prev_bundle else [])}
    status_diffs: List[Dict[str, Any]] = []
    for ps in cur_bundle["project_statuses"]:
        code = ps["project_code"]
        old_s = prev_statuses.get(code)
        new_s = ps["status_code"]
        if old_s != new_s:
            status_diffs.append({"project_code": code, "previous_status": old_s, "current_status": new_s})

    return {
        "current_week": wk,
        "previous_week": prev_wk,
        "kpi_changes": kpi_diffs,
        "status_changes": status_diffs,
        "new_achievements_count": len(cur_bundle["achievements"]),
        "active_tasks_count": len(cur_bundle["upcoming_tasks"]),
    }


@phase4_router.post("/weeks/{week_id}/safe-archive")
def safe_archive_week(
    week_id: str,
    payload: ArchiveWeekRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Archive a reporting week only after at least one successful PPTX generation (unless force=true)."""
    require_coordinator(user)
    repo = request.app.state.repo
    wk = repo.get_reporting_week(week_id)
    if not wk:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "الأسبوع غير موجود."})
    gens = [g for g in repo.list_generations(reporting_week_id=week_id) if g["status"] == "succeeded"]
    if not gens and not payload.force:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ARCHIVE_REQUIRES_GENERATION",
                "message": "لا يمكن أرشفة الأسبوع قبل توليد نسخة PowerPoint ناجحة واحدة على الأقل (أو تفعيل force=true).",
            },
        )
    repo.update_week_status(week_id, "archived", actor_user_id=user.id)
    return {"reporting_week": repo.get_reporting_week(week_id), "generations_count": len(gens)}


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., max_length=200)
    new_password: str = Field(..., min_length=12, max_length=200)

@phase4_router.post("/auth/password")
def change_password(payload: PasswordChangeRequest, request: Request, user: AuthenticatedUser=Depends(get_current_user)):
    from app.passwords import verify, save
    repo=request.app.state.repo
    if not verify(repo,user.id,payload.current_password):
        raise HTTPException(status_code=401,detail={"code":"INVALID_PASSWORD","message":"كلمة المرور الحالية غير صحيحة."})
    save(repo,user.id,payload.new_password)
    repo.db.execute("UPDATE user_sessions SET revoked=1 WHERE user_id=?",(user.id,))
    repo.record_audit(entity_type="user",entity_id=user.id,action="password_changed",actor_user_id=user.id)
    return {"status":"password_changed"}


class ContributorsRequest(BaseModel):
    user_ids: List[str] = Field(default_factory=list, max_items=100)

@phase4_router.put("/projects/{project_id}/contributors")
def set_contributors(project_id: str, payload: ContributorsRequest, request: Request, user: AuthenticatedUser=Depends(get_current_user)):
    require_coordinator(user)
    repo=request.app.state.repo
    if not repo.get_project(project_id):raise HTTPException(status_code=404,detail="القسم غير موجود")
    ids=list(dict.fromkeys(payload.user_ids))
    if any(not repo.get_user(uid) or not repo.get_user(uid)["is_active"] for uid in ids):raise HTTPException(status_code=422,detail="المستخدم غير نشط أو غير موجود")
    with repo.db.transaction():
        wk=repo.get_current_reporting_week()
        if wk:
            repo.db.lock_reporting_week(wk['id'])
            if repo.db.fetch_one("SELECT id FROM project_approvals WHERE reporting_week_id=? AND project_id=?",(wk['id'],project_id)):
                raise HTTPException(status_code=409,detail={"code":"SECTION_APPROVED","message":"أعد فتح القسم للتعديل قبل تغيير المسؤولين."})
        old=repo.list_project_members(project_id)
        repo.db.execute("DELETE FROM project_members WHERE project_id=? AND member_role IN ('manager','contributor')",(project_id,))
        for uid in ids:
            repo.assign_project_member(project_id=project_id,user_id=uid,member_role="contributor",actor_user_id=user.id)
        repo.db.execute("UPDATE projects SET owner_user_id=?,updated_at=? WHERE id=?",(ids[0] if ids else None,_now_iso(),project_id))
        repo.record_audit(entity_type="project_members",entity_id=project_id,action="set_contributors",actor_user_id=user.id,old_value={"members":old},new_value={"user_ids":ids})
    return {"members":repo.list_project_members(project_id)}

@phase4_router.get("/weeks/{week_id}/projects/{project_id}/contributions")
def review_contributions(week_id: str, project_id: str, request: Request, user: AuthenticatedUser=Depends(get_current_user)):
    require_coordinator(user)
    from app.collaboration import section_state
    repo=request.app.state.repo
    project=repo.get_project(project_id)
    if not project or not repo.get_reporting_week(week_id):raise HTTPException(status_code=404,detail="القسم أو الأسبوع غير موجود")
    state=section_state(repo,week_id,project)
    return {"project":project,"status":state["status"],"approval":state["approval"],"expected_versions":{s["id"]:s["version"] for s in state["submissions"]},"contributors":[{**c,"detail":repo.get_project_week_detail(week_id,project_id,c["user_id"])} for c in state["contributors"]],"kpi_conflicts":[c for c in repo.get_week_bundle(week_id).get("kpi_conflicts",[]) if c["project_id"]==project_id]}
