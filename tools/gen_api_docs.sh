#!/usr/bin/env bash
# scripts/gen_api_docs.sh — генерация auto-generated API reference (S40 W4).
#
# Pipeline: sphinx-apidoc → docs/api/_apidoc/, затем sphinx-build → docs/api/_build/html/
# Exit: 0 = ОК, 1 = python/sphinx not found, 2 = apidoc failed, 3 = build failed.
#
# Использование:
#   ./scripts/gen_api_docs.sh             # полный build
#   ./scripts/gen_api_docs.sh --clean     # очистить _build/ и _apidoc/

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." &> /dev/null && pwd)"
DOCS_API_DIR="${REPO_ROOT}/docs/api"
APIDOC_OUT="${DOCS_API_DIR}/_apidoc"
BUILD_OUT="${DOCS_API_DIR}/_build/html"
APISRC="${REPO_ROOT}/src/backend/dsl"

# Sanity-check: убеждаемся, что мы в корне репозитория.
if [[ ! -d "${APISRC}" ]]; then
    printf 'ERROR: %s does not look like the repo root (missing %s)\n' \
        "${REPO_ROOT}" "${APISRC}" >&2
    exit 4
fi

# Python detection: локальный .venv → system python3 → python.
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" && -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
fi
if [[ -z "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="$(command -v python3 || command -v python || true)"
fi
[[ -z "${PYTHON_BIN}" ]] && { echo "ERROR: no python interpreter" >&2; exit 1; }

if ! "${PYTHON_BIN}" -c 'import sphinx' 2> /dev/null; then
    echo "ERROR: sphinx not importable. pip install -r ${DOCS_API_DIR}/requirements.txt" >&2
    exit 1
fi

printf 'Python: %s | Sphinx: %s\n' "${PYTHON_BIN}" "$("${PYTHON_BIN}" -c 'import sphinx; print(sphinx.__version__)')"

# Sphinx binaries (sphinx-build / sphinx-apidoc рядом с python).
SPHINX_BUILD_BIN="${SPHINX_BUILD:-${PYTHON_BIN%/*}/sphinx-build}"
SPHINX_APIDOC_BIN="${SPHINX_APIDOC:-${PYTHON_BIN%/*}/sphinx-apidoc}"
[[ -x "${SPHINX_BUILD_BIN}" ]] || SPHINX_BUILD_BIN="${PYTHON_BIN} -m sphinx"
[[ -x "${SPHINX_APIDOC_BIN}" ]] || SPHINX_APIDOC_BIN="${PYTHON_BIN} -m sphinx.cmd.apidoc"

# CLI flags.
CLEAN_ONLY=0
for arg in "$@"; do
    case "${arg}" in
        --clean) CLEAN_ONLY=1 ;;
        -h|--help)
            sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "Unknown flag: ${arg}" >&2; exit 1 ;;
    esac
done

run_apidoc() {
    printf '\n=== sphinx-apidoc → %s/ ===\n' "${APIDOC_OUT}"
    mkdir -p "${APIDOC_OUT}"
    # -f перезаписывать, -e отдельная страница на модуль,
    # -M пропустить __init__ без docstring, -T не создавать toc-файл.
    "${SPHINX_APIDOC_BIN}" -f -e -M -T -d 2 --module-first --implicit-namespaces \
        -o "${APIDOC_OUT}" "${APISRC}"
}

run_html() {
    printf '\n=== sphinx-build → %s/ ===\n' "${BUILD_OUT}"
    mkdir -p "${BUILD_OUT}"
    "${SPHINX_BUILD_BIN}" -b html "${DOCS_API_DIR}" "${BUILD_OUT}"
}

if [[ "${CLEAN_ONLY}" -eq 1 ]]; then
    printf '=== clean ===\n'
    rm -rf "${DOCS_API_DIR}/_build" "${DOCS_API_DIR}/_apidoc"
    echo "[OK] Cleaned."
    exit 0
fi

run_apidoc || { echo "sphinx-apidoc FAILED" >&2; exit 2; }
run_html    || { echo "sphinx-build FAILED" >&2; exit 3; }

printf '\n[OK] HTML: file://%s/index.html\n' "${BUILD_OUT}"
exit 0
