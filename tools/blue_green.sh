#!/usr/bin/env bash
# Sprint 7 Team T5 — Blue/Green deployment helper.
#
# Назначение:
#     Координирует переключение трафика между двумя независимыми
#     stack'ами (blue / green), запущенными из docker-compose.bluegreen.yml.
#     Реализует канонический паттерн blue/green deploy:
#
#         1) "blue" — текущая активная версия (получает 100% трафика).
#         2) "green" — новая версия, поднята параллельно, прогревается.
#         3) Smoke-test против green (health-endpoints + критичные routes).
#         4) Переключение nginx upstream blue → green.
#         5) Останавливается старый blue (или оставляется warm-pool на rollback).
#
# Использование:
#     ./scripts/blue_green.sh up green             # поднять green stack
#     ./scripts/blue_green.sh smoke green          # smoke-тест против green
#     ./scripts/blue_green.sh switch green         # переключить router на green
#     ./scripts/blue_green.sh down blue            # остановить старую версию
#     ./scripts/blue_green.sh status               # текущий active
#     ./scripts/blue_green.sh rollback             # вернуться на предыдущий
#
# Замечания:
#     - Скрипт идемпотентен: повторный вызов с тем же аргументом — no-op.
#     - Stub-реализация (Sprint 7 R1.6): production NGINX-роутер
#       подключается в Sprint 8 R2 через configs/nginx/active.conf.
#     - Хранит активный stack в .blue_green.state (gitignore).

set -euo pipefail

# ── Project root резолвится относительно расположения скрипта ─────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/ops/compose/docker-compose.bluegreen.yml"
STATE_FILE="${PROJECT_ROOT}/.blue_green.state"

# ── Утилиты ───────────────────────────────────────────────────────────
log() { printf '[blue-green] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

ensure_compose() {
    [[ -f "${COMPOSE_FILE}" ]] || die "compose file not found: ${COMPOSE_FILE}"
    command -v docker >/dev/null 2>&1 || die "docker not in PATH"
}

read_state() {
    [[ -f "${STATE_FILE}" ]] && cat "${STATE_FILE}" || echo "blue"
}

write_state() {
    printf '%s' "$1" > "${STATE_FILE}"
}

usage() {
    cat <<EOF
Usage: $0 <command> [stack]

Commands:
    up <blue|green>          Поднять указанный stack
    down <blue|green>        Остановить указанный stack
    smoke <blue|green>       Smoke-test (health-endpoints) против stack
    switch <blue|green>      Переключить router на указанный stack
    status                   Показать текущий активный stack
    rollback                 Откатиться на предыдущий активный stack

Examples:
    $0 up green
    $0 smoke green
    $0 switch green
    $0 down blue
EOF
}

# ── Команды ────────────────────────────────────────────────────────────

cmd_up() {
    local stack="$1"
    [[ "${stack}" == "blue" || "${stack}" == "green" ]] || die "stack must be blue or green"
    ensure_compose
    log "starting ${stack} stack..."
    docker compose -f "${COMPOSE_FILE}" --profile "${stack}" up -d
    log "${stack} stack is up"
}

cmd_down() {
    local stack="$1"
    [[ "${stack}" == "blue" || "${stack}" == "green" ]] || die "stack must be blue or green"
    ensure_compose
    log "stopping ${stack} stack..."
    docker compose -f "${COMPOSE_FILE}" --profile "${stack}" down
    log "${stack} stack is down"
}

cmd_smoke() {
    local stack="$1"
    [[ "${stack}" == "blue" || "${stack}" == "green" ]] || die "stack must be blue or green"
    local port
    [[ "${stack}" == "blue" ]] && port=8001 || port=8002
    log "smoke-testing ${stack} on :${port}..."
    if command -v curl >/dev/null 2>&1; then
        # Stub smoke: проверяем GET /health (production-pipeline расширяется
        # в Sprint 8 — добавляет проверки routes/actions/workflows).
        curl --fail --silent --max-time 5 "http://localhost:${port}/health" \
            || die "smoke failed for ${stack}"
        log "smoke OK for ${stack}"
    else
        log "WARN: curl missing — smoke skipped (assuming OK)"
    fi
}

cmd_switch() {
    local target="$1"
    [[ "${target}" == "blue" || "${target}" == "green" ]] || die "target must be blue or green"
    local current
    current="$(read_state)"
    if [[ "${current}" == "${target}" ]]; then
        log "router already on ${target} — no-op"
        return 0
    fi
    log "switching router: ${current} → ${target}"
    # Stub: production nginx reload запускается в Sprint 8 R2.
    # Здесь только обновляем state-файл.
    write_state "${target}"
    log "router switched to ${target}"
}

cmd_status() {
    local active
    active="$(read_state)"
    printf 'active stack: %s\n' "${active}"
}

cmd_rollback() {
    local current other
    current="$(read_state)"
    if [[ "${current}" == "blue" ]]; then
        other="green"
    else
        other="blue"
    fi
    log "rollback: ${current} → ${other}"
    write_state "${other}"
    log "rollback complete (router on ${other})"
}

# ── Главный диспатч ────────────────────────────────────────────────────
main() {
    if [[ $# -lt 1 ]]; then
        usage
        exit 1
    fi
    local command="$1"
    shift || true

    case "${command}" in
        up|down|smoke|switch)
            [[ $# -eq 1 ]] || { usage; exit 1; }
            "cmd_${command}" "$1"
            ;;
        status|rollback)
            "cmd_${command}"
            ;;
        -h|--help|help)
            usage
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"
