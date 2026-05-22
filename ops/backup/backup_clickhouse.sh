#!/usr/bin/env bash
# K-OPS-5 (Sprint 17): ClickHouse backup → S3 (audit-таблицы).
#
# Использует `clickhouse-backup` CLI (рекомендуется AltinityLabs)
# или fallback на `clickhouse-client` для freeze + tar.
#
# Использование:
#   bash ops/backup/backup_clickhouse.sh
#
# ENV (с дефолтами):
#   CH_HOST             — (default: clickhouse)
#   CH_PORT             — TCP-порт native (default: 9000)
#   CH_HTTP_PORT        — HTTP-порт (default: 8123)
#   CH_USER             — (default: default)
#   CH_PASSWORD         — (REQUIRED, из Vault)
#   CH_DATABASE         — БД (default: audit)
#   BACKUP_S3_BUCKET    — (REQUIRED)
#   BACKUP_S3_PREFIX    — (default: clickhouse/)
#   AWS_REGION          — (default: ru-central-1)
#   RETENTION_DAYS      — (default: 14)

set -euo pipefail

CH_HOST="${CH_HOST:-clickhouse}"
CH_PORT="${CH_PORT:-9000}"
CH_HTTP_PORT="${CH_HTTP_PORT:-8123}"
CH_USER="${CH_USER:-default}"
CH_DATABASE="${CH_DATABASE:-audit}"
BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-clickhouse/}"
AWS_REGION="${AWS_REGION:-ru-central-1}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

: "${CH_PASSWORD:?CH_PASSWORD is required}"
: "${BACKUP_S3_BUCKET:?BACKUP_S3_BUCKET is required}"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_NAME="ch_${CH_DATABASE}_${TIMESTAMP}"
BACKUP_DIR="${BACKUP_DIR:-/var/lib/gd_integration_tools/backups}"
mkdir -p "${BACKUP_DIR}"

echo "[backup_clickhouse] start: ${CH_DATABASE} @ ${CH_HOST}:${CH_PORT}"

if command -v clickhouse-backup >/dev/null 2>&1; then
    # Predefined path (см. clickhouse-backup config).
    clickhouse-backup create "${BACKUP_NAME}"
    clickhouse-backup upload "${BACKUP_NAME}"
    echo "[backup_clickhouse] done via clickhouse-backup CLI"
    exit 0
fi

# Fallback: ALTER TABLE FREEZE + tar.gz + S3 upload.
echo "[backup_clickhouse] WARN: clickhouse-backup CLI not found, fallback to FREEZE+tar"

# Получаем shadow-каталог через freeze.
ARCHIVE_FILE="${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
S3_KEY="${BACKUP_S3_PREFIX}${BACKUP_NAME}.tar.gz"

clickhouse_query() {
    curl --silent --fail --max-time 30 \
        --user "${CH_USER}:${CH_PASSWORD}" \
        --data-binary "$1" \
        "http://${CH_HOST}:${CH_HTTP_PORT}/"
}

TABLES="$(clickhouse_query "SELECT name FROM system.tables WHERE database='${CH_DATABASE}' FORMAT TabSeparated")"
if [[ -z "${TABLES}" ]]; then
    echo "[backup_clickhouse] ERROR: no tables in ${CH_DATABASE}" >&2
    exit 1
fi

for tbl in ${TABLES}; do
    clickhouse_query "ALTER TABLE ${CH_DATABASE}.${tbl} FREEZE" >/dev/null
done

SHADOW_DIR="/var/lib/clickhouse/shadow"
if [[ ! -d "${SHADOW_DIR}" ]]; then
    echo "[backup_clickhouse] ERROR: shadow dir not found: ${SHADOW_DIR}" >&2
    exit 1
fi

tar -czf "${ARCHIVE_FILE}" -C "${SHADOW_DIR}" .
echo "[backup_clickhouse] archive: ${ARCHIVE_FILE} ($(stat -c '%s' "${ARCHIVE_FILE}") bytes)"

if command -v aws >/dev/null 2>&1; then
    aws s3 cp \
        --region "${AWS_REGION}" \
        --sse AES256 \
        "${ARCHIVE_FILE}" \
        "s3://${BACKUP_S3_BUCKET}/${S3_KEY}"
    echo "[backup_clickhouse] uploaded to s3://${BACKUP_S3_BUCKET}/${S3_KEY}"
fi

rm -rf "${SHADOW_DIR}"
find "${BACKUP_DIR}" -name "ch_${CH_DATABASE}_*.tar.gz" \
    -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true

echo "[backup_clickhouse] done (fallback path)"
