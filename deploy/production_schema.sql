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
    is_active   INTEGER NOT NULL DEFAULT 1,
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
    rfp_linked          INTEGER NOT NULL DEFAULT 0,
    service_providers_ar TEXT,
    is_active           INTEGER NOT NULL DEFAULT 1,
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
    is_active           INTEGER NOT NULL DEFAULT 1
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
    is_unchanged        INTEGER NOT NULL DEFAULT 0,
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
    is_resolved         INTEGER NOT NULL DEFAULT 0,
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

-- TOMOH Weekly Report Automation — Migration 003: Phase 2 Web App Features (PostgreSQL)

CREATE TABLE IF NOT EXISTS user_sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked     INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE reporting_weeks ADD COLUMN IF NOT EXISTS submission_deadline TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS is_enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS section_config_json TEXT;
ALTER TABLE report_generations ADD COLUMN IF NOT EXISTS input_snapshot_json TEXT;

-- TOMOH Weekly Report Automation — Production Clean Master Seed (PostgreSQL)
-- Seeds ONLY permanent department structure, projects, and KPI definitions.
-- ZERO synthetic test users, ZERO synthetic weekly submissions.

INSERT INTO teams (id, code, name_ar, name_en) VALUES
  ('team-growth', 'GROWTH_REL', 'إدارة علاقات نمو المنشآت – طموح', 'TOMOH Growth Relations'),
  ('team-rm', 'REL_MGRS', 'فريق مدراء العلاقة', 'Relationship Managers'),
  ('team-enablers', 'ENABLERS', 'فريق الجهات الممكنة والفعاليات', 'Enablers & Events')
ON CONFLICT (id) DO NOTHING;

INSERT INTO projects (id, project_code, title_ar, category, fiscal_year, team_id, is_enabled, section_config_json) VALUES
  ('proj-platform', 'PLATFORM_KPI', 'احصائيات منصة طموح و SMI', 'department_kpi', 2026, 'team-growth', 1, '{"slides":[4,5,6,7,9,10],"inputs":["kpis"],"required":["kpis"],"kpi_codes":["SMI_WEEKLY","SMI_CUMULATIVE_2026","SMI1_CUMULATIVE_TOTAL","SMI1_COMPLETION_PCT","REG_COMPANIES_WEEKLY","REG_COMPANIES_2026","REG_COMPANIES_ALL_TIME","REG_COMPANIES_TARGET_2026","DIAGNOSTIC_REPORTS_WEEKLY","DIAGNOSTIC_REPORTS_2026","DIAGNOSTIC_REPORTS_ALL_TIME","SMI1_RM_FAHAD_WEEKLY","SMI1_RM_MOHAMMED_WEEKLY","SMI1_RM_FAISAL_WEEKLY","SMI1_RM_KHALID_WEEKLY","SMI1_RM_TOTAL_WEEKLY"]}'),
  ('proj-p1-3', 'P1_3', 'مشروع 1.3: الحملة الإعلامية', 'operational_track', 2026, 'team-growth', 1, '{"slides":[16],"inputs":["achievements","upcoming_tasks"],"required":["achievements","upcoming_tasks"],"max_achievements":3,"max_tasks":1}'),
  ('proj-p1-4', 'P1_4', 'مشروع 1.4: الأنشطة والفعاليات', 'operational_track', 2026, 'team-enablers', 1, '{"slides":[7,20],"inputs":["kpis","events"],"required":["kpis"],"kpi_codes":["BENEFICIARIES_UPDATED"],"event_slots":["CAL_2026_DEC_1","CAL_2026_DEC_2"]}'),
  ('proj-p1-6', 'P1_6', 'مشروع 1.6: الجهات الممكنة', 'operational_track', 2026, 'team-enablers', 1, '{"slides":[29,30],"inputs":["kpis","achievements","upcoming_tasks"],"required":["kpis","achievements"],"kpi_codes":["ENABLERS_ACTIVATED","ENABLERS_NEW_SERVICES","ENABLERS_TRACKS","ENABLERS_BENEFITING_SMES","ENABLERS_EVENTS"],"max_achievements":2,"max_tasks":2}'),
  ('proj-int-rel', 'INT_RELATIONSHIP', 'تعزيز العلاقة مع منشآت طموح', 'internal_priority', 2026, 'team-rm', 1, '{"slides":[32],"inputs":["project_status","challenges"],"required":["challenges"]}'),
  ('proj-int-ai', 'INT_AI_DIAGNOSTIC', 'تحسين اداة التشخيص الذاتي وتوظيف الذكاء الاصطناعي', 'internal_priority', 2026, 'team-rm', 1, '{"slides":[34],"inputs":["project_status","deliverables","challenges"],"required":["project_status","challenges"]}'),
  ('proj-news', 'TOMOH_NEWS', 'أخبار طموح والمهام الصادرة من الاجتماع', 'news_and_events', 2026, 'team-growth', 1, '{"slides":[38,40],"inputs":["news","images","action_items"],"required":["news","action_items"],"max_news":2,"max_action_items":8}')
ON CONFLICT (id) DO NOTHING;

INSERT INTO kpi_definitions (id, kpi_code, project_id, label_ar, aggregation_type, auto_accumulate_from, annual_target, unit_format) VALUES
  ('kpi-smi-w', 'SMI_WEEKLY', 'proj-platform', 'عدد اجتماعات (SMI) — الأسبوعي', 'weekly_delta', NULL, NULL, 'int'),
  ('kpi-smi-26', 'SMI_CUMULATIVE_2026', 'proj-platform', 'عدد اجتماعات (SMI) — التراكمي 2026', 'ytd_cumulative', 'SMI_WEEKLY', NULL, 'int'),
  ('kpi-smi1-tot', 'SMI1_CUMULATIVE_TOTAL', 'proj-platform', 'العدد التراكمي / SMI 1', 'all_time_cumulative', NULL, NULL, 'int'),
  ('kpi-smi1-pct', 'SMI1_COMPLETION_PCT', 'proj-platform', 'نسبة اكتمال الـ SMI 1', 'percentage', NULL, 100, 'percent_prefix'),
  ('kpi-reg-w', 'REG_COMPANIES_WEEKLY', 'proj-platform', 'الشركات المسجلة — الأسبوعي', 'weekly_delta', NULL, NULL, 'int'),
  ('kpi-reg-26', 'REG_COMPANIES_2026', 'proj-platform', 'الشركات المسجلة — التراكمي 2026', 'ytd_cumulative', 'REG_COMPANIES_WEEKLY', 500, 'int'),
  ('kpi-reg-all', 'REG_COMPANIES_ALL_TIME', 'proj-platform', 'الشركات المسجلة — التراكمي الكلي', 'all_time_cumulative', 'REG_COMPANIES_WEEKLY', NULL, 'comma_int'),
  ('kpi-reg-tgt', 'REG_COMPANIES_TARGET_2026', 'proj-platform', 'المستهدف السنوي للشركات المسجلة', 'annual_target', NULL, 500, 'prefix:المستهدف: '),
  ('kpi-diag-w', 'DIAGNOSTIC_REPORTS_WEEKLY', 'proj-platform', 'تقارير التشخيص — الأسبوعي', 'weekly_delta', NULL, NULL, 'int'),
  ('kpi-diag-26', 'DIAGNOSTIC_REPORTS_2026', 'proj-platform', 'تقارير التشخيص — التراكمي 2026', 'ytd_cumulative', 'DIAGNOSTIC_REPORTS_WEEKLY', 300, 'int'),
  ('kpi-diag-all', 'DIAGNOSTIC_REPORTS_ALL_TIME', 'proj-platform', 'تقارير التشخيص — التراكمي الكلي', 'all_time_cumulative', NULL, NULL, 'int'),
  ('kpi-ben-upd', 'BENEFICIARIES_UPDATED', 'proj-p1-4', 'عدد المستفيدين من الأنشطة والفعاليات', 'ytd_cumulative', NULL, 800, 'comma_int'),
  ('kpi-rm-f-w', 'SMI1_RM_FAHAD_WEEKLY', 'proj-platform', 'SMI الأسبوعي — فهد القحطاني', 'weekly_delta', NULL, NULL, 'int'),
  ('kpi-rm-m-w', 'SMI1_RM_MOHAMMED_WEEKLY', 'proj-platform', 'SMI الأسبوعي — محمد أبو عباة', 'weekly_delta', NULL, NULL, 'int'),
  ('kpi-rm-fi-w', 'SMI1_RM_FAISAL_WEEKLY', 'proj-platform', 'SMI الأسبوعي — فيصل الحيزان', 'weekly_delta', NULL, NULL, 'int'),
  ('kpi-rm-k-w', 'SMI1_RM_KHALID_WEEKLY', 'proj-platform', 'SMI الأسبوعي — خالد القرني', 'weekly_delta', NULL, NULL, 'int'),
  ('kpi-rm-tot-w', 'SMI1_RM_TOTAL_WEEKLY', 'proj-platform', 'SMI الأسبوعي — الإجمالي', 'weekly_delta', NULL, NULL, 'int'),
  ('kpi-en-act', 'ENABLERS_ACTIVATED', 'proj-p1-6', 'عدد الجهات الممكنة التي تم تفعيلها', 'ratio', NULL, 15, 'ratio'),
  ('kpi-en-srv', 'ENABLERS_NEW_SERVICES', 'proj-p1-6', 'عدد الخدمات الجديدة المقدمة', 'ratio', NULL, 15, 'ratio'),
  ('kpi-en-trk', 'ENABLERS_TRACKS', 'proj-p1-6', 'عدد المسارات المفعلة', 'ratio', NULL, 2, 'ratio'),
  ('kpi-en-sme', 'ENABLERS_BENEFITING_SMES', 'proj-p1-6', 'عدد المنشآت المستفيدة', 'ratio', NULL, 90, 'ratio'),
  ('kpi-en-evt', 'ENABLERS_EVENTS', 'proj-p1-6', 'عدد الفعاليات واللقاءات المنفذة', 'ratio', NULL, 25, 'ratio')
ON CONFLICT (id) DO NOTHING;

-- TOMOH Weekly Report Automation — Migration 004: Supabase PostgreSQL 16 RLS & Private Storage Buckets
-- Enforces strict server-side-only access (blocks all direct anon/public PostgREST access).

-- 1. Enable Row-Level Security (RLS) on every application table
ALTER TABLE schema_migrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE teams ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE reporting_weeks ENABLE ROW LEVEL SECURITY;
ALTER TABLE weekly_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE kpi_values ENABLE ROW LEVEL SECURITY;
ALTER TABLE achievements ENABLE ROW LEVEL SECURITY;
ALTER TABLE upcoming_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_statuses ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE news ENABLE ROW LEVEL SECURITY;
ALTER TABLE attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE slide_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY;

-- Note: With RLS enabled and NO permissive policies for `anon` or `authenticated`,
-- direct browser/PostgREST access is completely denied by default.
-- Only the FastAPI backend connecting with the server-side PostgreSQL role / service_role can read/write.

-- 2. Provision Private Supabase Storage Buckets (public = false)
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES
  ('tomoh-templates',   'tomoh-templates',   false, 52428800, ARRAY['application/vnd.openxmlformats-officedocument.presentationml.presentation']),
  ('tomoh-reports',     'tomoh-reports',     false, 52428800, ARRAY['application/vnd.openxmlformats-officedocument.presentationml.presentation']),
  ('tomoh-uploads',     'tomoh-uploads',     false, 5242880,  ARRAY['image/png', 'image/jpeg']),
  ('tomoh-attachments', 'tomoh-attachments', false, 10485760, ARRAY['image/png', 'image/jpeg', 'application/pdf'])
ON CONFLICT (id) DO UPDATE SET public = false;

INSERT INTO schema_migrations(version) VALUES ('001_initial_schema'),('002_seed_tomoh_master'),('003_phase2_webapp_features'),('004_supabase_rls_and_storage') ON CONFLICT DO NOTHING;

