PRAGMA foreign_keys=OFF;
CREATE TABLE weekly_submissions_multi_user_new (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    submitted_by        TEXT NOT NULL REFERENCES users(id),
    reviewed_by         TEXT REFERENCES users(id),
    status              TEXT NOT NULL CHECK (status IN ('draft', 'submitted', 'changes_requested', 'approved')) DEFAULT 'draft',
    version             INTEGER NOT NULL DEFAULT 1,
    reviewer_notes_ar   TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (reporting_week_id, project_id, submitted_by)
);
INSERT INTO weekly_submissions_multi_user_new SELECT * FROM weekly_submissions;
DROP TABLE weekly_submissions;
ALTER TABLE weekly_submissions_multi_user_new RENAME TO weekly_submissions;
CREATE TABLE kpi_values_multi_user_new (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT REFERENCES projects(id),
    kpi_definition_id   TEXT NOT NULL REFERENCES kpi_definitions(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    numeric_value       REAL,
    denominator_value   REAL,
    is_unchanged        INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (reporting_week_id, kpi_definition_id, responsible_user_id)
);
INSERT INTO kpi_values_multi_user_new SELECT * FROM kpi_values;
DROP TABLE kpi_values;
ALTER TABLE kpi_values_multi_user_new RENAME TO kpi_values;
CREATE TABLE achievements_multi_user_new (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT NOT NULL REFERENCES projects(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    slot_index          INTEGER NOT NULL,
    content_ar          TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (reporting_week_id, project_id, slot_index, responsible_user_id)
);
INSERT INTO achievements_multi_user_new SELECT * FROM achievements;
DROP TABLE achievements;
ALTER TABLE achievements_multi_user_new RENAME TO achievements;
CREATE TABLE project_statuses_multi_user_new (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT NOT NULL REFERENCES projects(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    status_code         TEXT NOT NULL CHECK (status_code IN ('on_track', 'delayed', 'critically_delayed', 'on_hold', 'completed', 'not_started')),
    progress_note_ar    TEXT,
    deliverables_override_ar TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (reporting_week_id, project_id, responsible_user_id)
);
INSERT INTO project_statuses_multi_user_new SELECT * FROM project_statuses;
DROP TABLE project_statuses;
ALTER TABLE project_statuses_multi_user_new RENAME TO project_statuses;
CREATE TABLE events_multi_user_new (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT REFERENCES projects(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    slot_key            TEXT NOT NULL,
    title_ar            TEXT NOT NULL,
    event_date_label    TEXT,
    lead_names_ar       TEXT,
    event_status        TEXT NOT NULL DEFAULT 'على المسار',
    beneficiaries_count INTEGER,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (reporting_week_id, slot_key, responsible_user_id)
);
INSERT INTO events_multi_user_new SELECT * FROM events;
DROP TABLE events;
ALTER TABLE events_multi_user_new RENAME TO events;
CREATE TABLE news_multi_user_new (
    id                  TEXT PRIMARY KEY,
    reporting_week_id   TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
    project_id          TEXT REFERENCES projects(id),
    responsible_user_id TEXT NOT NULL REFERENCES users(id),
    submission_status   TEXT NOT NULL DEFAULT 'submitted',
    slot_index          INTEGER NOT NULL,
    headline_ar         TEXT,
    body_ar             TEXT NOT NULL,
    attachment_id       TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (reporting_week_id, slot_index, responsible_user_id)
);
INSERT INTO news_multi_user_new SELECT * FROM news;
DROP TABLE news;
ALTER TABLE news_multi_user_new RENAME TO news;
CREATE TABLE IF NOT EXISTS project_approvals (
 id TEXT PRIMARY KEY,
 reporting_week_id TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 approved_by TEXT NOT NULL REFERENCES users(id),
 approved_at TEXT NOT NULL,
 kpi_source_user_id TEXT REFERENCES users(id),
 UNIQUE(reporting_week_id,project_id)
);

PRAGMA foreign_keys=ON;
INSERT INTO projects(id,project_code,title_ar,category,fiscal_year,team_id,is_enabled,section_config_json) VALUES ('proj-p1-1','P1_1','مشروع 1.1: الاستقطاب والتسجيل','operational_track',2026,'team-growth',1,'{"slides": [11, 12, 13], "inputs": ["kpis", "achievements", "upcoming_tasks"], "required": ["achievements"], "max_achievements": 3, "max_tasks": 2, "kpi_codes": ["REG_COMPANIES_WEEKLY", "REG_COMPANIES_2026", "REG_COMPANIES_ALL_TIME", "REG_COMPANIES_TARGET_2026", "ATTRACTION_DIRECT_WEEKLY", "ATTRACTION_EMAIL_WEEKLY", "ATTRACTION_SMS1_WEEKLY", "ATTRACTION_SMS2_WEEKLY", "ATTRACTION_CUSTOMER_CONTACTS_WEEKLY"]}') ON CONFLICT(id) DO NOTHING;
INSERT INTO kpi_definitions(id,kpi_code,project_id,label_ar,aggregation_type,unit_format) VALUES ('kpi-attraction_direct_weekly','ATTRACTION_DIRECT_WEEKLY','proj-p1-1','التواصل المباشر — فريق الاستقطاب','weekly_delta','int') ON CONFLICT(id) DO NOTHING;
INSERT INTO kpi_definitions(id,kpi_code,project_id,label_ar,aggregation_type,unit_format) VALUES ('kpi-attraction_email_weekly','ATTRACTION_EMAIL_WEEKLY','proj-p1-1','رسائل البريد الإلكتروني','weekly_delta','int') ON CONFLICT(id) DO NOTHING;
INSERT INTO kpi_definitions(id,kpi_code,project_id,label_ar,aggregation_type,unit_format) VALUES ('kpi-attraction_sms1_weekly','ATTRACTION_SMS1_WEEKLY','proj-p1-1','الرسائل النصية (١)','weekly_delta','int') ON CONFLICT(id) DO NOTHING;
INSERT INTO kpi_definitions(id,kpi_code,project_id,label_ar,aggregation_type,unit_format) VALUES ('kpi-attraction_sms2_weekly','ATTRACTION_SMS2_WEEKLY','proj-p1-1','الرسائل النصية (٢)','weekly_delta','int') ON CONFLICT(id) DO NOTHING;
INSERT INTO kpi_definitions(id,kpi_code,project_id,label_ar,aggregation_type,unit_format) VALUES ('kpi-attraction_customer_contacts_weekly','ATTRACTION_CUSTOMER_CONTACTS_WEEKLY','proj-p1-1','التواصل المباشر — تجربة العميل','weekly_delta','int') ON CONFLICT(id) DO NOTHING;
UPDATE kpi_definitions SET project_id='proj-p1-1' WHERE kpi_code LIKE 'REG_COMPANIES_%';
UPDATE kpi_values SET project_id='proj-p1-1' WHERE kpi_definition_id IN (SELECT id FROM kpi_definitions WHERE kpi_code LIKE 'REG_COMPANIES_%');
INSERT INTO weekly_submissions(id,reporting_week_id,project_id,submitted_by,status,version,created_at,updated_at)
SELECT 'sub-attraction-' || reporting_week_id || '-' || responsible_user_id,reporting_week_id,'proj-p1-1',responsible_user_id,'draft',1,MIN(created_at),MAX(updated_at)
FROM kpi_values WHERE project_id='proj-p1-1'
GROUP BY reporting_week_id,responsible_user_id
ON CONFLICT(reporting_week_id,project_id,submitted_by) DO NOTHING;
