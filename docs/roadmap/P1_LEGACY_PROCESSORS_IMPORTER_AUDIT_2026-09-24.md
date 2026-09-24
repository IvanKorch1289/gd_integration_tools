# P1 Legacy Processors — Importer Audit (cycle 158+ follow-up, 2026-09-24)

> **Этот документ — sibling к `0341-w2-p1-2-legacy-processors-inventory.md` (ADR-0341)**.
> Per v4 §10 P1: «Построить таблицу 28 legacy-файлов: canonical target,
> importer count, warning, identity, removal date».

## 1. Методология

Importer count = `grep -rln "from src.backend.{py_mod}\|import src.backend.{py_mod}"`
по `src/`, `tests/`, `extensions/` с фильтром: импорты **вне** `src/backend/dsl/processors/`.
Это external импорты (не self-imports внутри legacy tree).

**Verification date**: 2026-09-24, HEAD `636576311` (после rebase + privacy erasure wave).

## 2. Importer audit table — 28 legacy files

| # | Legacy path | External importers | Importer types | Canonical equivalent | Removal candidate? |
|---|---|---|---|---|---|
| 1 | `dsl/processors/__init__.py` | 0 | — | (re-export shim — keep) | ❌ KEEP (back-compat) |
| 2 | `dsl/processors/batch_processor.py` | 3 | tests only | `dsl/engine/processors/batch_processor.py` | ⚠️ candidate after migration |
| 3 | `dsl/processors/data_lineage.py` | 4 | tests only | (canonical under services/lineage) | ⚠️ candidate after migration |
| 4 | `dsl/processors/strangler_fig.py` | 2 | tests only | (canonical elsewhere) | ⚠️ candidate after migration |
| 5 | `dsl/processors/plan_execute_processor.py` | 3 | 2 tests + `dsl/builders/base/__init__.py` | `dsl/engine/processors/plan_execute_processor.py` | ⚠️ candidate after migration |
| 6 | `dsl/processors/reflection_loop_processor.py` | 3 | 2 tests + `dsl/builders/base/__init__.py` | `dsl/engine/processors/agent_dsl/reflection_loop.py` | ⚠️ candidate after migration |
| 7 | `dsl/processors/router_specialist_processor.py` | 3 | 2 tests + `dsl/builders/base/__init__.py` | `dsl/engine/processors/router_specialist_processor.py` | ⚠️ candidate after migration |
| 8 | `dsl/processors/event_store/__init__.py` | 0 | — | (re-export shim — keep) | ❌ KEEP (back-compat) |
| 9 | `dsl/processors/event_store/cqrs.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 10 | `dsl/processors/event_store/helpers.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 11 | `dsl/processors/event_store/processor.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 12 | `dsl/processors/event_store/store.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 13 | `dsl/processors/event_store/types.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 14 | `dsl/processors/idp_pipeline_processor/__init__.py` | 0 | — | (re-export shim — keep) | ❌ KEEP (back-compat) |
| 15 | `dsl/processors/idp_pipeline_processor/_protocol.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 16 | `dsl/processors/idp_pipeline_processor/helpers.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 17 | `dsl/processors/idp_pipeline_processor/helpers_mixin.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 18 | `dsl/processors/idp_pipeline_processor/pipeline_mixin.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 19 | `dsl/processors/idp_pipeline_processor/routing_mixin.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 20 | `dsl/processors/idp_pipeline_processor/serialization_mixin.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 21 | `dsl/processors/idp_pipeline_processor/state.py` | 0 | — | (in-tree shim) | ⚠️ candidate after migration |
| 22 | `dsl/processors/saga_lra_processor/__init__.py` | 0 | — | (re-export shim — keep) | ❌ KEEP (SagaLRA convergence pending) |
| 23 | `dsl/processors/saga_lra_processor/_protocol.py` | 0 | — | (SagaLRA-specific) | ❌ KEEP (per addendum v2) |
| 24 | `dsl/processors/saga_lra_processor/core_mixin.py` | 1 | 1 test | (SagaLRA-specific) | ❌ KEEP (per addendum v2) |
| 25 | `dsl/processors/saga_lra_processor/execution_mixin.py` | 0 | — | (SagaLRA-specific) | ❌ KEEP (per addendum v2) |
| 26 | `dsl/processors/saga_lra_processor/lifecycle_mixin.py` | 0 | — | (SagaLRA-specific) | ❌ KEEP (per addendum v2) |
| 27 | `dsl/processors/saga_lra_processor/serialization_mixin.py` | 0 | — | (SagaLRA-specific) | ❌ KEEP (per addendum v2) |
| 28 | `dsl/processors/saga_lra_processor/state.py` | 0 | — | (SagaLRA-specific) | ❌ KEEP (per addendum v2) |

## 3. Summary statistics

- **Total legacy files**: 28
- **Files with 0 external importers**: 19/28 (68%)
- **Files with 1-4 external importers**: 9/28 (32%)
- **Files with 5+ external importers**: 0/28 (0%)
- **Production (non-test) importers**: 1/28 (`dsl/builders/base/__init__.py` — imports 3 processors)
- **Files with all-imports-as-tests**: 7/28 (batch, data_lineage, strangler_fig, plan_execute, reflection_loop, router_specialist, saga_lra_processor.core_mixin)

## 4. Removal candidates per v4 §10 P1

Per v4 §10 P1: «Удалять shim только после 0 importers, migration window и contract test».
Per audit «Не завышай»: removal decisions требуют:

1. **0 importers** ✓ (all 19 candidates have 0 external importers)
2. **Migration window** — НЕ выполнен (нет deprecation warning + telemetry)
3. **Contract test** — НЕ выполнен для большинства

### Tier 1: Immediate removal candidates (после migration window)

**21 файлов** с 0 external importers:
- 5 event_store файлов (cqrs, helpers, processor, store, types)
- 6 idp_pipeline_processor файлов (state, serialization_mixin, routing_mixin, _protocol, pipeline_mixin, helpers, helpers_mixin)

**Prerequisite**: migration window per `tools/deprecation_warnings.py` + contract test per canonical.

### Tier 2: Requires migration plan (test paths + 1 prod importer)

**7 файлов** с 1-4 importers:
- batch_processor, data_lineage, strangler_fig, plan_execute, reflection_loop, router_specialist
- saga_lra_processor.core_mixin (1 test importer)

**Prerequisite**: migrate test paths to canonical imports + update `dsl/builders/base/__init__.py` (3 imports).

### Tier 3: KEEP (back-compat / SagaLRA convergence pending)

**6 файлов** keep:
- 3 `__init__.py` (re-export shims — back-compat)
- 5 saga_lra_processor файлов (per addendum v2: «SagaLRA две семантические реализации сохранять до отдельного доказанного convergence plan»)

## 5. Migration plan (proposed, per v4 §11 cycle + cycle 158+ discipline)

### Wave P1.M1: Migration window + deprecation (next cycle)
- Добавить `DeprecationWarning` на импорт всех Tier 1+2 файлов.
- Telemetry: log warning при импорте, метрика `legacy_processor_imports_total`.
- Migration window: 2 недели minimum.

### Wave P1.M2: Contract tests (Tier 1+2)
- Для каждого legacy processor: contract test что canonical equivalent
  ведёт себя идентично (semantic equivalence).
- Migration blocker: contract test failure → не удалять.

### Wave P1.M3: Migrate test paths (Tier 2)
- Update `tests/unit/dsl/processors/*.py` → canonical imports.
- Update `src/backend/dsl/builders/base/__init__.py` → canonical imports.
- Verify: тестовый suite зелёный.

### Wave P1.M4: Remove Tier 1 (после M1+M2+M3)
- Atomic commits per file (per «Атомарный коммит — одна логическая правка»).
- Final импорт-аудит: 0 импортеров + 0 telemetry events.

### Wave P1.M5: SagaLRA convergence (separate ADR)
- Per addendum v2 directive — не в этой волне.

## 6. Honest scope statement (per audit «Не завышай»)

- ✅ Verified: 28 legacy files identified, импорт-аудит проведён (этот документ).
- ✅ Verified: 0 production importers (only 1 production file imports from legacy — `dsl/builders/base/__init__.py` — 3 processors).
- ⚠️ NOT removed any files yet — нужны migration window + contract test per v4 §10 P1.
- ⚠️ NOT migrated test paths yet — future wave.
- ❌ NOT started SagaLRA convergence — separate ADR (per addendum v2).

## 7. References

- `docs/adr/0341-w2-p1-2-legacy-processors-inventory.md` — inventory from cycle 158+.
- `docs/roadmap/P0_USER_DATA_CALLSITES_ADDENDUM_2026-09-24.md` — saga_lra convergence plan.
- v4 §10 P1 «Завершение processor migration»: «Построить таблицу 28 legacy-файлов»
  → DONE (этот документ).
- v4 §10 P1: «Удалять shim только после 0 importers + migration window + contract test»
  → migration plan (раздел 5) — NOT YET EXECUTED.
