"""Authenticated slide backgrounds and field geometry. No employee content is stored in assets."""
import json
from functools import lru_cache
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
import os
import urllib.request
from app.auth import get_current_user, require_project_write_access, AuthenticatedUser

slide_router=APIRouter(prefix="/api/v1",tags=["Slide editor"])
ASSETS=Path(__file__).resolve().parent.parent/"slide_assets"

BLOB_BASE="https://hfxbs9ixyifnnch6.private.blob.vercel-storage.com/templates/v1"
@lru_cache(maxsize=24)
def asset(name):
    local=ASSETS/name
    if local.exists():return local.read_bytes()
    token=os.environ.get("BLOB_READ_WRITE_TOKEN")
    if not token:raise HTTPException(503,detail={"code":"SLIDE_TEMPLATE_UNAVAILABLE","message":"تعذر تحميل قالب الشريحة. استخدم نموذج التعبئة."})
    req=urllib.request.Request(BLOB_BASE+"/"+name,headers={"Authorization":"Bearer "+token})
    try:
        with urllib.request.urlopen(req,timeout=25) as res:
            data=res.read(2*1024*1024+1)
            if len(data)>2*1024*1024:raise ValueError("asset too large")
            return data
    except Exception:
        raise HTTPException(503,detail={"code":"SLIDE_TEMPLATE_UNAVAILABLE","message":"تعذر تحميل قالب الشريحة. استخدم نموذج التعبئة."})

@lru_cache(maxsize=1)
def manifest():
    return json.loads(asset("manifest.json"))

def section(request,user,week_id,project_id):
    repo=request.app.state.repo
    require_project_write_access(repo,user,project_id)
    project=repo.get_project(project_id)
    if not project or not repo.get_reporting_week(week_id):
        raise HTTPException(404,detail={"code":"NOT_FOUND","message":"القسم أو الأسبوع غير موجود."})
    cfg=json.loads(project.get("section_config_json") or "{}")
    return project,cfg

@slide_router.get("/weeks/{week_id}/projects/{project_id}/slides")
def slides(week_id:str,project_id:str,request:Request,user:AuthenticatedUser=Depends(get_current_user)):
    project,cfg=section(request,user,week_id,project_id)
    meta=manifest()
    pages=[]
    for number in cfg.get("slides",[]):
        page=meta["slides"].get(str(number))
        if not page:continue
        pages.append({**page,"image_url":f"/api/v1/weeks/{week_id}/projects/{project_id}/slides/{number}/background"})
    if not pages:
        raise HTTPException(503,detail={"code":"SLIDE_TEMPLATE_UNAVAILABLE","message":"تعذر تحميل قالب الشرائح. يمكنك استخدام نموذج التعبئة."})
    return {"width":meta["width"],"height":meta["height"],"slides":pages}

@slide_router.get("/weeks/{week_id}/projects/{project_id}/slides/{number}/background")
def background(week_id:str,project_id:str,number:int,request:Request,user:AuthenticatedUser=Depends(get_current_user)):
    _,cfg=section(request,user,week_id,project_id)
    if number not in cfg.get("slides",[]) or str(number) not in manifest()["slides"]:
        raise HTTPException(404,detail={"code":"SLIDE_NOT_IN_SECTION","message":"الشريحة غير موجودة في هذا القسم."})
    return Response(asset(f"slide-{number}.webp"),media_type="image/webp",headers={"Cache-Control":"private, no-store"})
