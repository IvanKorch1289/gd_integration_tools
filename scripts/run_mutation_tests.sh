#!/usr/bin/env bash
# Sprint 39 W4 — Mutation testing runner (mutmut wrapper).
#
# Назначение:
#     Прогоняет mutmut на hot-модулях, описанных в [tool.mutmut] pyproject.toml,
#     и возвращает exit-code по спринтовому gate (S39 W4: mutation score ≥ 55%).
#     Использует coverage-guided фильтрацию (--use-coverage): прогоняет только
#     тесты, реально покрывающие мутируемый код, что сокращает цикл с ~30 минут
#     до 3-5 минут.
#
# Использование:
#     ./scripts/run_mutation_tests.sh             # полный прогон (3 модуля)
#     ./scripts/run_mutation_tests.sh results     # показать только summary
#     ./scripts/run_mutation_tests.sh html        # сгенерировать HTML-отчёт
#     ./scripts/run_mutation_tests.sh clean       # очистить мутационный кэш
#     ./scripts/run_mutation_tests.sh quick       # smoke-run на 5 мутациях
#
# Переменные окружения:
#     MUTMUT_MIN_SCORE   переопределяет minimum_score из pyproject.toml (%)
#     MUTMUT_TIMEOUT     переопределяет timeout на мутацию (сек)
#
# Замечания:
#     - Скрипт идемпотентен; повторный вызов = догоняет оставшиеся мутации.
#     - HTML-отчёт пишется в mutants/ (mutmut 2.x convention).
#     - .mutmut-cache и mutants/ должны быть в .gitignore (см. docs/MUTATION_TESTING.md).

set -euo pipefail

# ---- paths -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_PY="${REPO_ROOT}/.venv/bin/python"
COVERAGE_DATA="${REPO_ROOT}/.coverage.mutations"
MUTMUT_CACHE="${REPO_ROOT}/.mutmut-cache"
MUTMUT_HTML_DIR="${REPO_ROOT}/mutants"
MUTMUT_MIN_SCORE="${MUTMUT_MIN_SCORE:-55.0}"
MUTMUT_TIMEOUT="${MUTMUT_TIMEOUT:-60}"

cd "${REPO_ROOT}"

# ---- helpers -----------------------------------------------------------------
log()  { printf '\033[1;34m[mutation]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[mutation][warn]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[mutation][err]\033[0m %s\n' "$*" >&2; }

usage() {
    sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
}

require_python() {
    if [[ ! -x "${VENV_PY}" ]]; then
        err "Python venv not found at ${VENV_PY}"
        err "Создайте его: python3.13 -m venv .venv && .venv/bin/pip install -e .[test]"
        exit 2
    fi
}

ensure_mutmut() {
    if ! "${VENV_PY}" -c "import mutmut" 2>/dev/null; then
        log "mutmut не установлен; ставлю mutmut==2.4.4"
        "${VENV_PY}" -m pip install --quiet "mutmut==2.4.4"
    fi
    "${VENV_PY}" -m mutmut --version
}

# ---- commands ----------------------------------------------------------------
cmd_run() {
    require_python
    ensure_mutmut

    log "Этап 1/3: сбор coverage для фильтрации тестов"
    rm -f "${COVERAGE_DATA}"
    "${VENV_PY}" -m coverage run --branch --data-file="${COVERAGE_DATA}" \
        -m pytest -q -m unit \
        tests/unit/core/config tests/unit/dsl/builders tests/unit/core/resilience \
        --no-header 2>&1 | tail -20 || {
            err "Базовый прогон unit-тестов провалился — fix tests before mutations"
            exit 1
        }
    "${VENV_PY}" -m coverage combine --keep --data-file="${COVERAGE_DATA}" || true

    log "Этап 2/3: запуск мутационного тестирования (mutmut run)"
    log "        gate: mutation score >= ${MUTMUT_MIN_SCORE}%, timeout: ${MUTMUT_TIMEOUT}s/mutation"
    MUTMUT_TIMEOUT="${MUTMUT_TIMEOUT}" "${VENV_PY}" -m mutmut run \
        --use-coverage \
        --coverage-data-file="${COVERAGE_DATA}" \
        || {
            rc=$?
            warn "mutmut run exited with ${rc} (часть мутаций выжила — см. mutants/)"
        }

    log "Этап 3/3: оценка mutation score"
    local score
    score="$("${VENV_PY}" -m mutmut results 2>/dev/null \
        | awk '/^Mutation score/ {print $3}' | tr -d '%' || echo "0")"
    score="${score:-0}"
    log "Mutation score: ${score}%  (gate: ${MUTMUT_MIN_SCORE}%)"

    # Сравнение float'ов через awk (bash не умеет float-arithmetic портативно).
    local pass
    pass="$(awk -v s="${score}" -v g="${MUTMUT_MIN_SCORE}" 'BEGIN{print (s+0 >= g+0) ? 1 : 0}')"
    if [[ "${pass}" == "1" ]]; then
        log "GATE PASSED: ${score}% >= ${MUTMUT_MIN_SCORE}%"
        return 0
    else
        err "GATE FAILED: ${score}% < ${MUTMUT_MIN_SCORE}%"
        err "См. mutants/html/index.html — каждая выжившая мутация = упущенный тест-кейс."
        return 1
    fi
}

cmd_results() {
    require_python
    log "Сводка по мутациям:"
    "${VENV_PY}" -m mutmut results
}

cmd_html() {
    require_python
    log "Генерация HTML-отчёта → ${MUTMUT_HTML_DIR}/html/"
    "${VENV_PY}" -m mutmut html
    log "Открой: file://${MUTMUT_HTML_DIR}/html/index.html"
}

cmd_clean() {
    log "Очистка mutation-артефактов"
    rm -rf "${MUTMUT_CACHE}" "${MUTMUT_HTML_DIR}" "${COVERAGE_DATA}"
    log "OK"
}

cmd_quick() {
    require_python
    ensure_mutmut
    log "Smoke-run: первые 5 мутаций (для CI dry-check)"
    "${VENV_PY}" -m mutmut run --use-coverage --coverage-data-file="${COVERAGE_DATA}" \
        || true
    "${VENV_PY}" -m mutmut results | head -20
}

# ---- dispatch ----------------------------------------------------------------
case "${1:-run}" in
    run)     cmd_run ;;
    results) cmd_results ;;
    html)    cmd_html ;;
    clean)   cmd_clean ;;
    quick)   cmd_quick ;;
    -h|--help|help) usage ;;
    *)
        err "Unknown command: ${1}"
        usage
        exit 2
        ;;
esac
