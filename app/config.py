"""Environment-driven application configuration (zero hardcoded credentials)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_url: str
    template_pptx_path: Path
    mapping_config_path: Path
    migrations_dir: Path
    output_dir: Path
    auth_mode: str = "session_password"  # "session_password" | "header_dev" | "external_oidc"
    enable_visual_validation: bool = False
    uploads_dir: Path = BASE_DIR / "uploads"
    frontend_dir: Path = BASE_DIR / "frontend"
    ai_assistant_enabled: bool = False  # Disabled by default; never sends data to external AI

    @classmethod
    def from_env(cls) -> "Settings":
        auth_mode = os.environ.get("TOMOH_AUTH_MODE", "session_password")
        if os.environ.get("VERCEL") and auth_mode == "header_dev":
            raise RuntimeError("Development header authentication is forbidden on Vercel.")
        return cls(
            database_url=os.environ.get(
                "TOMOH_DATABASE_URL",
                f"sqlite:///{BASE_DIR / 'tomoh_local.db'}",
            ),
            template_pptx_path=Path(
                os.environ.get(
                    "TOMOH_TEMPLATE_PPTX",
                    str(BASE_DIR / "private" / "master_template.pptx"),
                )
            ),
            mapping_config_path=Path(
                os.environ.get(
                    "TOMOH_MAPPING_CONFIG",
                    str(BASE_DIR / "config" / "mapping_config.json"),
                )
            ),
            migrations_dir=Path(
                os.environ.get("TOMOH_MIGRATIONS_DIR", str(BASE_DIR / "migrations"))
            ),
            output_dir=Path(
                os.environ.get("TOMOH_OUTPUT_DIR", str(BASE_DIR / "generated_reports"))
            ),
            uploads_dir=Path(
                os.environ.get("TOMOH_UPLOADS_DIR", str(BASE_DIR / "uploads"))
            ),
            frontend_dir=Path(
                os.environ.get("TOMOH_FRONTEND_DIR", str(BASE_DIR / "frontend"))
            ),
            auth_mode=auth_mode,
            enable_visual_validation=os.environ.get("TOMOH_VISUAL_VALIDATION", "false").lower() == "true",
            ai_assistant_enabled=os.environ.get("TOMOH_AI_ASSISTANT_ENABLED", "false").lower() == "true",
        )
