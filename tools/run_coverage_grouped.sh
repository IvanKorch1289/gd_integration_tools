#!/usr/bin/env bash
# Прогон тестов с coverage по группам + объединение (ADR-0453).
#
# Зачем: один монолитный `pytest tests --cov=src/backend` на dev-box падает
# с OOM (артефакт покрытия растёт на 24k тестов, ~45 мин). По группам
# память ограничена размером группы, а итоговый coverage.xml собирается
# через `coverage combine` — цифра сопоставима с монолитным прогоном.
#
# Использование:
#   tools/run_coverage_grouped.sh [--out coverage.xml] [--pytest-args "..."]
#
# Переменные окружения:
#   PYTHON        — интерпретатор (по умолчанию .venv/bin/python)
#   COVERAGE_DIR  — каталог частей покрытия (по умолчанию .coverage-parts)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-.venv/bin/python}"
COVERAGE_DIR="${COVERAGE_DIR:-.coverage-parts}"
OUT="coverage.xml"
PYTEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out) OUT="$2"; shift 2 ;;
        --pytest-args) read -r -a PYTEST_ARGS <<< "$2"; shift 2 ;;
        *) PYTEST_ARGS+=("$1"); shift ;;
    esac
done

rm -rf "$COVERAGE_DIR"
mkdir -p "$COVERAGE_DIR"

run_group() {
    local name="$1"; shift
    if [[ ! -e "$1" ]]; then
        return 0
    fi
    echo "[coverage] группа: ${name}"
    COVERAGE_FILE="${COVERAGE_DIR}/${name}.coverage" \
        "$PYTHON" -m pytest "$@" \
        --cov=src/backend \
        --cov-report= \
        --maxfail=20 \
        -n auto \
        "${PYTEST_ARGS[@]}"
}

# 1) подкаталоги верхнего уровня tests/ (unit разбит ниже по-своему)
shopt -s nullglob
for dir in tests/*/; do
    [[ "$dir" == "tests/unit/" ]] && continue
    run_group "top_$(basename "${dir%/}")" "$dir"
done

# 2) подкаталоги tests/unit/
for dir in tests/unit/*/; do
    run_group "unit_$(basename "${dir%/}")" "$dir"
done

# 3) модули верхнего уровня tests/unit/*.py
top_files=(tests/unit/*.py)
if [[ ${#top_files[@]} -gt 0 ]]; then
    run_group "unit_root_files" "${top_files[@]}"
fi

# 4) объединение частей и генерация XML
echo "[coverage] combine: ${COVERAGE_DIR}"
"$PYTHON" -m coverage combine "$COVERAGE_DIR"
"$PYTHON" -m coverage xml -o "$OUT"
echo "[coverage] готов: ${OUT}"
