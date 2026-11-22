#!/usr/bin/env bash
# TOMOH Weekly Report Automation — Verified Restore Script
set -euo pipefail

BACKUP_DIR="${1:?Usage: restore.sh <backup_dir>}"
DB_URL="${TOMOH_DATABASE_URL:-sqlite:///./tomoh_local.db}"

echo "Verifying SHA-256 checksums..."
(cd "${BACKUP_DIR}" && sha256sum -c SHA256SUMS.txt)

if [[ -f "${BACKUP_DIR}/database.sqlite" && "${DB_URL}" == sqlite:///* ]]; then
  DB_FILE="${DB_URL#sqlite:///}"
  cp "${BACKUP_DIR}/database.sqlite" "${DB_FILE}"
  chmod 600 "${DB_FILE}"
  echo "Restored SQLite database to ${DB_FILE}"
elif [[ -f "${BACKUP_DIR}/database.pgdump" && "${DB_URL}" == postgres* ]]; then
  pg_restore --clean --if-exists --dbname="${DB_URL}" "${BACKUP_DIR}/database.pgdump"
  echo "Restored PostgreSQL database."
else
  echo "Mismatch between backup format and TOMOH_DATABASE_URL." >&2
  exit 1
fi

echo "Restore completed successfully."
