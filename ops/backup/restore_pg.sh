#!/usr/bin/env bash
# K-OPS-5 (Sprint 17): PostgreSQL restore + verify-restore-smoke.
#
# Восстанавливает БД из дампа на S3. Перед записью в target-БД делает
# smoke-проверку дампа (psql --schema-only --dry-run NOT доступен,
# поэтому валидируем через pg_restore --list для custom-формата или
# через `grep CREATE TABLE` для plain-format).
#
# Использование:
#   bash ops/backup/restore_pg.sh s3://bucket/path/dump.sql.gz
#   bash ops/backup/restore_pg.sh /tmp/local_dump.sql.gz
#
# ENV:
#   PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DATABASE
#   AWS_REGION (для S3-источников)
#   RESTORE_TARGET_DB — если указан, target = этот; иначе ${PG_DATABASE}_restore
#   DROP_TARGET       — true/false (default: false). Если true — DROP DATABASE
#                       перед CREATE.

set -euo pipefail

SOURCE="${1:?Usage: bash restore_pg.sh <s3://bucket/key|/local/path>}"

PG_HOST="${PG_HOST:-postgres}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-postgres}"
PG_DATABASE="${PG_DATABASE:-gd_integration_tools}"
RESTORE_TARGET_DB="${RESTORE_TARGET_DB:-${PG_DATABASE}_restore}"
DROP_TARGET="${DROP_TARGET:-false}"
AWS_REGION="${AWS_REGION:-ru-central-1}"

: "${PG_PASSWORD:?PG_PASSWORD is required}"

WORK_DIR="$(mktemp -d /tmp/restore_pg.XXXXXX)"
trap 'rm -rf "${WORK_DIR}"' EXIT

LOCAL_DUMP="${WORK_DIR}/dump.sql.gz"

if [[ "${SOURCE}" == s3://* ]]; then
    echo "[restore_pg] downloading from ${SOURCE}"
    if ! command -v aws >/dev/null 2>&1; then
        echo "[restore_pg] ERROR: aws CLI required for s3:// sources" >&2
        exit 1
    fi
    aws s3 cp --region "${AWS_REGION}" "${SOURCE}" "${LOCAL_DUMP}"
else
    [[ -f "${SOURCE}" ]] || { echo "[restore_pg] ERROR: not found: ${SOURCE}" >&2; exit 1; }
    cp "${SOURCE}" "${LOCAL_DUMP}"
fi

# Smoke-валидация: gunzip + поиск CREATE TABLE / COPY.
gunzip -t "${LOCAL_DUMP}" || { echo "[restore_pg] ERROR: corrupt gzip" >&2; exit 1; }
CREATE_TABLE_COUNT="$(gunzip -c "${LOCAL_DUMP}" | grep -c '^CREATE TABLE ' || true)"
if [[ "${CREATE_TABLE_COUNT}" -lt 1 ]]; then
    echo "[restore_pg] ERROR: dump contains no CREATE TABLE statements" >&2
    exit 1
fi
echo "[restore_pg] smoke OK: ${CREATE_TABLE_COUNT} CREATE TABLE statements"

export PGPASSWORD="${PG_PASSWORD}"

if [[ "${DROP_TARGET}" == "true" ]]; then
    echo "[restore_pg] dropping target DB ${RESTORE_TARGET_DB}"
    psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" \
        -d postgres -c "DROP DATABASE IF EXISTS \"${RESTORE_TARGET_DB}\""
fi

echo "[restore_pg] creating target DB ${RESTORE_TARGET_DB}"
psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" \
    -d postgres -c "CREATE DATABASE \"${RESTORE_TARGET_DB}\""

echo "[restore_pg] restoring dump into ${RESTORE_TARGET_DB}"
gunzip -c "${LOCAL_DUMP}" \
    | psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" \
        -d "${RESTORE_TARGET_DB}" \
        --set ON_ERROR_STOP=on \
        --quiet

# Verify-restore-smoke: количество таблиц должно быть > 0.
TABLE_COUNT="$(psql -h "${PG_HOST}" -p "${PG_PORT}" -U "${PG_USER}" \
    -d "${RESTORE_TARGET_DB}" -tA \
    -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"

if [[ "${TABLE_COUNT}" -lt 1 ]]; then
    echo "[restore_pg] ERROR: restored DB has no tables in schema 'public'" >&2
    exit 1
fi

echo "[restore_pg] verify-smoke OK: ${TABLE_COUNT} tables restored into ${RESTORE_TARGET_DB}"
echo "[restore_pg] done"
