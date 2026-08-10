#!/usr/bin/env bash
set -euo pipefail

# DATAEZ Database Restore Script
# Usage: ./restore.sh <backup_file.sql.gz>
#
# Environment variables:
#   POSTGRES_USER     (default: dataez)
#   POSTGRES_DB       (default: dataez)
#   DB_CONTAINER      (default: dataez-db)

BACKUP_FILE="${1:?Usage: ./restore.sh <backup_file.sql.gz>}"

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "[restore] ERROR: File not found: ${BACKUP_FILE}"
  exit 1
fi

DB_USER="${POSTGRES_USER:-dataez}"
DB_NAME="${POSTGRES_DB:-dataez}"
CONTAINER="${DB_CONTAINER:-dataez-db}"

echo "[restore] WARNING: This will DROP and recreate database '${DB_NAME}'."
read -rp "[restore] Continue? (y/N): " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
  echo "[restore] Aborted."
  exit 0
fi

echo "[restore] Dropping and recreating database..."
docker exec "${CONTAINER}" psql -U "${DB_USER}" -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME};"
docker exec "${CONTAINER}" psql -U "${DB_USER}" -d postgres -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

echo "[restore] Restoring from ${BACKUP_FILE}..."
gunzip -c "${BACKUP_FILE}" | docker exec -i "${CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" --quiet

echo "[restore] Done. Restart the API to re-establish connections:"
echo "  docker compose restart api"
