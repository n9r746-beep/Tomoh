ALTER TABLE weekly_submissions DROP CONSTRAINT IF EXISTS weekly_submissions_reporting_week_id_project_id_key;
ALTER TABLE weekly_submissions ADD CONSTRAINT weekly_submissions_contributor_key UNIQUE (reporting_week_id, project_id, submitted_by);
ALTER TABLE kpi_values DROP CONSTRAINT IF EXISTS kpi_values_reporting_week_id_kpi_definition_id_key;
ALTER TABLE kpi_values ADD CONSTRAINT kpi_values_contributor_key UNIQUE (reporting_week_id, kpi_definition_id, responsible_user_id);
ALTER TABLE achievements DROP CONSTRAINT IF EXISTS achievements_reporting_week_id_project_id_slot_index_key;
ALTER TABLE achievements ADD CONSTRAINT achievements_contributor_key UNIQUE (reporting_week_id, project_id, slot_index, responsible_user_id);
ALTER TABLE project_statuses DROP CONSTRAINT IF EXISTS project_statuses_reporting_week_id_project_id_key;
ALTER TABLE project_statuses ADD CONSTRAINT project_statuses_contributor_key UNIQUE (reporting_week_id, project_id, responsible_user_id);
ALTER TABLE events DROP CONSTRAINT IF EXISTS events_reporting_week_id_slot_key_key;
ALTER TABLE events ADD CONSTRAINT events_contributor_key UNIQUE (reporting_week_id, slot_key, responsible_user_id);
ALTER TABLE news DROP CONSTRAINT IF EXISTS news_reporting_week_id_slot_index_key;
ALTER TABLE news ADD CONSTRAINT news_contributor_key UNIQUE (reporting_week_id, slot_index, responsible_user_id);
CREATE TABLE IF NOT EXISTS project_approvals (
 id TEXT PRIMARY KEY,
 reporting_week_id TEXT NOT NULL REFERENCES reporting_weeks(id) ON DELETE CASCADE,
 project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 approved_by TEXT NOT NULL REFERENCES users(id),
 approved_at TEXT NOT NULL,
 kpi_source_user_id TEXT REFERENCES users(id),
 UNIQUE(reporting_week_id,project_id)
);

ALTER TABLE public.project_approvals ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.project_approvals FROM anon,authenticated;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.project_approvals TO tomoh_backend;
CREATE POLICY backend_access ON public.project_approvals FOR ALL TO tomoh_backend USING (true) WITH CHECK (true);
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
