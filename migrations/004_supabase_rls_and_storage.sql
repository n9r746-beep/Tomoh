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
