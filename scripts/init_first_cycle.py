#!/usr/bin/env python3
"""
TOMOH Weekly Report Automation — First Reporting Cycle Bootstrap CLI.
Idempotently initializes the next reporting week from the immutable original template,
carrying forward persistent projects and annual KPI targets without touching historical weeks.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.config import Settings
from app.db.database import Database
from app.db.migrator import run_migrations
from app.db.phase2_repo_ext import attach_phase2_methods
from app.db.repository import TomohRepository
from app.schemas import ReportingWeekCreate
from app.services.lifecycle_service import LifecycleService

attach_phase2_methods(TomohRepository)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a TOMOH reporting cycle idempotently.")
    parser.add_argument("--week-number", type=int, required=True, help="Target report week number (e.g., 45)")
    parser.add_argument("--fiscal-year", type=int, default=2026)
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--deadline", default=None, help="Optional submission deadline string")
    parser.add_argument("--actor", default="u-coord", help="Coordinator user ID")
    args = parser.parse_args()

    cfg = Settings.from_env()
    db = Database(cfg.database_url)
    run_migrations(db, cfg.migrations_dir)
    repo = TomohRepository(db)
    lifecycle = LifecycleService(repo)

    existing = repo.db.fetch_one("SELECT * FROM reporting_weeks WHERE week_number = ?", (args.week_number,))
    if existing:
        print(json.dumps({"status": "already_exists", "reporting_week": existing}, ensure_ascii=False))
        return 0

    prev = repo.get_previous_week(args.week_number)
    res = lifecycle.create_reporting_week(
        ReportingWeekCreate(
            week_number=args.week_number,
            fiscal_year=args.fiscal_year,
            start_date=args.start_date,
            end_date=args.end_date,
            carry_forward_from_week_id=prev["id"] if prev else None,
        ),
        actor_user_id=args.actor,
    )
    if args.deadline:
        repo.update_week_deadline(res["reporting_week"]["id"], args.deadline, actor_user_id=args.actor)
        res["reporting_week"] = repo.get_reporting_week(res["reporting_week"]["id"])

    print(json.dumps({"status": "created", **res}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
