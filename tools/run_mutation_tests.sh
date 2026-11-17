#!/usr/bin/env bash
# Mutation testing runner (mutmut 3.x wrapper).
#
# Назначение:
#     Прогоняет mutmut на hot-модулях, описанных в [tool.mutmut] pyproject.toml,
#     и возвращает exit-code по гейту: score >= порога из baseline
#     (.baselines/mutation.json, ADR-0452/ADR-0443).
#
# Использование:
#     ./tools/run_mutation_tests.sh             # полный прогон + гейт
#     ./tools/run_mutation_tests.sh results     # список мутаций и их вердикты
#     ./tools/run_mutation_tests.sh clean       # очистить mutation-кэш
#     ./tools/run_mutation_tests.sh quick       # smoke-прогон с малым бюджетом времени
#
# Переменные окружения:
#     MUTMUT_MIN_SCORE   переопределяет порог из baseline (%)
#     MUTMUT_TIMEOUT     бюджет времени на прогон мутаций (сек)
#
# Замечания:
#     - Реальная логика гейта (порог, подсчёт score, exit-коды) живёт в
#       tools/checks/check_mutmut.py — этот скрипт тонкая обёртка, чтобы
#       не было двух реализаций одного правила.
#     - mutmut 3.x: покрытие тестами определяется самим mutmut, флагов
#       --use-coverage/--coverage-data-file больше нет.
#     - Кэш результатов мутаций — mutants/*.meta; его НЕЛЬЗЯ стирать
#       синхронизацией рабочей копии (см. tools/checks/run_mutmut.py).

set -euo pipefail

# ---- paths -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PY="${REPO_ROOT}/.venv/bin/python"
GATE="${REPO_ROOT}/tools/checks/check_mutmut.py"
MUTMUT_MIN_SCORE="${MUTMUT_MIN_SCORE:-}"
MUTMUT_TIMEOUT="${MUTMUT_TIMEOUT:-}"

cd "${REPO_ROOT}"

# ---- helpers -----------------------------------------------------------------
log()  { printf '\033[1;34m[mutation]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[mutation][warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[mutation][err]\033[0m %s\n' "$*" >&2; }

usage() {
    sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
}

require_python() {
    if [[ ! -x "${VENV_PY}" ]]; then
        err "Python venv not found at ${VENV_PY}"
        err "Создайте его: python3.14 -m venv .venv && uv sync"
        exit 2
    fi
}

require_mutmut() {
    # Устанавливать пакеты из скрипта нельзя (политика проекта + риск
    # откатить версию mutmut и сломать гейт): проверяем и падаем внятно.
    if ! "${VENV_PY}" -c "import mutmut" 2>/dev/null; then
        err "mutmut не установлен в ${VENV_PY}"
        err "Установите его: uv sync  (mutmut>=3.6.0 в dev-группе)"
        exit 2
    fi
    "${VENV_PY}" -m mutmut --version
}

# ---- commands ----------------------------------------------------------------
cmd_run() {
    require_python
    require_mutmut
    log "Запуск mutation-гейта (порог — из .baselines/mutation.json)"
    local args=()
    [[ -n "${MUTMUT_MIN_SCORE}" ]] && args+=(--threshold "${MUTMUT_MIN_SCORE}")
    [[ -n "${MUTMUT_TIMEOUT}" ]] && args+=(--timeout "${MUTMUT_TIMEOUT}")
    "${VENV_PY}" "${GATE}" ${args[@]+"${args[@]}"}
}

cmd_results() {
    require_python
    require_mutmut
    log "Вердикты по мутациям:"
    "${VENV_PY}" -m mutmut results
}

cmd_clean() {
    require_python
    log "Очистка mutation-кэша (mutants/, .mutmut-cache)"
    rm -rf "${REPO_ROOT}/mutants" "${REPO_ROOT}/.mutmut-cache"
    log "OK"
}

cmd_quick() {
    require_python
    require_mutmut
    log "Smoke-прогон: бюджет времени ${MUTMUT_TIMEOUT:-120}s"
    MUTMUT_TIMEOUT="${MUTMUT_TIMEOUT:-120}" cmd_run
}

# ---- dispatch ----------------------------------------------------------------
case "${1:-run}" in
    run)     cmd_run ;;
    results) cmd_results ;;
    clean)   cmd_clean ;;
    quick)   cmd_quick ;;
    -h|--help|help) usage ;;
    *)
        err "Unknown command: ${1}"
        usage
        exit 2
        ;;
esac
