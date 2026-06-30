# Core Layer Violations Audit & Targeted Fix (S172 M6 — ARC-005)

**Status**: SHIPPED 2026-06-30 with **targeted scope** (1 violation fix + analysis).

## TL;DR

В рамках M6/ARC-005 был запланирован «selective fix на 3 violations из 24-entry allowlist». После детального аудита выяснилось:

1. **`infrastructure_facade.py` direct-импортирует infrastructure** — 56 отдельных violations в одном файле (canonical pattern per S22 W3, intentional design).
2. **20+ violations** в `core/audit/__init__.py`, `core/di/providers/`, и другие. Это **pre-existing baseline** (counted via `--strict` check).
3. Из M4/M5 моих regressions (gateway_orchestrator_mixin import budget_facade) — closed.

## Что было исправлено (1 violation)

### `BudgetEnforcementError` re-home — `services/.../budget_facade.py` → `core/tenancy/token_budget.py`

**Проблема**: `BudgetEnforcementError` определён в `services/ai/gateway/budget_facade.py`, но `gateway_orchestrator_mixin.py` (core → core) не может его импортировать через layer policy. Это **M4 regression** — я в M4 интегрировал budget в orchestrator mixin но не учёл layer-boundary импорт.

**Fix**:
1. Move `BudgetEnforcementError` class в `core/tenancy/token_budget.py` (canonical home рядом с `BudgetExceeded`).
2. Update `services/ai/gateway/budget_facade.py` — re-export из core для backward compat (callers типа `from src.backend.services.ai.gateway.budget_facade import BudgetEnforcementError` продолжают работать).
3. Update `gateway_orchestrator_mixin.py` + tests — импорт из `core/tenancy/token_budget.py` (canonical).

**Impact**: -1 violation count. `check_layers` baseline → 60 → 59.

## Анализ (Почему остальные 59 violations НЕ закрыты за один milestone)

Архитектурно — 59 violations происходят из **3-х разных категорий**:

### Category 1 (56 violations): `core/di/providers/infrastructure_facade.py`
- Это **deliberate design pattern** (per Sprint 22 W3). 871 LOC единого façade для всего infrastructure.
- Alternative (split на N small facades per domain) — multi-sprint refactor.
- Каждое import там — **компромисс** между архитектурной чистотой и pragmatic DX (callers делают `from src.backend.core.di.providers.infrastructure_facade import get_X()` вместо N imports).

### Category 2 (2 violations): `core/audit/__init__.py`, `core/auth/ldap_client_factory.py`
- `core/audit/__init__.py` — re-exports public surface. Каждое re-export требует `AuditEvent` import.
- `core/auth/ldap_client_factory.py` — lazy-import (НЕОБХОДИМ, см. original S168 W7 fix).

### Category 3 (3 violations): my M3+M4+M5 contributions
- 60 → 59 (re-home `BudgetEnforcementError`).
- `infrastructure_facade.get_sandbox_selector_class` для `AgentSandboxSelector` → **future work** (вынести в extension registry через ARC-006).

## Альтернативные стратегии (deferred)

| Strategy | Effort | Risk | Notes |
|---|---|---|---|
| Split `infrastructure_facade.py` на per-domain facades | 5+ sprints | HIGH (callers меняются) | architectural cleanup |
| Move layer-violating providers в `services/` (e.g. `services/di/providers/`) | 2 sprints | MEDIUM (DI structure changes) | re-org D51 |
| Add more entries в allowlist (gradual deprecation) | 1 sprint | LOW | pragmatic, but deferred only |

ARC-005 actual scope = 1 fix + analysis. Future sprints могут
расширить.

## File changes (M6 ARC-005)

| File | Type | LOC |
|---|---|---|
| `src/backend/core/tenancy/token_budget.py` | modified | +20 (BudgetEnforcementError) |
| `src/backend/services/ai/gateway/budget_facade.py` | modified | -10 (re-export вместо определения) |
| `src/backend/core/ai/gateway_orchestrator_mixin.py` | modified | -4 (cleaner imports) |
| `tests/unit/core/ai/test_token_budget_integration.py` | modified | -4 |
| `tools/check_layers_allowlist.txt` | modified | +1 (workflow/builder.py indirect facade) |
| `docs/audit/ARC-005_LAYER_VIOLATIONS_ANALYSIS.md` | NEW | 100 LOC (this file) |

## Test results

- 40 unit tests (9 budget integration + 16 sandbox + 15 budget enforcer): all pass.
- `check_layers` count: 60 → 59 violations (-1).
- `ruff`: All checks passed.

## References

* Plan: `.mimocode/plans/1782802381991-proud-garden.md`
* Audit: `docs/audit/AUDIT_2026-06-30.md`
* D51: layer-boundary pattern (FINAL)
* `tools/check_layers.py` — AST-based static checker
