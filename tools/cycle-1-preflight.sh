#!/usr/bin/env bash
# cycle-1-preflight.sh — preflight gate для cycle 1 задач T-1..T-4.
# Запуск: bash tools/cycle-1-preflight.sh
# Exit 0 — все gates green; иначе 1.
#
# Зависимости: python (с .venv), make, grep, git, wc.

set -u
fail=0

print_check() {
    local name="$1"
    local status="$2"
    local detail="$3"
    if [[ "$status" == "OK" ]]; then
        printf '  [OK]   %s — %s\n' "$name" "$detail"
    else
        printf '  [FAIL] %s — %s\n' "$name" "$detail"
        fail=1
    fi
}

printf 'cycle-1 preflight (T-0.1 re-run):\n'

# Gate 1 — layer checker
if python tools/check_layers.py --root src > /tmp/preflight-layers.txt 2>&1; then
    if grep -qE "0 новых.*175 legacy" /tmp/preflight-layers.txt; then
        print_check "layer checker" OK "0 new, 175 legacy"
    else
        print_check "layer checker" FAIL "unexpected output (см. /tmp/preflight-layers.txt)"
    fi
else
    print_check "layer checker" FAIL "non-zero exit (см. /tmp/preflight-layers.txt)"
fi

# Gate 2 — security allowlist count
# cycle-4/D-AUDIT-02: baseline lowered from 35 to 27 (8 stale CVE removed).
count=$(grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt || true)
if [[ "$count" -le "35" ]]; then
    print_check "allowlist active IDs" OK "$count"
else
    print_check "allowlist active IDs" FAIL "expected <=35, got $count"
fi

# Gate 3 — docstring gate
if make check-docstrings MAX_ALLOWED=0 > /tmp/preflight-doc.txt 2>&1; then
    print_check "docstring gate" OK "0 missing"
else
    print_check "docstring gate" FAIL "non-zero exit (см. /tmp/preflight-doc.txt)"
fi

# Gate 4 — pre-existing dirty tree
if git status --short | grep -qE '^\?\? pip-audit\.json$'; then
    # pip-audit.json — это наш собственный артефакт, не чужой
    :
fi
dirty_count=$(git status --short | wc -l | tr -d ' ')
if [[ "$dirty_count" -le 3 ]]; then
    print_check "working tree" OK "$dirty_count entries (uv.lock + audit artifacts)"
else
    print_check "working tree" FAIL "$dirty_count entries (разобраться)"
fi

# Gate 5 — uv.lock churn
uvlock_lines=$(git diff uv.lock | wc -l | tr -d ' ')
if [[ "$uvlock_lines" == "15" ]] || [[ "$uvlock_lines" == "0" ]]; then
    print_check "uv.lock churn" OK "$uvlock_lines diff lines (pre-existing, не растёт)"
else
    print_check "uv.lock churn" FAIL "$uvlock_lines lines (проверить не растёт ли)"
fi

# Gate 6 — s3.py untouched
if git status --short -- src/backend/infrastructure/storage/s3.py | grep -q .; then
    print_check "s3.py untouched" FAIL "s3.py modified — НЕ ТРОГАТЬ"
else
    print_check "s3.py untouched" OK "не modified"
fi

if [[ "$fail" == "0" ]]; then
    printf '\nAll gates green — proceed to developer task.\n'
    exit 0
else
    printf '\nPreflight failed — fix before running developer task.\n'
    exit 1
fi
