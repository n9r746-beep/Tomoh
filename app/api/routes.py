"""FastAPI REST endpoints for TOMOH Weekly Report Automation (Hardened Phase 3 RBAC)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.auth import (
    AuthenticatedUser,
    get_current_user,
    require_coordinator,
    require_project_write_access,
)
from app.schemas import (
    GenerateReportRequest,
    ProjectAssignmentCreate,
    ProjectCreate,
    ReportingWeekCreate,
    WeeklySubmissionPayload,
)

router = APIRouter(prefix="/api/v1", tags=["TOMOH Weekly Report API"])


# --- 1. Projects & Assignments (Scoped by RBAC) ---
@router.get("/projects")
def list_projects(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    repo = request.app.state.repo
    include_all = user.role in ("coordinator", "admin")
    return {"projects": repo.list_assigned_projects(user.id, include_all=include_all)}


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    try:
        proj = request.app.state.repo.create_project(payload.dict(), actor_user_id=user.id)
        return {"project": proj}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "PROJECT_CREATE_FAILED", "message": str(exc)},
        )


@router.get("/projects/{project_id}/members")
def list_project_members(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    repo = request.app.state.repo
    if not repo.get_project(project_id):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Project not found"})
    require_project_write_access(repo, user, project_id)
    return {"members": repo.list_project_members(project_id)}


@router.post("/projects/{project_id}/members", status_code=status.HTTP_201_CREATED)
def assign_project_member(
    project_id: str,
    payload: ProjectAssignmentCreate,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    if not request.app.state.repo.get_project(project_id):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Project not found"})
    if not request.app.state.repo.get_user(payload.user_id):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "User not found"})
    member = request.app.state.repo.assign_project_member(
        project_id, payload.user_id, payload.member_role, actor_user_id=user.id
    )
    return {"member": member}


# --- 2. Reporting Weeks ---
@router.post("/weeks", status_code=status.HTTP_201_CREATED)
def create_reporting_week(
    payload: ReportingWeekCreate,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    try:
        return request.app.state.lifecycle.create_reporting_week(payload, actor_user_id=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"code": "WEEK_CREATE_FAILED", "message": str(exc)})


@router.get("/weeks")
def list_reporting_weeks(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    return {"weeks": request.app.state.repo.list_reporting_weeks()}


@router.get("/weeks/current")
def get_current_reporting_week(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    wk = request.app.state.repo.get_current_reporting_week()
    if not wk:
        raise HTTPException(status_code=404, detail={"code": "NO_ACTIVE_WEEK", "message": "No reporting weeks exist yet"})
    return {"reporting_week": wk}


# --- 3. Weekly Submissions & Updates (Horizontal RBAC Enforced) ---
@router.get("/weeks/{week_id}/submissions")
def get_week_submissions(
    week_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    repo = request.app.state.repo
    if not repo.get_reporting_week(week_id):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Reporting week not found"})
    subs = repo.list_submissions_for_week(week_id)
    if user.role not in ("coordinator", "admin"):
        allowed_pids = {p["id"] for p in repo.list_assigned_projects(user.id, include_all=False)}
        subs = [s for s in subs if s["project_id"] in allowed_pids]
    return {"submissions": subs}


@router.post("/weeks/{week_id}/submissions", status_code=status.HTTP_201_CREATED)
def submit_weekly_update(
    week_id: str,
    payload: WeeklySubmissionPayload,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_project_write_access(request.app.state.repo, user, payload.project_id)
    try:
        return request.app.state.lifecycle.submit_weekly_update(
            week_id,
            payload,
            actor_user_id=user.id,
            uploads_dir=request.app.state.settings.uploads_dir,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail={"code": "WEEK_LOCKED", "message": str(exc)})
    except ValueError as exc:
        msg = str(exc)
        if "CONFLICT" in msg:
            code, sc = "VERSION_CONFLICT", 409
        elif "INVALID_IMAGE_PATH" in msg:
            code, sc = "INVALID_IMAGE_PATH", 400
        else:
            code, sc = "VALIDATION_ERROR", 422
        raise HTTPException(status_code=sc, detail={"code": code, "message": msg})


@router.put("/weeks/{week_id}/submissions/{project_id}")
def update_weekly_submission(
    week_id: str,
    project_id: str,
    payload: WeeklySubmissionPayload,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    if payload.project_id != project_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "PROJECT_ID_MISMATCH", "message": "Path project_id must match payload project_id"},
        )
    require_project_write_access(request.app.state.repo, user, project_id)
    try:
        return request.app.state.lifecycle.submit_weekly_update(
            week_id,
            payload,
            actor_user_id=user.id,
            uploads_dir=request.app.state.settings.uploads_dir,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail={"code": "WEEK_LOCKED", "message": str(exc)})
    except ValueError as exc:
        msg = str(exc)
        if "CONFLICT" in msg:
            code, sc = "VERSION_CONFLICT", 409
        elif "INVALID_IMAGE_PATH" in msg:
            code, sc = "INVALID_IMAGE_PATH", 400
        else:
            code, sc = "VALIDATION_ERROR", 422
        raise HTTPException(status_code=sc, detail={"code": code, "message": msg})


# --- 4. KPIs, Completeness & Preview (Scoped by RBAC) ---
@router.get("/weeks/{week_id}/kpis")
def get_week_kpis(
    week_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    repo = request.app.state.repo
    if not repo.get_reporting_week(week_id):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Reporting week not found"})
    defs = repo.list_kpi_definitions()
    vals = repo.list_kpi_values_for_week(week_id)
    if user.role not in ("coordinator", "admin"):
        allowed_pids = {p["id"] for p in repo.list_assigned_projects(user.id, include_all=False)}
        defs = [d for d in defs if d.get("project_id") in allowed_pids]
        allowed_def_ids = {d["id"] for d in defs}
        vals = [v for v in vals if v.get("kpi_definition_id") in allowed_def_ids]
    return {"definitions": defs, "values": vals}


@router.get("/weeks/{week_id}/completeness")
def get_week_completeness(
    week_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    try:
        return request.app.state.lifecycle.compute_completeness(week_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})


@router.get("/weeks/{week_id}/preview")
def preview_week_report(
    week_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    try:
        return request.app.state.report_service.preview_week_report(week_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})


# --- 5. PowerPoint Generation, Download & Historical Reports ---
@router.post("/weeks/{week_id}/generate", status_code=status.HTTP_201_CREATED)
def generate_report(
    week_id: str,
    payload: GenerateReportRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    try:
        return request.app.state.report_service.generate_weekly_pptx(
            reporting_week_id=week_id,
            actor_user_id=user.id,
            allow_incomplete=payload.allow_incomplete,
            run_visual_validation=payload.run_visual_validation,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)})
    except RuntimeError as exc:
        if "GENERATION_IN_PROGRESS" in str(exc):
            raise HTTPException(status_code=409, detail={"code": "GENERATION_IN_PROGRESS", "message": str(exc)})
        raise HTTPException(status_code=500, detail={"code": "GENERATION_FAILED", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "GENERATION_BLOCKED", "message": str(exc)})


@router.get("/generations")
def list_generations(
    request: Request,
    week_id: Optional[str] = None,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    return {"generations": request.app.state.repo.list_generations(reporting_week_id=week_id)}


@router.get("/generations/{generation_id}/download")
def download_generated_pptx(
    generation_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    require_coordinator(user)
    gen = request.app.state.repo.get_generation(generation_id)
    if not gen:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Generation record not found"})
    if gen["output_pptx_path"].startswith("supabase://tomoh-reports/"):
        from app import cloud_storage
        from fastapi.responses import RedirectResponse
        name = gen["output_pptx_path"].split("/")[-1]
        result = cloud_storage.call("sign", "tomoh-reports", name)
        return RedirectResponse(result["url"], status_code=303)
    path = Path(gen["output_pptx_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail={"code": "FILE_MISSING", "message": "Generated PPTX file missing on disk"})
    return FileResponse(
        path=str(path),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=path.name,
    )
