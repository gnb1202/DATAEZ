#!/usr/bin/env bash
set -euo pipefail

# DATAEZ Database Backup Script
# Usage: ./backup.sh [output_dir]
#
# Environment variables:
#   POSTGRES_USER     (default: dataez)
#   POSTGRES_DB       (default: dataez)
#   DB_CONTAINER      (default: dataez-db)
#   S3_BUCKET         (optional — upload to S3 if set)
#   S3_PREFIX         (default: backups)

OUTPUT_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="dataez_backup_${TIMESTAMP}.sql.gz"
FILEPATH="${OUTPUT_DIR}/${FILENAME}"

DB_USER="${POSTGRES_USER:-dataez}"
DB_NAME="${POSTGRES_DB:-dataez}"
CONTAINER="${DB_CONTAINER:-dataez-db}"

mkdir -p "${OUTPUT_DIR}"

echo "[backup] Starting backup of ${DB_NAME}..."
docker exec "${CONTAINER}" pg_dump -U "${DB_USER}" "${DB_NAME}" | gzip > "${FILEPATH}"

FILE_SIZE=$(du -h "${FILEPATH}" | cut -f1)
echo "[backup] Saved: ${FILEPATH} (${FILE_SIZE})"

# Upload to S3 if configured
if [ -n "${S3_BUCKET:-}" ]; then
  S3_KEY="${S3_PREFIX:-backups}/${FILENAME}"
  echo "[backup] Uploading to s3://${S3_BUCKET}/${S3_KEY}..."
  aws s3 cp "${FILEPATH}" "s3://${S3_BUCKET}/${S3_KEY}"
  echo "[backup] S3 upload complete."
fi

# Retain only last 7 local backups
cd "${OUTPUT_DIR}"
ls -1t dataez_backup_*.sql.gz 2>/dev/null | tail -n +8 | xargs -r rm --
echo "[backup] Done."
