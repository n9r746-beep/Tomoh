"""Idempotent SQL migration runner supporting PostgreSQL and SQLite (Migrations 001–003)."""

from __future__ import annotations

from pathlib import Path
from typing import List

from app.db.database import Database


def run_migrations(db: Database, migrations_dir: Path) -> List[str]:
    schema_file = (
        migrations_dir / "001_initial_schema_sqlite.sql"
        if db.dialect == "sqlite"
        else migrations_dir / "001_initial_schema.sql"
    )
    seed_file = migrations_dir / "002_seed_tomoh_master.sql"
    phase2_file = (
        migrations_dir / "003_phase2_webapp_features_sqlite.sql"
        if db.dialect == "sqlite"
        else migrations_dir / "003_phase2_webapp_features.sql"
    )

    migration_plan = [
        ("001_initial_schema", schema_file),
        ("002_seed_tomoh_master", seed_file),
        ("003_phase2_webapp_features", phase2_file),
    ]

    applied_now: List[str] = []

    for version, path in migration_plan:
        if not path.exists():
            raise FileNotFoundError(f"Migration file not found: {path}")

        already_applied = False
        try:
            row = db.fetch_one("SELECT version FROM schema_migrations WHERE version = ?", (version,))
            already_applied = row is not None
        except Exception:
            already_applied = False

        if already_applied:
            continue

        sql_text = path.read_text(encoding="utf-8")
        if db.dialect == "postgresql" and version == "002_seed_tomoh_master":
            sql_text = sql_text.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            lines = []
            for stmt in sql_text.split(";"):
                s = stmt.strip()
                if s and s.upper().startswith("INSERT INTO"):
                    lines.append(s + " ON CONFLICT DO NOTHING;")
                elif s:
                    lines.append(s + ";")
            sql_text = "\n".join(lines)

        db.execute_script(sql_text)
        db.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        applied_now.append(version)

    return applied_now
