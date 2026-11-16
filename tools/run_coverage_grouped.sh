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

# Есть ли в каталоге тесты. Пустая группа → pytest «no tests ran» (exit 5)
# и весь прогон падал бы на tests/fixtures/, tests/factories/, __pycache__/.
has_tests() {
    find "$1" -type f -name 'test_*.py' -print -quit 2>/dev/null | grep -q .
}

run_group() {
    local name="$1"; shift
    if [[ ! -e "$1" ]]; then
        return 0
    fi
    if ! has_tests "$1"; then
        echo "[coverage] группа ${name}: тестов нет — пропуск"
        return 0
    fi
    echo "[coverage] группа: ${name}"
    # Имя части — `.coverage.<group>`: `coverage combine` ищет именно
    # `<dir>/.coverage.*` (при parallel=true ещё и с суффиксом хоста/ pid).
    # Префикс `.coverage.<group>` без точки-разделителя combine не видел →
    # «No data to combine» (exit 1) и итоговый coverage.xml не создавался.
    #
    # `--cov-fail-under=0`: порог 70 % из pyproject применяется к КАЖДОЙ
    # группе, где он недостижим (группа покрывает поддерево src/). Итоговый
    # порог проверяется один раз — на объединённом отчёте (coverage xml) и
    # гейтом tools/check_coverage_gate.py (порог из baseline).
    set +e
    COVERAGE_FILE="${COVERAGE_DIR}/.coverage.${name}" \
        "$PYTHON" -m pytest "$@" \
        --cov=src/backend \
        --cov-report= \
        --cov-fail-under=0 \
        --maxfail=20 \
        -n auto \
        "${PYTEST_ARGS[@]}"
    local rc=$?
    set -e
    # 5 = «no tests ran» (например, каталог есть, а собираемых тестов в нём
    # нет). Это не падение: группа пропускается. Любой другой код — ошибка
    # тестов, прогон прерывается (fail-closed).
    if [[ $rc -eq 5 ]]; then
        echo "[coverage] группа ${name}: тестов не собрано — пропуск"
        return 0
    fi
    return $rc
}

# 1) подкаталоги верхнего уровня tests/ (unit разбит ниже по-своему)
#
# Исключения (среды, которых нет в CI-джобе):
#   * tests/chaos — свой workflow (.github/workflows/chaos.yml) с живыми
#     брокерами и toxiproxy; фикстуры toxiproxy_* недоступны в обычном
#     прогоне (pytest-toxiproxy не в lock-файле) → «fixture not found»;
#   * tests/integration — требует живых PostgreSQL/Redis/браузеров; часть
#     сьютов вынесена в отдельный workflow (sentinel-integration.yml).
#     В обычном прогоне группа падала на внешних сервисах.
shopt -s nullglob
for dir in tests/*/; do
    [[ "$dir" == "tests/unit/" ]] && continue
    [[ "$dir" == "tests/chaos/" ]] && continue
    [[ "$dir" == "tests/integration/" ]] && continue
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
# Старый .coverage в корне (артефакт монолитного прогона) не должен
# смешиваться с частями: иначе цифра покрытия не соответствует этому
# прогону. Файл в .gitignore, артефакт локального прогона.
rm -f .coverage
echo "[coverage] combine: ${COVERAGE_DIR}"
"$PYTHON" -m coverage combine "$COVERAGE_DIR"
"$PYTHON" -m coverage xml -o "$OUT"
echo "[coverage] готов: ${OUT}"
