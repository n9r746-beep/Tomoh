-- TOMOH Weekly Report Automation — Production Clean Master Seed (PostgreSQL)
-- Seeds ONLY permanent department structure, projects, and KPI definitions.
-- ZERO synthetic test users, ZERO synthetic weekly submissions.

INSERT INTO teams (id, code, name_ar, name_en) VALUES
  ('team-growth', 'GROWTH_REL', 'إدارة علاقات نمو المنشآت – طموح', 'TOMOH Growth Relations'),
  ('team-rm', 'REL_MGRS', 'فريق مدراء العلاقة', 'Relationship Managers'),
  ('team-enablers', 'ENABLERS', 'فريق الجهات الممكنة والفعاليات', 'Enablers & Events')
ON CONFLICT (id) DO NOTHING;

INSERT INTO projects (id, project_code, title_ar, category, fiscal_year, team_id, is_enabled, section_config_json) VALUES
  ('proj-platform', 'PLATFORM_KPI', 'احصائيات منصة طموح و SMI', 'department_kpi', 2026, 'team-growth', TRUE, '{"slides":[4,5,6,7,9,10],"inputs":["kpis"],"required":["kpis"],"kpi_codes":["SMI_WEEKLY","SMI_CUMULATIVE_2026","SMI1_CUMULATIVE_TOTAL","SMI1_COMPLETION_PCT","REG_COMPANIES_WEEKLY","REG_COMPANIES_2026","REG_COMPANIES_ALL_TIME","REG_COMPANIES_TARGET_2026","DIAGNOSTIC_REPORTS_WEEKLY","DIAGNOSTIC_REPORTS_2026","DIAGNOSTIC_REPORTS_ALL_TIME","SMI1_RM_FAHAD_WEEKLY","SMI1_RM_MOHAMMED_WEEKLY","SMI1_RM_FAISAL_WEEKLY","SMI1_RM_KHALID_WEEKLY","SMI1_RM_TOTAL_WEEKLY"]}'),
  ('proj-p1-3', 'P1_3', 'مشروع 1.3: الحملة الإعلامية', 'operational_track', 2026, 'team-growth', TRUE, '{"slides":[16],"inputs":["achievements","upcoming_tasks"],"required":["achievements","upcoming_tasks"],"max_achievements":3,"max_tasks":1}'),
  ('proj-p1-4', 'P1_4', 'مشروع 1.4: الأنشطة والفعاليات', 'operational_track', 2026, 'team-enablers', TRUE, '{"slides":[7,20],"inputs":["kpis","events"],"required":["kpis"],"kpi_codes":["BENEFICIARIES_UPDATED"],"event_slots":["CAL_2026_DEC_1","CAL_2026_DEC_2"]}'),
  ('proj-p1-6', 'P1_6', 'مشروع 1.6: الجهات الممكنة', 'operational_track', 2026, 'team-enablers', TRUE, '{"slides":[29,30],"inputs":["kpis","achievements","upcoming_tasks"],"required":["kpis","achievements"],"kpi_codes":["ENABLERS_ACTIVATED","ENABLERS_NEW_SERVICES","ENABLERS_TRACKS","ENABLERS_BENEFITING_SMES","ENABLERS_EVENTS"],"max_achievements":2,"max_tasks":2}'),
  ('proj-int-rel', 'INT_RELATIONSHIP', 'تعزيز العلاقة مع منشآت طموح', 'internal_priority', 2026, 'team-rm', TRUE, '{"slides":[32],"inputs":["project_status","challenges"],"required":["challenges"]}'),
  ('proj-int-ai', 'INT_AI_DIAGNOSTIC', 'تحسين اداة التشخيص الذاتي وتوظيف الذكاء الاصطناعي', 'internal_priority', 2026, 'team-rm', TRUE, '{"slides":[34],"inputs":["project_status","deliverables","challenges"],"required":["project_status","challenges"]}'),
  ('proj-news', 'TOMOH_NEWS', 'أخبار طموح والمهام الصادرة من الاجتماع', 'news_and_events', 2026, 'team-growth', TRUE, '{"slides":[38,40],"inputs":["news","images","action_items"],"required":["news","action_items"],"max_news":2,"max_action_items":8}')
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
