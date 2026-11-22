-- TOMOH Weekly Report Automation — Migration 003: Phase 2 Web App Features (SQLite)

CREATE TABLE IF NOT EXISTS user_sessions (
    token       TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,
    revoked     INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE reporting_weeks ADD COLUMN submission_deadline TEXT;
ALTER TABLE projects ADD COLUMN is_enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE projects ADD COLUMN section_config_json TEXT;
ALTER TABLE report_generations ADD COLUMN input_snapshot_json TEXT;

-- Populate per-project section configurations strictly from the Phase 0 slide-field manifest
UPDATE projects SET section_config_json = '{"slides":[4,5,6,7,9,10],"inputs":["kpis"],"required":["kpis"],"kpi_codes":["SMI_WEEKLY","SMI_CUMULATIVE_2026","SMI1_CUMULATIVE_TOTAL","SMI1_COMPLETION_PCT","REG_COMPANIES_WEEKLY","REG_COMPANIES_2026","REG_COMPANIES_ALL_TIME","REG_COMPANIES_TARGET_2026","DIAGNOSTIC_REPORTS_WEEKLY","DIAGNOSTIC_REPORTS_2026","DIAGNOSTIC_REPORTS_ALL_TIME","SMI1_RM_FAHAD_WEEKLY","SMI1_RM_MOHAMMED_WEEKLY","SMI1_RM_FAISAL_WEEKLY","SMI1_RM_KHALID_WEEKLY","SMI1_RM_TOTAL_WEEKLY"]}'
WHERE project_code = 'PLATFORM_KPI';

UPDATE projects SET section_config_json = '{"slides":[16],"inputs":["achievements","upcoming_tasks"],"required":["achievements","upcoming_tasks"],"max_achievements":3,"max_tasks":1}'
WHERE project_code = 'P1_3';

UPDATE projects SET section_config_json = '{"slides":[7,20],"inputs":["kpis","events"],"required":["kpis"],"kpi_codes":["BENEFICIARIES_UPDATED"],"event_slots":["CAL_2026_DEC_1","CAL_2026_DEC_2"]}'
WHERE project_code = 'P1_4';

UPDATE projects SET section_config_json = '{"slides":[29,30],"inputs":["kpis","achievements","upcoming_tasks"],"required":["kpis","achievements"],"kpi_codes":["ENABLERS_ACTIVATED","ENABLERS_NEW_SERVICES","ENABLERS_TRACKS","ENABLERS_BENEFITING_SMES","ENABLERS_EVENTS"],"max_achievements":2,"max_tasks":2}'
WHERE project_code = 'P1_6';

UPDATE projects SET section_config_json = '{"slides":[32],"inputs":["project_status","challenges"],"required":["challenges"]}'
WHERE project_code = 'INT_RELATIONSHIP';

UPDATE projects SET section_config_json = '{"slides":[34],"inputs":["project_status","deliverables","challenges"],"required":["project_status","challenges"]}'
WHERE project_code = 'INT_AI_DIAGNOSTIC';

UPDATE projects SET section_config_json = '{"slides":[38,40],"inputs":["news","images","action_items"],"required":["news","action_items"],"max_news":2,"max_action_items":8}'
WHERE project_code = 'TOMOH_NEWS';
