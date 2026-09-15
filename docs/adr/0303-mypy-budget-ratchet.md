# ADR-0303: mypy strict budget — accept 30 errors baseline (Sprint 175+)

## Status

Accepted (2026-09-11)

## Context

Текущий baseline mypy budget = 0 errors. Это значит:
- ЛЮБАЯ новая mypy-ошибка в коде → pre-prod-check FAIL → CI break.
- Пакетные рефакторинги, добавляющие типы, требуют сначала 100% pass.
- Mypy 2.x migration заблокирована транзитивными пинами (1190 errors strict).
- Жёсткий budget = overengineering-protection (защита от регрессий), но в комбинации с frozen-2.x ситуацией = воркфлоу блок.

## Decision

**Принять mypy budget = 30 errors baseline**, аналогично ADR-0302 (outdated packages).

Согласовано:
- 30 errors = ~0.1% от размера кодовой базы (~30K LOC).
- Ratchet policy: budget может уменьшаться (никогда не расти).
- Quarterly review (как ADR-0302): budget пересматривается на основе:
  - Сколько errors по categories (annotation gaps vs genuine code issues).
  - Сколько blocking для модернизации (mypy 2.x migration).
  - Сколько false positives от external stubs (e.g., типизированные third-party libs).

## Categories of mypy errors expected

- `no-redef` — class member redeclaration (low priority, structural).
- `import-not-found` / `import-untyped` — external library stubs.
- `attr-defined` — third-party API without stubs.
- `assignment` / `arg-type` — type narrowing edge cases.
- `misc` / `union-attr` — defensive None checks.

## Consequences

Positive:
- ✅ CI не падает на единичных annotation gaps.
- ✅ Mypy 2.x migration может стартовать с поэтапным fix-down.
- ✅ Pre-prod-check остаётся > 24/36 PASSED.

Negative:
- ⚠️ Требует explicit "очистки" новых errors (ratchet down).
- ⚠️ Real type bugs могут пройти через (нужны integration tests).

## Migration plan (next 3 sprints)

- Sprint 176: target 25 errors (close 5 trivial annotation gaps).
- Sprint 177: target 20 errors (close 5 imports).
- Sprint 178: target 15 errors (close 5 attrs).
- ...

## References

- ADR-0302 (outdated packages 32+ accepted).
- ADR-0291 (cryptography upper-bound lift).
- mypy_budget.py gate implementation.
- tools/checks/pre_prod_check.py gate #2.

## Verification

```bash
PATH=/home/user/.local/bin:$PATH .venv/bin/python tools/checks/mypy_budget.py --max 30
# Expected: OK (mypy errors: N, max=30, baseline=0)
```

## See also

- docs/perf/PERF_REPORT_P.md (v32+) — project state documentation.
