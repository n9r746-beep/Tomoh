"""
Pluggable RBAC & Session Authentication Layer.
Supports server-side HttpOnly session cookies (`tomoh_session`), `X-Session-Token`,
and local-dev `X-User-Id` header (disabled when TOMOH_AUTH_MODE=external_oidc).
Zero hardcoded credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from fastapi import Cookie, Header, HTTPException, Request, status


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str
    full_name_ar: str
    role: str  # "employee" | "coordinator" | "admin"


def get_current_user(
    request: Request,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_session_token: Optional[str] = Header(default=None, alias="X-Session-Token"),
    tomoh_session: Optional[str] = Cookie(default=None, alias="tomoh_session"),
) -> AuthenticatedUser:
    settings = request.app.state.settings
    repo = request.app.state.repo

    if settings.auth_mode == "external_oidc":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "code": "AUTH_PROVIDER_NOT_CONFIGURED",
                "message": "External OIDC provider hook must be configured for production deployment.",
            },
        )

    user = None
    token = x_session_token or tomoh_session
    if token:
        user = repo.get_user_by_session(token)
    elif x_user_id and settings.auth_mode == "header_dev":
        user = repo.get_user(x_user_id)

    if not user or not user.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHENTICATED",
                "message": "يرجى تسجيل الدخول للمتابعة.",
            },
        )

    return AuthenticatedUser(
        id=user["id"],
        email=user["email"],
        full_name_ar=user["full_name_ar"],
        role=user["role"],
    )


def require_coordinator(user: AuthenticatedUser) -> None:
    if user.role not in ("coordinator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN_COORDINATOR_ONLY",
                "message": "هذا الإجراء متاح للمنسق أو مدير النظام فقط.",
            },
        )


def require_project_write_access(repo, user: AuthenticatedUser, project_id: str) -> None:
    if user.role in ("coordinator", "admin"):
        return
    if not repo.user_can_edit_project(user.id, project_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN_PROJECT_ACCESS",
                "message": f"ليس لديك صلاحية تعديل هذا القسم ({project_id}).",
            },
        )
