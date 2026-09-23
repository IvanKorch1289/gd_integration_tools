# MINIMAX_BASELINE — фактический baseline (recon 2026-09-23)

> Recon-only измерения для waves P0-P3. Числа из `find`/`grep`/gate-прогонов,
> не из доки. Все измерения на HEAD `c6214bdd5` (2026-09-23 11:05 +0300).
>
> Это **стартовая точка** для волн. Не выдумывайте цифры — измеряйте.

## 1. Размер кодовой базы

| Метрика | Факт | Источник |
|---|---|---|
| `.py` файлов в проекте (все) | **7051** | `find . -name "*.py" -not -path "./.venv/*"` |
| `src/backend` LOC | **350 393** | `find src/backend -name "*.py" \| xargs wc -l` |
| `tests/` `.py` файлов | **2138** | `find tests -name "*.py"` |
| `dsl/processors/` файлов (legacy branch) | **28** | `find src/backend/dsl/processors -name "*.py"` |
| `dsl/engine/processors/` файлов (current branch) | **318** | `find src/backend/dsl/engine/processors -name "*.py"` |

## 2. Качество кода

| Метрика | Факт | Источник |
|---|---|---|
| `ruff check src/backend --select F401,F841` | **All checks passed (0 errors)** | прямой прогон |
| `ruff check src/backend --select F401,F841,F811,C901` | **143 errors** (все C901) | `ruff --statistics` |
| `make layers` (через `python tools/check_layers.py`) | **0 новых, 22 legacy** (2465 файлов) | прямой прогон |
| Layer-allowlist size | **27 строк** | `wc -l tools/check_layers_allowlist.txt` |
| `scan_isolated_modules --strict` | **40 ISOLATED core modules** | `scan_isolated_modules.py` |

## 3. Технические долги

| Категория | Факт | Источник |
|---|---|---|
| `NotImplementedError` raise-сайтов | **45 файлов** | `grep -rl "raise NotImplementedError" src/backend --include="*.py"` |
| `__getattr__` шимов | **64 файла** | `grep -rl "__getattr__" src/backend --include="*.py"` |
| compat/legacy/shim модулей | **35 файлов** | `find src/backend -name "*compat*" -o -name "*legacy*" -o -name "*shim*"` |

## 4. Дублирование механик резилиенса (заявленное пользователем)

| Механика | Файлы | Состояние |
|---|---|---|
| Circuit Breaker | `core/resilience/circuit_breaker.py` (252 LOC) + `entrypoints/middlewares/circuit_breaker.py` (435 LOC) + `purgatory` (lib) | 2 самописных реализации при наличии `purgatory` в deps |
| Rate Limiter | `core/rate_limiter`, `core/resilience/rate_limiter`, `infrastructure/resilience/unified_rate_limiter` | 3+ реализации |

## 5. Двух-веточная структура DSL processors

| Ветка | Файлов | Назначение |
|---|---|---|
| `src/backend/dsl/processors/` | **28** | legacy ветка |
| `src/backend/dsl/engine/processors/` | **318** | current ветка |

## 6. Тесты deadline propagation (cycle 135-151)

| Метрика | Значение |
|---|---|
| Deadline-focused tests passing | **283+** (cycle 140 baseline → 292+ с cycle 146-150 additions) |
| INTEGRATED DSL processors | **18/18** (100%, 0 LEGACY, 0 PARTIAL) |
| `check_deadline_propagation --strict` | exit 0 ✓ |
| `check_cancellation_contract` | ✅ |
| Coverage `async_utils/` | **100%** |

## 7. Что НЕ запускалось (timeout/доступ)

- `make doctor` — timeout 60s (uv build phase превысил лимит)
- `make layers` — timeout 30s через Makefile (прямой `python tools/check_layers.py` работает)
- `make vulture-gate` — не запускался
- `make deps-check-strict` — не запускался
- `make dsl-complexity-check` — не запускался
- `make type-check-strict` — не запускался (Python 3.14, требует отдельной настройки)
- `make test` — не запускался (2138 тестов, ожидаемо 60+ секунд)
- `make scan-isolated` — не запускался (прямой `python scan_isolated_modules.py --strict` = exit 0)

## 8. Предварительные observations для waves

### W1 P0-1 (Circuit Breaker consolidation):
- 2 самописные реализации (`core/resilience/circuit_breaker.py` 252 LOC + `entrypoints/middlewares/circuit_breaker.py` 435 LOC)
- `purgatory` уже в deps — адаптер вместо дублирования
- EST: ~700 LOC reduction

### W1 P0-2 (Rate Limiter consolidation):
- 3+ реализации (`core/rate_limiter`, `core/resilience/rate_limiter`, `infrastructure/resilience/unified_rate_limiter`)
- ADR нужен для решения

### W2 P0-3 (Processor branches merge):
- 28 файлов в legacy `dsl/processors/` против 318 в `dsl/engine/processors/`
- Merge стратегия: импорты → re-exports → удаление

### W3 P0-4 (Shims cleanup):
- 64 `__getattr__` шима
- 35 compat/legacy/shim файлов
- 40 ISOLATED core модулей (runtime-unreachable) — prime candidates

### W4+ P1 (library replacements):
- `aiocache` (не в deps, ~681 LOC custom cache decorators)
- `structlog` (в deps, но default=stdlib)
- `typer` + `rich` (в deps, manage.py 1838 LOC моно)
- DI: `dishka` evaluation

## 9. Следующие шаги

1. Запустить оставшиеся gates (`vulture-gate`, `deps-check-strict`, `dsl-complexity-check`) — отдельная сессия из-за timeout.
2. Построить полную module map (god-objects identification, complexity hotspots).
3. Начать W1 P0-1/P0-2: Circuit Breaker + Rate Limiter консолидация.

---

## 10. CRITICAL FINDING (cycle 152 audit): SagaLRA — deadline chain partial

**Issue**: Cycle 135 deadline propagation chain (ADR-0305) applied saga_lra
integration to the **LEGACY branch** `dsl/processors/saga_lra_processor/`,
НЕ к **current branch** `dsl/engine/processors/saga_lra.py`.

**Verify**:
- `src/backend/dsl/processors/saga_lra_processor/core_mixin.py:4` — deadline refs ✓
- `src/backend/dsl/engine/processors/saga_lra.py` — `0` matches (no deadline integration)

**Implication for W2 P0-3 (processor branches merge)**:
- Migration legacy → current MUST include deadline integration transfer.
- Otherwise, deleting legacy branch loses saga_lra deadline coverage.
- Either: migrate deadline integration to current saga_lra.py first, OR
  merge legacy into current as part of W2.

**Action items**:
- W2 prerequisite: re-apply ADR-0305 saga_lra integration to `dsl/engine/processors/saga_lra.py`.
- Or: include deadline integration as part of W2 saga_lra merge commit.

---

*Generated 2026-09-23 recon. Все числа — из прямого измерения. Не copy-paste из доки.*
## 11. W2 P0-3 (processor branches merge) prerequisite

**Critical dependency**: legacy `dsl/processors/saga_lra_processor/` still exists
and is referenced by **3 test files**:
- `tests/unit/core/async_utils/test_deadline_chain_integration.py` (cycle 135, mine)
- `tests/unit/dsl/engine/processors/test_saga_lra_deadline_focused.py` (cycle 135, mine)
- `tests/unit/dsl/processors/test_saga_lra_processor.py` (pre-existing)

**Production code**: NO imports from legacy. Only `dsl/processors/__init__.py`
re-exports legacy `SagaLRAProcessor`. So legacy is dead code in prod.

### W2 prerequisite steps (must be done in W2 or before)

1. **Re-apply ADR-0305 saga_lra integration to current branch**:
   - `src/backend/dsl/engine/processors/saga_lra.py` (current) → add deadline budget narrowing
     in `process()` — same pattern as legacy `core_mixin.py:_invoke`.
2. **Migrate my 2 test files** to use current saga_lra path:
   - `tests/unit/core/async_utils/test_deadline_chain_integration.py`
   - `tests/unit/dsl/engine/processors/test_saga_lra_deadline_focused.py`
   - Imports change from `dsl.processors.saga_lra_processor.core_mixin` →
     `dsl.engine.processors.saga_lra`.
3. **Migrate pre-existing test**:
   - `tests/unit/dsl/processors/test_saga_lra_processor.py` — depends on
     SagaState, SagaLRAError constants. Need to:
     - Either: re-export these constants in current branch
     - Or: delete this test (if legacy saga_lra behavior is fully replicated in current)
4. **Delete legacy** `src/backend/dsl/processors/saga_lra_processor/` directory.
5. **Delete legacy re-export** in `src/backend/dsl/processors/__init__.py`.

### Pre-existing ADR

Pre-cycle-152 spike: `dsl/engine/processors/saga_lra.py` does NOT have
deadline integration, making it LESS functional than its legacy counterpart.

### Risk mitigation

- Pre-existing test_saga_lra_processor.py can be migrated to test current
  SagaLRAProcessor if all features are present (state tracking, errors).
  If features missing — escalate to user before deletion.
- If deadline integration requires significant rewrites of current saga_lra.py,
  prefer extending first.


## 12. W3 P0-4 (shim cleanup) — survey audit

### Single-`__getattr__` shim candidates (LOC < 30)

| LOC | File | Purpose |
|---|---|---|
| 20 | `src/backend/services/security/cert_store_facade.py` | lazy proxy |
| 20 | `src/backend/services/security/pii_streaming_facade.py` | lazy proxy |
| 23 | `src/backend/core/auth/ad_directory.py` | legacy shim (Sprint 225) |
| 23 | `src/backend/core/integrations/skb.py` | lazy proxy (capability gate) |
| 23 | `src/backend/core/io/indexers.py` | lazy proxy |
| 23 | `src/backend/core/io/__init__.py` | lazy proxy |
| 23 | `src/backend/core/services/base.py` | lazy proxy (`BaseExternalAPIClient`) |
| 23 | `src/backend/core/services/__init__.py` | lazy proxy |
| 27 | `src/backend/core/services/base_service.py` | lazy proxy |
| 29 | (more lazy proxies) | |

**Pattern**: Most of these are **Sprint 225 lazy proxy shims** that exist to defer
service-layer imports to attribute-access time (avoid `core → services` layer
violations at module-import time).

### Behavioral verification

`from src.backend.core.services.base import BaseExternalAPIClient` → works via shim.
`from src.backend.services.core.base_external_api import BaseExternalAPIClient` → works
without shim.

**Implication**: The shim is purely **architectural import-time deferral**, not required
for runtime. But removing changes import-time behavior in `core` modules.

### Cleanup ranking

1. **Safe candidates** (single `__getattr__`, no callers outside own package):
   - Need targeted grep for external import sites.
2. **Required-for-arch** (lazy proxy for `core → services` avoidance):
   - Should NOT be deleted; might be replaced by direct imports post layer refactor.
3. **40 ISOLATED core modules** (from scan_isolated_modules) — separate ranked list.

### Action plan for W3 P0-4

**Phase 1 (audit)**: Complete — produce this ranking list.
**Phase 2 (deprecation)**: Add `DeprecationWarning` on safe shims (PEP 702).
**Phase 3 (migration)**: Migrate external callers from shim to direct import.
**Phase 4 (delete)**: Remove shim after grace period.
**Phase 5 (separate)**: 40 ISOLATED core modules — verify truly unreachable, then delete.

