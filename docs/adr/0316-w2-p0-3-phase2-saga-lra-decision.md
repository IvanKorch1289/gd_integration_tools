# ADR-0316 — W2 P0-3 Phase 2: SagaLRA — Variant A (migrate legacy mixin-based subpackage) + ADR

- Status: **Accepted** (2026-09-23, cycle 152).
- Связано с: MINIMAX W2 P0-3 (слияние процессоров); ADR-0313 (Phase 1A),
  ADR-0314 (Phase 1B), ADR-0315 (Phase 1C); ADR-0308 (SagaLRA prerequisite).
- Заменяет: SagaLRA как особый случай в W2 P0-3 (другая реализация,
  не дубликат).

## Контекст

W2 P0-3 Phase 1A/1B/1C мигрировали **6 single-file processors + 2 subpackages**
(event_store/, idp_pipeline_processor/). SagaLRA — **особый случай**:

* **`src/backend/dsl/engine/processors/saga_lra.py`** (current) — single-file,
  `BaseProcessor`, simpler state, persistent checkpoints via `_RepoProxy`.
  Deadline integration per ADR-0308 (W2 prerequisite).
* **`src/backend/dsl/processors/saga_lra_processor/`** (legacy, 7 файлов,
  ~1100 LOC) — mixin-based, full state machine с 5 states
  (`STATE_RUNNING/COMPLETED/COMPENSATING/COMPENSATED/FAILED`) +
  `SagaLRAError`/`SagaCompensationError` exceptions + `SagaStepTimeoutError`
  (extends `asyncio.TimeoutError`).

**Cycle 152 recon**:
* External legacy users: `tests/unit/dsl/processors/test_saga_lra_processor.py`
  (37 тестов, используют `SagaCompensationError`, `SagaLRAError`,
  `STATE_*` constants) + `tests/unit/core/async_utils/test_deadline_chain_integration.py`.
* Production users (src/backend): только `dsl/processors/__init__.py` (через
  hub) + cross-imports внутри legacy subpackage.
* `dsl/builders/saga_lra.py` использует **current** `saga_lra.SagaLRAProcessor`
  (production critical path).

**Decision needed**: SagaLRA — **другая реализация**, не дубликат. Нельзя
слепо мигрировать. Нужен decision matrix.

## Decision matrix

| Variant | Описание | Pros | Cons |
|---|---|---|---|
| **A** | Migrate legacy `saga_lra_processor/` subpackage → `engine.processors.saga_lra_processor/` (canonical subpackage). Keep current `saga_lra.py` как separate SagaLRA. | Сохраняет mixin-based API + state machine + exception classes. `test_saga_lra_processor.py` regression-clean. Current `saga_lra.py` остаётся для production. | Два SagaLRA в проекте (current saga_lra.py + canonical saga_lra_processor/) — документация required. |
| B | Deprecate legacy, force-migrate importers → `saga_lra.py`. | Один canonical (current saga_lra.py). Простой. | Ломает `test_saga_lra_processor.py` (37 тестов). Ломает mixin-based extension points. Ломает state machine (current — simpler). |
| C | Coexistence (без migration). | Zero risk. | Не выполняет W2 P0-3 (legacy processors должны быть consolidated). |

**Выбор: Variant A**.

### Why Variant A?

1. **Legacy API шире, чем current**: state machine + 5 state constants +
   `SagaCompensationError` + `SagaState` dataclass. Current не имеет
   этих — миграция на current сломала бы API.
2. **Mixin-based architecture** — позволяет extension (новые mixins
   добавляются без правки `SagaLRAProcessor`). Current single-file
   этого не позволяет.
3. **`test_saga_lra_processor.py` (37 тестов)** привязан к legacy API.
   Variant B сломал бы 37 тестов + соответствующий test coverage.
4. **Current `saga_lra.py` не deprecated** — production critical path
   (`dsl/builders/saga_lra.py`). Оба класса остаются, но с разными
   архитектурами.

## Решение

### Изменения (Phase 2)

1. **Canonical subpackage** создан в
   `src/backend/dsl/engine/processors/saga_lra_processor/` (7 файлов,
   ~1100 LOC).
   - `core_mixin.py` (3): `__init__`, `_set_state`, `_invoke`,
     `SagaStepTimeoutError(asyncio.TimeoutError)`, state constants.
   - `execution_mixin.py` (2): `process`, `to_spec`.
   - `lifecycle_mixin.py` (2): `_run_action`, `_run_compensation`.
   - `serialization_mixin.py` (2): `_normalize_steps`, `_publish_result`.
   - `state.py`: `SagaState`, `SagaLRAError`, `SagaCompensationError`.
   - `_protocol.py`: `_SagaLRAProcessorProtocol`.
   - `__init__.py`: `SagaLRAProcessor(CoreMixin, LifecycleMixin,
     SerializationMixin, ExecutionMixin)` + re-exports.
   - **Internal imports** обновлены (6 файлов): все
     `from src.backend.dsl.processors.saga_lra_processor.X import`
     → `from src.backend.dsl.engine.processors.saga_lra_processor.X import`.

2. **`__all__` в canonical `__init__.py`** расширен: `STATE_COMPENSATED`,
   `STATE_COMPENSATING`, `STATE_COMPLETED`, `STATE_FAILED`,
   `STATE_RUNNING`, `SagaCompensationError`, `SagaLRAError`,
   `SagaLRAProcessor`, `SagaState`, `SagaStepTimeoutError`.

3. **Legacy → re-export shim** в
   `src/backend/dsl/processors/saga_lra_processor/__init__.py` с
   `__getattr__` lazy proxy + DeprecationWarning. Внутренние файлы
   legacy subpackage (`core_mixin.py`, `execution_mixin.py`, etc.)
   оставлены нетронутыми (cross-imports обновлены на engine.processors;
   можно удалить через Phase 3 после telemetry audit).

4. **`src/backend/dsl/processors/__init__.py`** обновлён — импортирует
   `SagaLRAProcessor` и др. из canonical subpackage напрямую (НЕ через
   legacy shim). Hub продолжает экспортировать без DeprecationWarning.

5. **Current `saga_lra.py` НЕ изменён** — он продолжает работать для
   production critical path (`dsl/builders/saga_lra.py`). Deadline
   integration из ADR-0308 сохранён.

### Тесты

**`tests/unit/dsl/processors/test_w2_p0_3_phase2_saga_lra.py`** (13 тестов):
- TestSagaLRACanonicalMigration (10): SagaLRAProcessor + SagaLRAError +
  SagaCompensationError + SagaStepTimeoutError + 5 state constants +
  SagaState identity checks (legacy vs canonical).
- TestSagaLRAMixinArchitecture (1): SagaLRAProcessor MRO contains all 4 mixins.
- TestSagaLRADistinctFromCurrentSagaLRA (1): legacy ≠ current (Variant A
  сохранение обеих реализаций).
- TestDslProcessorsReExportHubSagaLRA (1): hub imports без warning.

### Pre-existing tests regression

```
uv run python -m pytest tests/unit/dsl/processors/test_saga_lra_processor.py
  → 37 passed, 1 warning (DeprecationWarning на legacy shim — expected)
```

## Альтернативы (отклонённые)

* **Variant B (deprecate legacy → current)**: ломает 37 тестов + mixin-based
  extension points + state machine API. Слишком invasive.
* **Variant C (coexistence без migration)**: не выполняет W2 P0-3 DoD
  (legacy processors должны быть consolidated).
* **Merge legacy + current в один файл**: ~1100 LOC single-file,
  architecture drift, потеря mixin decomposition.

## Последствия

**Плюсы**:

* SagaLRAProcessor canonical в `engine.processors.saga_lra_processor/`
  (mixin-based, state machine).
* `test_saga_lra_processor.py` (37 тестов) regression-clean.
* Current `saga_lra.py` сохранён для production critical path —
  никакого breaking change.
* Hub импортирует из canonical напрямую — no DeprecationWarning.

**Минусы / риски**:

* Два SagaLRA класса в проекте (current saga_lra.py + canonical
  saga_lra_processor/) — потенциальная путаница. Documentation в
  `dsl/processors/__init__.py` явно разъясняет разницу.
* Internal cross-imports в canonical обновлены (6 файлов) — но
  семантика идентична.

## Verification (cycle 152)

```
compileall -q src/ extensions/ scripts/ tools/ tests/  → exit 0
uv run python -m pytest tests/unit/dsl/processors/test_w2_p0_3_phase2_saga_lra.py
  → 13 passed
uv run python -m pytest tests/unit/dsl/processors/test_saga_lra_processor.py
  → 37 passed (pre-existing, regression-clean)
uv run python -m pytest tests/unit/dsl/processors/ -q
  → 348 passed, 9 warnings (DeprecationWarning на legacy shim — expected)
ruff check --select F401,F841,F811,E9                   → All checks passed!
```

## Связанные изменения (Phase 2)

* **`src/backend/dsl/engine/processors/saga_lra_processor/`** — canonical
  subpackage (7 файлов, ~1100 LOC).
* **`src/backend/dsl/processors/saga_lra_processor/__init__.py`** — legacy
  shim с `__getattr__` lazy proxy + DeprecationWarning.
* **`src/backend/dsl/processors/__init__.py`** — обновлён: SagaLRA через
  canonical path + 10 дополнительных names в `__all__`.
* **`tests/unit/dsl/processors/test_w2_p0_3_phase2_saga_lra.py`** —
  focused tests (13 тестов).
* **`docs/adr/0316-w2-p0-3-phase2-saga-lra-decision.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0316 зарегистрирован (109 ADRs total).
* **`CHANGELOG.md`** + **`docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W2 P0-3, ADR-0313 (Phase 1A), ADR-0314 (Phase 1B), ADR-0315
(Phase 1C), ADR-0308 (SagaLRA prerequisite), ADR-0316 (this), cycle 152.