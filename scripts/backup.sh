#!/usr/bin/env bash
# TOMOH Weekly Report Automation — Automated Backup Script (SQLite & PostgreSQL + Media)
set -euo pipefail

BACKUP_ROOT="${1:-./backups}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_ROOT}/tomoh_backup_${TS}"
mkdir -p "${DEST}"
chmod 700 "${DEST}"

DB_URL="${TOMOH_DATABASE_URL:-sqlite:///./tomoh_local.db}"
UPLOADS_DIR="${TOMOH_UPLOADS_DIR:-./uploads}"
OUTPUT_DIR="${TOMOH_OUTPUT_DIR:-./generated_reports}"

if [[ "${DB_URL}" == sqlite:///* ]]; then
  DB_FILE="${DB_URL#sqlite:///}"
  python3 -c "import sqlite3; src=sqlite3.connect('${DB_FILE}'); dst=sqlite3.connect('${DEST}/database.sqlite'); src.backup(dst); dst.close(); src.close()"
elif [[ "${DB_URL}" == postgres* ]]; then
  pg_dump "${DB_URL}" --format=custom --file="${DEST}/database.pgdump"
else
  echo "Unsupported TOMOH_DATABASE_URL: ${DB_URL}" >&2
  exit 1
fi

[[ -d "${UPLOADS_DIR}" ]] && tar -czf "${DEST}/uploads.tar.gz" -C "$(dirname "${UPLOADS_DIR}")" "$(basename "${UPLOADS_DIR}")"
[[ -d "${OUTPUT_DIR}" ]] && tar -czf "${DEST}/generated_reports.tar.gz" -C "$(dirname "${OUTPUT_DIR}")" "$(basename "${OUTPUT_DIR}")"

(cd "${DEST}" && sha256sum * > SHA256SUMS.txt)
echo "Backup created and checksummed at: ${DEST}"
