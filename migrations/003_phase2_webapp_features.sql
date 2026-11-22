-- TOMOH Weekly Report Automation — Migration 003: Phase 2 Web App Features (PostgreSQL)

CREATE TABLE IF NOT EXISTS user_sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked     BOOLEAN NOT NULL DEFAULT FALSE
);

ALTER TABLE reporting_weeks ADD COLUMN IF NOT EXISTS submission_deadline TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS section_config_json TEXT;
ALTER TABLE report_generations ADD COLUMN IF NOT EXISTS input_snapshot_json TEXT;
