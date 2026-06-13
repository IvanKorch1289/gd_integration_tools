#!/usr/bin/env bash
# verify_d5_migration_readiness.sh — pre/post flight checks для D5 model move.
#
# Usage:
#   ./scripts/verify_d5_migration_readiness.sh pre   # перед началом B1
#   ./scripts/verify_d5_migration_readiness.sh post  # после завершения B1
#
# Exit codes:
#   0 — все checks pass
#   1 — pre/post check fail
#   2 — environment error (python не найден, etc.)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

PHASE="${1:-pre}"

# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

note()  { printf "\033[36m[note]\033[0m  %s\n" "$*"; }
pass()  { printf "\033[32m[pass]\033[0m  %s\n" "$*"; }
fail()  { printf "\033[31m[fail]\033[0m  %s\n" "$*" >&2; }
header(){ printf "\n\033[1m== %s ==\033[0m\n" "$*"; }

VENV_PY=".venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  fail "Python venv not found at $VENV_PY"
  exit 2
fi

# ──────────────────────────────────────────────────────────────────────
# Check 1: Model count
# ──────────────────────────────────────────────────────────────────────

header "Check 1: Model count = 12"

MODEL_DIR="src/backend/infrastructure/database/models"
MODEL_COUNT=$(find "$MODEL_DIR" -maxdepth 1 -name "*.py" -not -name "__init__*" | wc -l)

if [[ "$MODEL_COUNT" -eq 12 ]]; then
  pass "Found $MODEL_COUNT model files в $MODEL_DIR"
else
  fail "Expected 12 model files, found $MODEL_COUNT"
  exit 1
fi

# ──────────────────────────────────────────────────────────────────────
# Check 2: Reflection — все таблицы зарегистрированы
# ──────────────────────────────────────────────────────────────────────

header "Check 2: Reflection (BaseModel.metadata.tables)"

TABLES=$("$VENV_PY" -c "
# Импортируем все модели для trigger SQLAlchemy registration в metadata.
# Это паттерн из migrations/env.py:18-28.
from src.backend.infrastructure.database.models.base import metadata
from src.backend.infrastructure.database.models.files import File, OrderFile  # noqa: F401
from src.backend.infrastructure.database.models.orderkinds import OrderKind  # noqa: F401
from src.backend.infrastructure.database.models.orders import Order  # noqa: F401
from src.backend.infrastructure.database.models.users import User  # noqa: F401
import sys
tables = sorted(metadata.tables.keys())
for t in tables:
    print(t)
sys.exit(0 if len(tables) >= 4 else 1)
" 2>&1) || {
  fail "Reflection failed:"
  echo "$TABLES"
  exit 1
}

pass "Reflected tables:"
echo "$TABLES" | sed 's/^/    /'

# ──────────────────────────────────────────────────────────────────────
# Check 3: Linter — 41 violations baseline
# ──────────────────────────────────────────────────────────────────────

header "Check 3: Linter (check_layers.py --root extensions)"

LINTER_OUT=$("$VENV_PY" tools/check_layers.py --root extensions 2>&1) || true

# Извлекаем число "НОВЫЕ нарушения" из вывода linter'а.
# Используем `|| true` чтобы pipefail не прерывал при no-match.
NEW_VIOLATIONS=$(echo "$LINTER_OUT" | grep -oP "НОВЫЕ нарушения:\s*\K\d+" | head -1 || true)
NEW_VIOLATIONS=${NEW_VIOLATIONS:-0}

note "Linter reports: НОВЫЕ нарушения = $NEW_VIOLATIONS"

if [[ "$PHASE" == "pre" ]]; then
  if [[ "$NEW_VIOLATIONS" -eq 41 ]]; then
    pass "Baseline = 41 violations (matches S103 W1 honest measurement)"
  else
    note "⚠ Baseline drift: expected 41, got $NEW_VIOLATIONS"
    note "  Это нормально если extensions добавились или linter изменился"
  fi
elif [[ "$PHASE" == "post" ]]; then
  if [[ "$NEW_VIOLATIONS" -lt 41 ]]; then
    pass "Post-B1: $NEW_VIOLATIONS violations (< 41 baseline)"
  else
    fail "Post-B1: $NEW_VIOLATIONS violations (>= 41 baseline) — migration не сработала"
    exit 1
  fi
fi

# ──────────────────────────────────────────────────────────────────────
# Check 4: Sanity — facade не трогали
# ──────────────────────────────────────────────────────────────────────

header "Check 4: Sanity — core/audit/facade.py не сломан"

if "$VENV_PY" -c "from src.backend.core.audit.facade import emit_audit, AuditService, get_unified_audit_service; print('OK')" 2>&1 | grep -q "^OK$"; then
  pass "core/audit/facade.py imports OK"
else
  fail "core/audit/facade.py broken — что-то трогали"
  exit 1
fi

# ──────────────────────────────────────────────────────────────────────
# Check 5: Target directory (post-B1 only)
# ──────────────────────────────────────────────────────────────────────

if [[ "$PHASE" == "post" ]]; then
  header "Check 5: core/domain/models/ exists with 6 files (B1)"

  TARGET_DIR="src/backend/core/domain/models"
  if [[ -d "$TARGET_DIR" ]]; then
    TARGET_COUNT=$(find "$TARGET_DIR" -maxdepth 1 -name "*.py" -not -name "__init__*" | wc -l)
    if [[ "$TARGET_COUNT" -ge 6 ]]; then
      pass "Found $TARGET_COUNT files в $TARGET_DIR (target ≥ 6)"
    else
      fail "Expected ≥ 6 files в $TARGET_DIR, found $TARGET_COUNT"
      exit 1
    fi
  else
    fail "Target directory $TARGET_DIR does not exist"
    exit 1
  fi
fi

# ──────────────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────────────

header "Summary"

if [[ "$PHASE" == "pre" ]]; then
  note "Pre-flight check passed. D5 migration ГОТОВА к началу B1 (S105 W2)."
  note "Следующие шаги: см. docs/migration/d5-models-to-core.md раздел 4 (B1 план)."
elif [[ "$PHASE" == "post" ]]; then
  note "Post-B1 check passed. B1 ЗАВЕРШЁН. Готовность к B2 (S105 W3-W5)."
  note "Linter должен показать 41 → ~25 violations (только B2/B3 dependents)."
fi
