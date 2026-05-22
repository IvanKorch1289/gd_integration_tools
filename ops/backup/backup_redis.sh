#!/usr/bin/env bash
# K-OPS-5 (Sprint 17): Redis backup → S3.
#
# Запускает redis-cli BGSAVE (асинхронный snapshot RDB), ждёт окончания и
# заливает dump.rdb на S3. Метод не блокирует redis-сервер.
#
# Использование:
#   bash ops/backup/backup_redis.sh
#
# ENV (с дефолтами):
#   REDIS_HOST          — хост (default: redis)
#   REDIS_PORT          — порт (default: 6379)
#   REDIS_PASSWORD      — auth (опционально)
#   REDIS_DATA_DIR      — каталог RDB-файла (default: /data — стандарт redis:7-alpine)
#   BACKUP_S3_BUCKET    — S3 bucket (REQUIRED)
#   BACKUP_S3_PREFIX    — prefix (default: redis/)
#   AWS_REGION          — регион (default: ru-central-1)
#   BGSAVE_TIMEOUT_SEC  — макс. ожидание (default: 600)

set -euo pipefail

REDIS_HOST="${REDIS_HOST:-redis}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_DATA_DIR="${REDIS_DATA_DIR:-/data}"
BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-redis/}"
AWS_REGION="${AWS_REGION:-ru-central-1}"
BGSAVE_TIMEOUT_SEC="${BGSAVE_TIMEOUT_SEC:-600}"

: "${BACKUP_S3_BUCKET:?BACKUP_S3_BUCKET is required}"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
S3_KEY="${BACKUP_S3_PREFIX}redis_${TIMESTAMP}.rdb"

redis_cli() {
    if [[ -n "${REDIS_PASSWORD:-}" ]]; then
        redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" -a "${REDIS_PASSWORD}" --no-auth-warning "$@"
    else
        redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" "$@"
    fi
}

echo "[backup_redis] start: ${REDIS_HOST}:${REDIS_PORT}"

LAST_SAVE_BEFORE="$(redis_cli LASTSAVE)"
redis_cli BGSAVE | grep -qi "Background saving started" \
    || { echo "[backup_redis] ERROR: BGSAVE refused" >&2; exit 1; }

# Ожидание окончания BGSAVE: LASTSAVE должен увеличиться.
DEADLINE=$(( $(date +%s) + BGSAVE_TIMEOUT_SEC ))
while true; do
    LAST_SAVE_AFTER="$(redis_cli LASTSAVE)"
    if [[ "${LAST_SAVE_AFTER}" != "${LAST_SAVE_BEFORE}" ]]; then
        break
    fi
    if [[ $(date +%s) -ge ${DEADLINE} ]]; then
        echo "[backup_redis] ERROR: BGSAVE timeout (${BGSAVE_TIMEOUT_SEC}s)" >&2
        exit 1
    fi
    sleep 2
done
echo "[backup_redis] BGSAVE finished (LASTSAVE=${LAST_SAVE_AFTER})"

RDB_PATH="${REDIS_DATA_DIR}/dump.rdb"
if [[ ! -f "${RDB_PATH}" ]]; then
    echo "[backup_redis] ERROR: dump.rdb not found at ${RDB_PATH}" >&2
    exit 1
fi

RDB_SIZE="$(stat -c '%s' "${RDB_PATH}")"
echo "[backup_redis] dump.rdb: ${RDB_PATH} (${RDB_SIZE} bytes)"

if command -v aws >/dev/null 2>&1; then
    aws s3 cp \
        --region "${AWS_REGION}" \
        --sse AES256 \
        "${RDB_PATH}" \
        "s3://${BACKUP_S3_BUCKET}/${S3_KEY}"
    echo "[backup_redis] uploaded to s3://${BACKUP_S3_BUCKET}/${S3_KEY}"
else
    echo "[backup_redis] WARN: aws CLI not found — skipping S3 upload" >&2
fi

echo "[backup_redis] done"
