-- TOMOH Weekly Report Automation — Migration 001: Initial Schema (PostgreSQL 16+)
-- Separates Permanent Master Data, Weekly Reporting Data, and Immutable Audit History.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 1. Teams
CREATE TABLE IF NOT EXISTS teams (
    id          TEXT PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name_ar     TEXT NOT NULL,
    name_en     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Users
CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    full_name_ar TEXT NOT NULL,
    full_name_en TEXT,
    team_id     TEXT REFERENCES teams(id),
    role        TEXT NOT NULL CHECK (role IN ('employee', 'coordinator', 'admin')),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Projects (Permanent Master Registry)
CREATE TABLE IF NOT EXISTS projects (
    id                  TEXT PRIMARY KEY,
    project_code        TEXT NOT NULL UNIQUE,
    title_ar            TEXT NOT NULL,
    category            TEXT NOT NULL CHECK (category IN ('operational_track', 'internal_priority', 'department_kpi', 'news_and_events')),
    fiscal_year         INTEGER NOT NULL,
    description_ar      TEXT,
    deliverables_ar     TEXT,
    owner_user_id       TEXT REFERENCES users(id),
    team_id             TEXT REFERENCES teams(id),
    estimated_budget_ar TEXT,
    linked_kpi_ar       TEXT,
    rfp_linked          BOOLEAN NOT NULL DEFAULT FALSE,
    service_providers_ar TEXT,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Project Members (Assignment & RBAC scope)
CREATE TABLE IF NOT EXISTS project_members (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    member_role TEXT NOT NULL CHECK (member_role IN ('manager', 'contributor', 'viewer')),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, user_id)
);

-- 5. Reporting Weeks
CREATE TABLE IF NOT EXISTS reporting_weeks (
    id              TEXT PRIMARY KEY,
    week_number     INTEGER NOT NULL UNIQUE,
    fiscal_year     INTEGER NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    report_title_ar TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('open', 'in_review', 'locked', 'generated', 'archived')) DEFAULT 'open',
    created_by      TEXT REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. Weekly Submissions
CREATE TABLE IF NOT EXISTS weekly_submissions (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    submitted_by        TEXT NOT NULL REFERENCES users(id),
    reviewed_by         TEXT REFERENCES users(id),
    status              TEXT NOT NULL CHECK (status IN ('draft', 'submitted', 'changes_requested', 'approved')) DEFAULT 'draft',
    version             INTEGER NOT NULL DEFAULT 1,
    reviewer_notes_ar   TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (reporting_week_id, project_id)
);

-- 7. KPI Definitions (Permanent Catalog)
CREATE TABLE IF NOT EXISTS kpi_definitions (
    id                  TEXT PRIMARY KEY,
    kpi_code            TEXT NOT NULL UNIQUE,
    project_id          TEXT REFERENCES projects(id),
    label_ar            TEXT NOT NULL,
    aggregation_type    TEXT NOT NULL CHECK (aggregation_type IN ('weekly_delta', 'ytd_cumulative', 'all_time_cumulative', 'percentage', 'ratio', 'annual_target')),
    auto_accumulate_from TEXT,  -- Optional kpi_code; NULL means DO NOT auto-recalculate cumulative values
    annual_target       DOUBLE PRECISION,
    unit_format         TEXT NOT NULL DEFAULT 'int',
    owner_user_id       TEXT REFERENCES users(id),
    is_active           BOOLEAN NOT NULL DEFAULT TRUE
);

-- 8. KPI Values (Weekly & Cumulative — preserves NULL vs 0 explicitly)
CREATE TABLE IF NOT EXISTS kpi_values (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT REFERENCES projects(id),
    kpi_definition_id   TEXT NOT NULL REFERENCES kpi_definitions(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    numeric_value       DOUBLE PRECISION,       -- NULL = missing/not submitted (NEVER silently converted to 0)
    denominator_value   DOUBLE PRECISION,       -- Used for ratio KPIs e.g. 12/15
    is_unchanged        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (reporting_week_id, kpi_definition_id)
);

-- 9. Achievements (Weekly — NEVER blindly duplicated into next week)
CREATE TABLE IF NOT EXISTS achievements (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT NOT NULL REFERENCES projects(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    slot_index          INTEGER NOT NULL,
    content_ar          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (reporting_week_id, project_id, slot_index)
);

-- 10. Upcoming Tasks & Meeting Action Items
CREATE TABLE IF NOT EXISTS upcoming_tasks (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT REFERENCES projects(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    task_kind           TEXT NOT NULL CHECK (task_kind IN ('project_task', 'meeting_action_item')),
    sequence_no         INTEGER NOT NULL,
    title_ar            TEXT NOT NULL,
    owner_label_ar      TEXT,
    expected_due_date   TEXT,
    weekly_update_ar    TEXT,
    task_status         TEXT NOT NULL CHECK (task_status IN ('جاري', 'مكتمل', 'متأخر', 'معلق', 'ملغي')) DEFAULT 'جاري',
    carried_from_id     TEXT REFERENCES upcoming_tasks(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 11. Challenges & Required Support
CREATE TABLE IF NOT EXISTS challenges (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT NOT NULL REFERENCES projects(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    challenge_ar        TEXT NOT NULL,
    support_needed_ar   TEXT,
    is_resolved         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 12. Project Statuses (Weekly Snapshot)
CREATE TABLE IF NOT EXISTS project_statuses (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT NOT NULL REFERENCES projects(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    status_code         TEXT NOT NULL CHECK (status_code IN ('on_track', 'delayed', 'critically_delayed', 'on_hold', 'completed', 'not_started')),
    progress_note_ar    TEXT,
    deliverables_override_ar TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (reporting_week_id, project_id)
);

-- 13. Events (Calendar & Beneficiaries)
CREATE TABLE IF NOT EXISTS events (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT REFERENCES projects(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    slot_key            TEXT NOT NULL,          -- e.g., 'CAL_2026_DEC_1'
    title_ar            TEXT NOT NULL,
    event_date_label    TEXT,
    lead_names_ar       TEXT,
    event_status        TEXT NOT NULL DEFAULT 'على المسار',
    beneficiaries_count INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (reporting_week_id, slot_key)
);

-- 14. News
CREATE TABLE IF NOT EXISTS news (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT REFERENCES projects(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    slot_index          INTEGER NOT NULL,
    headline_ar         TEXT,
    body_ar             TEXT NOT NULL,
    attachment_id       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (reporting_week_id, slot_index)
);

-- 15. Attachments (Images & Files)
CREATE TABLE IF NOT EXISTS attachments (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    entity_type         TEXT NOT NULL,
    entity_id           TEXT NOT NULL,
    file_name           TEXT NOT NULL,
    mime_type           TEXT NOT NULL,
    storage_path        TEXT NOT NULL,
    uploaded_by         TEXT NOT NULL REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 16. Slide Mappings (DB-backed Mirror of mapping_config.json)
CREATE TABLE IF NOT EXISTS slide_mappings (
    id                  TEXT PRIMARY KEY,
    template_version    TEXT NOT NULL,
    slide_number        INTEGER NOT NULL,
    object_type         TEXT NOT NULL,
    object_id           TEXT NOT NULL,
    field_key           TEXT NOT NULL,
    data_type           TEXT NOT NULL,
    format_rule         TEXT NOT NULL,
    validation_json     TEXT,
    fallback_behavior   TEXT NOT NULL DEFAULT 'preserve_template',
    UNIQUE (template_version, slide_number, field_key)
);

-- 17. Report Generations
CREATE TABLE IF NOT EXISTS report_generations (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    triggered_by        TEXT NOT NULL REFERENCES users(id),
    template_sha256     TEXT NOT NULL,
    output_pptx_path    TEXT NOT NULL,
    output_sha256       TEXT,
    status              TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    validation_json     TEXT,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 18. Audit History (Immutable Append-Only Log)
CREATE TABLE IF NOT EXISTS audit_history (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT REFERENCES reporting_weeks(id),
    entity_type         TEXT NOT NULL,
    entity_id           TEXT NOT NULL,
    action              TEXT NOT NULL,
    actor_user_id       TEXT NOT NULL REFERENCES users(id),
    old_value_json      TEXT,
    new_value_json      TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
