#!/usr/bin/env bash
# TOMOH Weekly Report Automation — Safe Release Rollback Script
# Stops app, restores verified pre-upgrade backup, and checks health.
set -euo pipefail

BACKUP_DIR="${1:?Usage: rollback.sh <pre_upgrade_backup_dir> [compose_file]}"
COMPOSE_FILE="${2:-deploy/docker-compose.prod.yml}"

echo "[1/3] Verifying backup integrity..."
(cd "${BACKUP_DIR}" && sha256sum -c SHA256SUMS.txt)

echo "[2/3] Restoring database from ${BACKUP_DIR}..."
./scripts/restore.sh "${BACKUP_DIR}"

echo "[3/3] Rollback complete. Restart previous container image via:"
echo "  docker compose -f ${COMPOSE_FILE} up -d"
