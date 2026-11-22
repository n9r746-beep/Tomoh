-- TOMOH Weekly Report Automation — Migration 002: Master Seed Data
-- Grounded strictly in audited projects and KPI definitions from التحديث الاسبوعي رقم 44.pptx.

INSERT OR IGNORE INTO teams (id, code, name_ar, name_en) VALUES
  ('team-growth', 'GROWTH_REL', 'إدارة علاقات نمو المنشآت – طموح', 'TOMOH Growth Relations'),
  ('team-rm', 'REL_MGRS', 'فريق مدراء العلاقة', 'Relationship Managers'),
  ('team-enablers', 'ENABLERS', 'فريق الجهات الممكنة والفعاليات', 'Enablers & Events');

-- Synthetic test accounts (no hardcoded credentials; identity resolved via configurable header/SSO in dev)
INSERT OR IGNORE INTO users (id, email, full_name_ar, full_name_en, team_id, role) VALUES
  ('u-coord', 'coordinator@tomoh.internal', 'منسق التقرير الأسبوعي', 'Report Coordinator', 'team-growth', 'coordinator'),
  ('u-admin', 'admin@tomoh.internal', 'مدير النظام', 'System Admin', 'team-growth', 'admin'),
  ('u-fahad', 'fahad.q@tomoh.internal', 'فهد القحطاني', 'Fahad Al-Qahtani', 'team-rm', 'employee'),
  ('u-mohammed', 'mohammed.a@tomoh.internal', 'محمد أبو عباة', 'Mohammed Aboaba', 'team-rm', 'employee'),
  ('u-abdullah', 'abdullah.h@tomoh.internal', 'عبدالله الحسين', 'Abdullah Al-Hussain', 'team-enablers', 'employee'),
  ('u-maram', 'maram.g@tomoh.internal', 'مرام الغنيم', 'Maram Al-Ghunaim', 'team-enablers', 'employee');

INSERT OR IGNORE INTO projects (id, project_code, title_ar, category, fiscal_year, owner_user_id, team_id) VALUES
  ('proj-platform', 'PLATFORM_KPI', 'احصائيات منصة طموح و SMI', 'department_kpi', 2026, 'u-coord', 'team-growth'),
  ('proj-p1-3', 'P1_3', 'مشروع 1.3: الحملة الإعلامية', 'operational_track', 2026, 'u-maram', 'team-growth'),
  ('proj-p1-4', 'P1_4', 'مشروع 1.4: الأنشطة والفعاليات', 'operational_track', 2026, 'u-maram', 'team-enablers'),
  ('proj-p1-6', 'P1_6', 'مشروع 1.6: الجهات الممكنة', 'operational_track', 2026, 'u-abdullah', 'team-enablers'),
  ('proj-int-rel', 'INT_RELATIONSHIP', 'تعزيز العلاقة مع منشآت طموح', 'internal_priority', 2026, 'u-fahad', 'team-rm'),
  ('proj-int-ai', 'INT_AI_DIAGNOSTIC', 'تحسين اداة التشخيص الذاتي وتوظيف الذكاء الاصطناعي', 'internal_priority', 2026, 'u-mohammed', 'team-rm'),
  ('proj-news', 'TOMOH_NEWS', 'أخبار طموح والمهام الصادرة من الاجتماع', 'news_and_events', 2026, 'u-coord', 'team-growth');

INSERT OR IGNORE INTO project_members (id, project_id, user_id, member_role) VALUES
  ('pm-1', 'proj-platform', 'u-coord', 'manager'),
  ('pm-2', 'proj-p1-3', 'u-maram', 'manager'),
  ('pm-3', 'proj-p1-4', 'u-maram', 'manager'),
  ('pm-4', 'proj-p1-6', 'u-abdullah', 'manager'),
  ('pm-5', 'proj-int-rel', 'u-fahad', 'manager'),
  ('pm-6', 'proj-int-ai', 'u-mohammed', 'manager'),
  ('pm-7', 'proj-news', 'u-coord', 'manager');

-- KPI Definitions (auto_accumulate_from explicitly controls whether cumulative KPIs auto-sum)
INSERT OR IGNORE INTO kpi_definitions (id, kpi_code, project_id, label_ar, aggregation_type, auto_accumulate_from, annual_target, unit_format, owner_user_id) VALUES
  ('kpi-smi-w', 'SMI_WEEKLY', 'proj-platform', 'عدد اجتماعات (SMI) — الأسبوعي', 'weekly_delta', NULL, NULL, 'int', 'u-coord'),
  ('kpi-smi-26', 'SMI_CUMULATIVE_2026', 'proj-platform', 'عدد اجتماعات (SMI) — التراكمي 2026', 'ytd_cumulative', 'SMI_WEEKLY', NULL, 'int', 'u-coord'),
  ('kpi-smi1-tot', 'SMI1_CUMULATIVE_TOTAL', 'proj-platform', 'العدد التراكمي / SMI 1', 'all_time_cumulative', NULL, NULL, 'int', 'u-coord'),
  ('kpi-smi1-pct', 'SMI1_COMPLETION_PCT', 'proj-platform', 'نسبة اكتمال الـ SMI 1', 'percentage', NULL, 100, 'percent_prefix', 'u-coord'),
  ('kpi-reg-w', 'REG_COMPANIES_WEEKLY', 'proj-platform', 'الشركات المسجلة — الأسبوعي', 'weekly_delta', NULL, NULL, 'int', 'u-coord'),
  ('kpi-reg-26', 'REG_COMPANIES_2026', 'proj-platform', 'الشركات المسجلة — التراكمي 2026', 'ytd_cumulative', 'REG_COMPANIES_WEEKLY', 500, 'int', 'u-coord'),
  ('kpi-reg-all', 'REG_COMPANIES_ALL_TIME', 'proj-platform', 'الشركات المسجلة — التراكمي الكلي', 'all_time_cumulative', 'REG_COMPANIES_WEEKLY', NULL, 'comma_int', 'u-coord'),
  ('kpi-reg-tgt', 'REG_COMPANIES_TARGET_2026', 'proj-platform', 'المستهدف السنوي للشركات المسجلة', 'annual_target', NULL, 500, 'prefix:المستهدف: ', 'u-coord'),
  ('kpi-diag-w', 'DIAGNOSTIC_REPORTS_WEEKLY', 'proj-platform', 'تقارير التشخيص — الأسبوعي', 'weekly_delta', NULL, NULL, 'int', 'u-coord'),
  ('kpi-diag-26', 'DIAGNOSTIC_REPORTS_2026', 'proj-platform', 'تقارير التشخيص — التراكمي 2026', 'ytd_cumulative', 'DIAGNOSTIC_REPORTS_WEEKLY', 300, 'int', 'u-coord'),
  ('kpi-diag-all', 'DIAGNOSTIC_REPORTS_ALL_TIME', 'proj-platform', 'تقارير التشخيص — التراكمي الكلي', 'all_time_cumulative', NULL, NULL, 'int', 'u-coord'),
  ('kpi-ben-upd', 'BENEFICIARIES_UPDATED', 'proj-p1-4', 'عدد المستفيدين من الأنشطة والفعاليات', 'ytd_cumulative', NULL, 800, 'comma_int', 'u-maram'),
  ('kpi-rm-f-w', 'SMI1_RM_FAHAD_WEEKLY', 'proj-platform', 'SMI الأسبوعي — فهد القحطاني', 'weekly_delta', NULL, NULL, 'int', 'u-fahad'),
  ('kpi-rm-m-w', 'SMI1_RM_MOHAMMED_WEEKLY', 'proj-platform', 'SMI الأسبوعي — محمد أبو عباة', 'weekly_delta', NULL, NULL, 'int', 'u-mohammed'),
  ('kpi-rm-fi-w', 'SMI1_RM_FAISAL_WEEKLY', 'proj-platform', 'SMI الأسبوعي — فيصل الحيزان', 'weekly_delta', NULL, NULL, 'int', 'u-coord'),
  ('kpi-rm-k-w', 'SMI1_RM_KHALID_WEEKLY', 'proj-platform', 'SMI الأسبوعي — خالد القرني', 'weekly_delta', NULL, NULL, 'int', 'u-coord'),
  ('kpi-rm-tot-w', 'SMI1_RM_TOTAL_WEEKLY', 'proj-platform', 'SMI الأسبوعي — الإجمالي', 'weekly_delta', NULL, NULL, 'int', 'u-coord'),
  ('kpi-en-act', 'ENABLERS_ACTIVATED', 'proj-p1-6', 'عدد الجهات الممكنة التي تم تفعيلها', 'ratio', NULL, 15, 'ratio', 'u-abdullah'),
  ('kpi-en-srv', 'ENABLERS_NEW_SERVICES', 'proj-p1-6', 'عدد الخدمات الجديدة المقدمة', 'ratio', NULL, 15, 'ratio', 'u-abdullah'),
  ('kpi-en-trk', 'ENABLERS_TRACKS', 'proj-p1-6', 'عدد المسارات المفعلة', 'ratio', NULL, 2, 'ratio', 'u-abdullah'),
  ('kpi-en-sme', 'ENABLERS_BENEFITING_SMES', 'proj-p1-6', 'عدد المنشآت المستفيدة', 'ratio', NULL, 90, 'ratio', 'u-abdullah'),
  ('kpi-en-evt', 'ENABLERS_EVENTS', 'proj-p1-6', 'عدد الفعاليات واللقاءات المنفذة', 'ratio', NULL, 25, 'ratio', 'u-abdullah');
