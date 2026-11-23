#!/usr/bin/env bash
# Прогон тестов по группам — ограничение пиковой памяти процесса (P6).
#
# Зачем
# ----
# Один процесс pytest на все tests/unit держит в памяти состояние всех
# собранных модулей и тестовых артефактов. Измерено 2026-11-23:
#   * tests/unit/entrypoints (1839 тестов) — пик RSS 1.94 ГБ одним процессом
#     и 2.81 ГБ при `-n 2 --dist loadfile` (канонический режим CI);
#   * единый прогон ~5k тестов в одном процессе → SIGSEGV при 2.6 ГБ
#     свободной RAM.
# То есть ограничение не «хочется аккуратнее», а это требование к
# dev-box и к раннеру CI. Прогон по группам держит пик в пределах одной
# группы; каждая группа — отдельный процесс pytest, память освобождается
# между группами.
#
# Аналогично уже существующему tools/run_coverage_grouped.sh (ADR-0453),
# но без coverage: используется для обычного прогона (`make unit-tests`).
#
# Использование:
#   tools/run_tests_grouped.sh                       # tests/unit, -n 2
#   tools/run_tests_grouped.sh --jobs 4              # больше воркеров
#   tools/run_tests_grouped.sh --path tests/smoke    # другой набор
#   tools/run_tests_grouped.sh -- -k "some marker"   # остальные аргументы pytest
#
# Переменные окружения:
#   PYTHON — интерпретатор (по умолчанию .venv/bin/python)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-.venv/bin/python}"
JOBS=2
TARGET="tests/unit"
PYTEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --jobs) JOBS="$2"; shift 2 ;;
        --path) TARGET="$2"; shift 2 ;;
        --) shift; PYTEST_ARGS+=("$@"); break ;;
        *) PYTEST_ARGS+=("$1"); shift ;;
    esac
done

if [[ ! -d "$TARGET" ]]; then
    echo "ОШИБКА: каталога нет: ${TARGET}" >&2
    exit 2
fi

# Группа = отдельный процесс pytest. Пустая группа (нет test_*.py) —
# пропускается: pytest вернул бы exit 5 («no tests ran»).
has_tests() {
    find "$1" -type f -name 'test_*.py' -print -quit 2>/dev/null | grep -q .
}

run_group() {
    local name="$1"
    shift
    if ! has_tests "$1"; then
        echo "[tests] группа ${name}: тестов нет — пропуск"
        return 0
    fi
    echo "[tests] группа: ${name}"
    "$PYTHON" -m pytest "$@" \
        -n "${JOBS}" --dist loadfile \
        --no-header -q \
        "${PYTEST_ARGS[@]}"
}

# 1) подкаталоги верхнего уровня (tests/unit/<sub>/)
shopt -s nullglob
for dir in "${TARGET}"/*/; do
    [[ "$dir" == */entrypoints/ ]] && continue
    run_group "$(basename "${dir%/}")" "${dir%/}"
done

# 2) подкаталоги tests/unit/entrypoints/ — самая тяжёлая группа, делим ещё
entrypoints_dir="${TARGET%/}/entrypoints"
if [[ -d "$entrypoints_dir" ]]; then
    for dir in "${entrypoints_dir}"/*/; do
        run_group "entrypoints/$(basename "${dir%/}")" "${dir%/}"
    done
    # Файлы верхнего уровня tests/unit/entrypoints/
    top_files=("${entrypoints_dir}"/test_*.py)
    if [[ ${#top_files[@]} -gt 0 ]]; then
        run_group "entrypoints/root_files" "${top_files[@]}"
    fi
fi

# 3) тестовые файлы верхнего уровня (tests/unit/test_*.py)
top_files=("${TARGET%/}"/test_*.py)
if [[ ${#top_files[@]} -gt 0 ]]; then
    run_group "root_files" "${top_files[@]}"
fi

echo "[tests] все группы пройдены: ${TARGET} (jobs=${JOBS})"
