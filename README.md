# TOMOH v5.0.0

Arabic RTL weekly reporting application. FastAPI backend, Supabase PostgreSQL and private Storage, Vercel Python functions.

## Production
Email/password authentication uses PBKDF2-SHA256 (600,000 rounds), Secure HttpOnly cookies, server-side sessions, throttling and RBAC. With TOMOH_AUTH_MODE=session_password, development identity headers and the user selector are disabled. Admins can add users and assign projects from Settings. Corporate OIDC is not configured.

Images and generated reports persist in private storage; authenticated downloads issue five-minute signed links. The original PowerPoint master remains in private storage outside this repository. Generation preserves untouched OOXML parts. AI writing is disabled by default.

## Deployment
Python 3.12; pinned requirements.txt; api/index.py serves FastAPI. Apply deploy/production_schema.sql once and set TOMOH_SKIP_MIGRATIONS=true. Production uses integer flags compatible with repository SQL. Browser roles have no table access. Configure dedicated backend credentials separately; never commit them.

Server environment: TOMOH_DATABASE_URL, TOMOH_AUTH_MODE=session_password, TOMOH_SKIP_MIGRATIONS=true, TOMOH_STORAGE_RELAY_URL, TOMOH_STORAGE_TOKEN, TOMOH_TEMPLATE_PPTX=/tmp/tomoh_master.pptx, TOMOH_OUTPUT_DIR=/tmp/tomoh_generated, TOMOH_UPLOADS_DIR=/tmp/tomoh_uploads.

The storage relay authenticates the backend with a high-entropy token; only its SHA256 digest appears in source. The privileged Supabase Storage key stays in the Supabase runtime.

## Validation
Run TOMOH_TEMPLATE_PPTX=/path/to/private/master_template.pptx python -m unittest discover -s tests -v.
18 tests cover lifecycle, RBAC, revision conflicts, template preservation, report generation, snapshots, storage contracts, production header rejection and CSRF. Tests use disposable SQLite databases and synthetic sample values.


## Multiple contributors and attraction
Each contributor has a separate submission/version and privately edits their own weekly fields. Coordinators assign multiple contributors with checkboxes, inspect each update, approve the combined section, and reopen it for revisions. Approval freezes section edits. Conflicting KPI values require an explicit choice per metric; employee figures remain preserved. Whole saves and report snapshots are transactional.

Project P1_1 (الاستقطاب والتسجيل) maps the master slides 11–13, registration indicators and outreach counts. Existing production updates were retained during the schema migration. The updated regression suite contains 28 passing tests, including three contributors, simultaneous edits, stale approvals, reopening, author-preserving carry-forward and lossless PowerPoint export.

Production authentication defaults to session_password. Vercel refuses to start in header_dev mode, even if it is explicitly requested through environment configuration.
