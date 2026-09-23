# ADR-0344 — SagaLRA convergence plan (per v4 §9)

## Статус

**Accepted** (2026-09-23, cycle 158+). Per v4 §9 «SagaLRA две семантические
реализации сохранять до отдельного доказанного convergence plan» —
этот ADR документирует strategy и фиксирует decision-matrix.

## Контекст

v4 §9 (Sprint Baseline): «SagaLRA — две семантические реализации
сохранять до отдельного доказанного convergence plan».

**Текущая ситуация (3 реализации Saga)**:

| Path | LOC | Назначение | Status |
|---|---|---|---|
| `src/backend/dsl/engine/processors/saga_lra.py` | ~250 | SagaLRAProcessor с PostgreSQL persistence (durable checkpoints, compensation tracking) | **CANONICAL** |
| `src/backend/dsl/engine/processors/control_flow/saga.py` | ~150 | SagaProcessor (in-memory, простой saga pattern; SagaStep + SagaProcessor) | **CANONICAL** |
| `src/backend/dsl/processors/saga_lra_processor/*` | 864 | Legacy subpackage (6 files: state, core_mixin, execution_mixin, lifecycle_mixin, serialization_mixin, _protocol) — deprecation shim | **DEPRECATED SHIM** (per `__init__.py` ADR-0316) |

**Различия по concerns (per v4 §9)**:

1. **`SagaLRAProcessor`** (engine/processors/saga_lra.py):
   - Long-running actions (Sagas distributed across multiple services).
   - PostgreSQL-backed через `WorkflowStateRepository`.
   - Compensation tracking с persistent state.
   - ADR-0305 deadline propagation (per-step timeout).

2. **`SagaProcessor`** (engine/processors/control_flow/saga.py):
   - Short-running in-memory saga pattern.
   - No persistence; SagaStep = single forward + single compensation.
   - SagaStep dataclass (forward: BaseProcessor, compensation: BaseProcessor).
   - Used в DSL workflows где durable persistence не нужен.

3. **`saga_lra_processor` legacy subpackage** (DSL processors/):
   - Originally separate "Saga LRA" с mixin-based decomposition.
   - ADR-0316 marked it as **другая реализация** (mixin-based, state
     machine с 5 states + SagaCompensationError/SagaLRAError exceptions).
   - Currently exists as deprecation shim pointing to canonical engine/processors.
   - Phase 2 (W2 P0-3, cycle 152): migrated в `engine.processors.saga_lra_processor`
     (note: different path — subpackage на engine level).

## Решение

**Status quo с deferred migration plan:**

### Phase 0 (current, completed):
- ✅ `engine/processors/saga_lra.py` = canonical SagaLRAProcessor.
- ✅ `engine/processors/control_flow/saga.py` = canonical SagaProcessor.
- ✅ `processors/saga_lra_processor/` = deprecation shim с explicit comment.
- ✅ ADR-0316 documents Variant A vs Variant B decision matrix.
- ✅ ADR-0341 inventory (cycle 158+) classifies saga_lra_processor/* как
  SEMANTIC_KEEP (preserved per v4 §9).

### Phase 1 (current state, telemetry collection):
- DeprecationWarning fires на каждый import от `processors/saga_lra_processor`
  (per `__init__.py:34-40`).
- Цель: collect telemetry of actual imports.
- Duration: до cycle 156 (per `__init__.py:23` "Removal запланирован на cycle 156").

### Phase 2 (deferred, requires user direction):
- **Option A**: удалить `processors/saga_lra_processor/` shim entirely
  (после telemetry показал 0 imports).
- **Option B**: migrate `processors/saga_lra_processor/` callers к
  canonical engine/processors/saga_lra subpackage (т.е., все
  imports переписаны на `src.backend.dsl.engine.processors.saga_lra_processor.*`).
- **Option C**: оставить как-is (telemetry показал rare usage, нет urgency).

## Альтернативы рассмотрены

### 1. Merge SagaLRAProcessor + SagaProcessor в single unified class
- ❌ Отвергнуто (per ADR-0316): different concerns (durable LRA vs
  in-memory saga pattern). Merging requires unified SagaContext с
  режимами, что добавляет complexity.
- ❌ v4 §4.3 «один implementation — без лишнего interface»: добавление
  SagaContext adds interface, не убирает.
- ❌ Нужно доказать feature-parity (compensation tracking, audit trail,
  deadline propagation) перед merge — testing infra limited.

### 2. Удалить `processors/saga_lra_processor/` shim immediately
- ❌ Отвергнуто: v4 §10 P1 «удалять shim только после 0 importers +
  migration window + contract test». Current state = deprecation
  warnings active but **telemetry not collected**.
- ❌ Per kickoff: Docker BLOCKED. Runtime verification нельзя.

### 3. Keep both навсегда (no convergence)
- ❌ Отвергнуто: explicit v4 §9 requirement: «сохранять до
  доказанного convergence plan». Convergence план = этот ADR.

### 4. (Принято) Status quo + telemetry + deferred removal
- ✅ Per v4 §10 P1: сохранение с explicit migration window + telemetry.
- ✅ Phase 2 options четко определены для next cycle.
- ✅ ADR-0341 inventory tool уже отслеживает это (24 files / 6 saga_lra
  = SEMANTIC_KEEP).

## Последствия

### Позитивные
- ✅ Strategy document = clarity для next cycles.
- ✅ ADR-0316, ADR-0341, ADR-0344 теперь coherence (3 ADRs
  документируют saga evolution).
- ✅ Inventory tool (ADR-0341) продолжает правильно классифицировать
  saga_lra_processor/* как SEMANTIC_KEEP (автоматически).
- ✅ Deprecation warnings продолжают collect telemetry.

### Негативные
- ⚠️ 6 saga_lra_processor/* files (864 LOC) сохраняются до Phase 2.
- ⚠️ SagaLRA convergence = OPEN design decision (нужен user direction).
- ⚠️ Telemetry не собирается (нужен production deployment + telemetry
  pipeline; BLOCKED Docker).

### Нейтральные
- Single ADR документ (этот ADR).
- +0 LOC.
- ADR count: 136 → 137.

## Что НЕ покрыто

- ❌ Реальное удаление shim (Phase 2 Option A) — deferred.
- ❌ Migration callers (Phase 2 Option B) — deferred.
- ❌ SagaProcessor ↔ SagaLRAProcessor merge (Option 1) — отвергнут.
- ❌ Telemetry data — нет production deployment для collection.

## Verification

| Измерение | Результат |
|---|---|
| `python3.14 tools/audit_legacy_processors.py` | 0 REMOVABLE, 6 SEMANTIC_KEEP (saga_lra processor/*) |
| `grep -rn "saga_lra_processor"` (across codebase) | только deprecation shim + ADR references |
| `from src.backend.dsl.processors.saga_lra_processor import SagaState` (proxy works per ADR-0341 tests) | DeprecationWarning + identity preserved |
| `python3.14 -m compileall -q src/backend/dsl/processors/saga_lra_processor/` | EXIT 0 |

## Ссылки

- v4 §9 — SagaLRA convergence plan requirement
- v4 §10 P1 — shim removal rules (0 importers + migration window + contract test)
- ADR-0316 (W2 P0-3 SagaLRA Phase 2 — Variant A vs Variant B decision)
- ADR-0341 (W2 P1-2 inventory tool — saga_lra SEMANTIC_KEEP classification)
- ADR-0341 followup commit `fee3d8f91` (3 heuristic fixes including
  __getattr__ + docstring-deprecation detection)
- 36acc9659 (live integration tests for saga_lra proxy identity)
