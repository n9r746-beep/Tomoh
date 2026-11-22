"""FastAPI application factory for TOMOH Weekly Report Automation (Phase 3 Security-Hardened)."""

from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.phase2_routes import phase2_router
from app.api.phase4_routes import phase4_router
from app.api.routes import router
from app.config import Settings
from app.db.database import Database
from app.db.migrator import run_migrations
from app.db.phase2_repo_ext import attach_phase2_methods
from app.db.repository import TomohRepository
from app.engine.mapping import MappingRegistry
from app.logging_config import configure_logging
from app.services.lifecycle_service import LifecycleService
from app.services.report_service import ReportService

attach_phase2_methods(TomohRepository)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    configure_logging()
    cfg = settings or Settings.from_env()
    db = Database(cfg.database_url)
    if __import__("os").environ.get("TOMOH_SKIP_MIGRATIONS") != "true":
        run_migrations(db, cfg.migrations_dir)

    repo = TomohRepository(db)
    lifecycle = LifecycleService(repo)
    registry = MappingRegistry(cfg.mapping_config_path)
    report_service = ReportService(
        settings=cfg,
        repo=repo,
        lifecycle=lifecycle,
        registry=registry,
    )

    orig_generate = report_service.generate_weekly_pptx

    def _generate_with_snapshot(*args, **kwargs):
        res = orig_generate(*args, **kwargs)
        wk_id = kwargs.get("reporting_week_id") or (args[0] if args else None)
        if wk_id and res.get("generation", {}).get("id"):
            snapshot = repo.get_week_bundle(wk_id)
            repo.save_generation_snapshot(res["generation"]["id"], snapshot)
        return res

    report_service.generate_weekly_pptx = _generate_with_snapshot  # type: ignore

    app = FastAPI(
        title="TOMOH Weekly Report Automation System",
        version="5.0.0",
        description="Security-hardened Arabic RTL internal web app & surgical OOXML engine for TOMOH Growth Relations.",
    )
    app.state.settings = cfg
    app.state.db = db
    app.state.repo = repo
    app.state.lifecycle = lifecycle
    app.state.registry = registry
    app.state.report_service = report_service

    # Phase 3 Security Middleware: Strict Security Headers + CSRF Header Guard on Cookie Writes
    @app.middleware("http")
    async def security_headers_and_csrf(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.cookies.get("tomoh_session"):
            from urllib.parse import urlsplit
            origin = request.headers.get("Origin")
            if not request.headers.get("X-Requested-With") or (origin and urlsplit(origin).netloc != request.headers.get("host")):
                return JSONResponse(status_code=403, content={"error":{"code":"CSRF_BLOCKED","message":"تعذر التحقق من مصدر الطلب."}})

        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none';"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "HTTP_ERROR", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content={"error": detail})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "SCHEMA_VALIDATION_ERROR",
                    "message": "البيانات المدخلة غير صالحة، يرجى مراجعة الحقول.",
                    "details": {"errors": exc.errors()},
                }
            },
        )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "version": "5.0.0",
            "dialect": db.dialect,
            "mapping_schema": registry.schema_version,
            "template_present": cfg.template_pptx_path.exists(),
        }

    # Archive Week Endpoint (Phase 3 lifecycle completion)
    @app.post("/api/v1/weeks/{week_id}/archive")
    def archive_week(week_id: str, request: Request):
        from app.auth import get_current_user, require_coordinator
        user = get_current_user(
            request,
            x_user_id=request.headers.get("X-User-Id"),
            x_session_token=request.headers.get("X-Session-Token"),
            tomoh_session=request.cookies.get("tomoh_session"),
        )
        require_coordinator(user)
        wk = repo.get_reporting_week(week_id)
        if not wk:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "الأسبوع غير موجود."})
        repo.update_week_status(week_id, "archived", actor_user_id=user.id)
        return {"reporting_week": repo.get_reporting_week(week_id)}

    app.include_router(router)
    app.include_router(phase2_router)
    app.include_router(phase4_router)

    if cfg.frontend_dir.exists():
        assets_dir = cfg.frontend_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
        app.mount("/static", StaticFiles(directory=str(cfg.frontend_dir)), name="static")

        @app.get("/", include_in_schema=False)
        def serve_index():
            return FileResponse(str(cfg.frontend_dir / "index.html"))

    return app


app = create_app()
