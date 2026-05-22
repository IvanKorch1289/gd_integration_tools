#!/usr/bin/env bash
# K-OPS-5 (Sprint 17): PostgreSQL backup → S3.
#
# Использование:
#   bash ops/backup/backup_pg.sh
#
# ENV-переменные (с дефолтами):
#   PG_HOST            — хост PostgreSQL (default: postgres)
#   PG_PORT            — порт (default: 5432)
#   PG_USER            — пользователь (default: postgres)
#   PG_PASSWORD        — пароль (REQUIRED — из Vault или secrets-backend)
#   PG_DATABASE        — БД (default: gd_integration_tools)
#   BACKUP_S3_BUCKET   — S3 bucket для дампов (REQUIRED)
#   BACKUP_S3_PREFIX   — prefix внутри bucket (default: postgres/)
#   AWS_REGION         — регион S3 (default: ru-central-1)
#   RETENTION_DAYS     — local-retention (default: 7)
#
# RPO target: ≤1h (запускается ежечасно через APScheduler или cron).
# RTO target: ≤30min (см. restore_pg.sh).

set -euo pipefail

PG_HOST="${PG_HOST:-postgres}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"
PG_DATABASE="${PG_DATABASE:-gd_integration_tools}"
BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-postgres/}"
AWS_REGION="${AWS_REGION:-ru-central-1}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

: "${PG_PASSWORD:?PG_PASSWORD is required (load from Vault/secrets backend)}"
: "${BACKUP_S3_BUCKET:?BACKUP_S3_BUCKET is required}"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_DIR:-/var/lib/gd_integration_tools/backups}"
mkdir -p "${BACKUP_DIR}"

BACKUP_FILE="${BACKUP_DIR}/pg_${PG_DATABASE}_${TIMESTAMP}.sql.gz"
S3_KEY="${BACKUP_S3_PREFIX}pg_${PG_DATABASE}_${TIMESTAMP}.sql.gz"

echo "[backup_pg] start: ${PG_DATABASE} @ ${PG_HOST}:${PG_PORT}"
echo "[backup_pg] target: s3://${BACKUP_S3_BUCKET}/${S3_KEY}"

PGPASSWORD="${PG_PASSWORD}" pg_dump \
    --host="${PG_HOST}" \
    --port="${PG_PORT}" \
    --username="${PG_USER}" \
    --dbname="${PG_DATABASE}" \
    --no-owner \
    --no-acl \
    --format=plain \
    --verbose 2>/tmp/pg_dump.err \
    | gzip -9 > "${BACKUP_FILE}"

DUMP_SIZE="$(stat -c '%s' "${BACKUP_FILE}")"
echo "[backup_pg] dump complete: ${BACKUP_FILE} (${DUMP_SIZE} bytes)"

if [[ "${DUMP_SIZE}" -lt 1024 ]]; then
    echo "[backup_pg] ERROR: dump suspiciously small (<1KB)" >&2
    cat /tmp/pg_dump.err >&2
    exit 1
fi

# Upload to S3 через aws-cli (или s3cmd, или mc).
if command -v aws >/dev/null 2>&1; then
    aws s3 cp \
        --region "${AWS_REGION}" \
        --sse AES256 \
        "${BACKUP_FILE}" \
        "s3://${BACKUP_S3_BUCKET}/${S3_KEY}"
    echo "[backup_pg] uploaded to s3://${BACKUP_S3_BUCKET}/${S3_KEY}"
else
    echo "[backup_pg] WARN: aws CLI not found — skipping S3 upload" >&2
fi

# Local retention.
find "${BACKUP_DIR}" -name "pg_${PG_DATABASE}_*.sql.gz" \
    -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true

echo "[backup_pg] done"
