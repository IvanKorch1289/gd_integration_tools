# ADR-0308 — W2 prerequisite: SagaLRA deadline integration re-apply (current branch)

* Статус: **Accepted** (2026-09-23, cycle 152).
* Связано с: MINIMAX W2 P0-3 (слияние процессоров); ADR-0305 (deadline
  propagation chain); ADR-0304 (fail-closed AST parse).
* Устраняет: SagaLRA Critical Finding (cycle 135 work был только на
  LEGACY `dsl/processors/saga_lra_processor/`, production код использует
  CURRENT `dsl/engine/processors/saga_lra.py`).

## Контекст

Cycle 135 (Phase 1 deadline work) интегрировал ADR-0305 deadline-budget
narrowing в LEGACY saga_lra (`src/backend/dsl/processors/saga_lra_processor/
core_mixin.py:163-204`). Однако production код использует **другой**
модуль — CURRENT saga_lra (`src/backend/dsl/engine/processors/saga_lra.py`,
17.2 KB, 437 строк).

Critical Finding (cycle 152 recon):

* `src/backend/dsl/engine/processors/saga_lra.py`: **0 deadline references**.
* `src/backend/dsl/processors/saga_lra_processor/core_mixin.py`: 8 deadline
  references (уже интегрирован).
* 5 external импортёров current `saga_lra.py`.
* 19 external импортёров legacy `saga_lra_processor/`.

До W2 P0-3 (слияние процессоров + удаление `dsl/processors/`) необходимо:

1. Re-apply ADR-0305 narrowing на current `saga_lra.py`.
2. SagaLRA должен быть INTEGRATED per deadline propagation checker.

## Решение

### Изменения в `src/backend/dsl/engine/processors/saga_lra.py`

1. **Импорты**: добавлены `asyncio` и `inspect` для narrowing helper.

2. **`SagaStepTimeoutError`** (canonical class, дублируется из legacy):
   ```python
   class SagaStepTimeoutError(RuntimeError):
       def __init__(self, message: str, *, step_name: str, kind: str, timeout_s: float) -> None: ...
   ```
   Exposes `step_name`, `kind` (`"action"|"compensation"`), `timeout_s`.

3. **`_run_step_with_deadline(step, exchange, context, *, step_name, kind)`** —
   helper, копирующий семантику из legacy core_mixin:
   * Проверяет `RequestContext.current().deadline_budget.remaining()`.
   * Если `remaining <= 0` → `SagaStepTimeoutError` без await.
   * Иначе `effective_timeout = remaining`.
   * `await asyncio.wait_for(coro, timeout=effective_timeout)`.
   * При `TimeoutError` → `SagaStepTimeoutError`.
   * При недоступности `RequestContext` (ImportError/AttributeError/RuntimeError)
     → graceful fallback к unbounded wait (не ломаем saga-step).

4. **`SagaLRAProcessor.process()`** — два места обёрнуты:
   * `await step.forward.process(exchange, context)` → `await self._run_step_with_deadline(step.forward, ..., kind="action")`
   * `await comp_step.compensate.process(exchange, context)` (compensation
     path) → `await self._run_step_with_deadline(comp_step.compensate, ..., kind="compensation")`.

### Compromise: in-memory fallback не narrowing

SagaLRA.process использует `_run_step_with_deadline` **только в persistent
path** (когда `_get_repo()` вернул не None). In-memory fallback (repo=None)
НЕ narrowing — by design (cycle 19 P1.4: graceful degradation без БД).
Это явно зафиксировано в docstring SagaLRA + в unit-тесте
`test_no_budget_means_unbounded`.

### Тесты

* `tests/unit/dsl/engine/processors/test_saga_lra_deadline_focused.py`
  (13 tests, все passing):
    1. `TestSagaStepTimeoutError` — construction + attributes (3 теста).
    2. `TestRunStepWithDeadlineNarrowing` — narrowing via DeadlineBudget
       (5 тестов: no budget / expired / narrowed / within budget / import-error fallback).
    3. `TestRunStepWithDeadlineSyncCallables` — sync pass-through (1 тест).
    4. `TestSagaLRAProcessDeadlineIntegration` — in-memory smoke-test (1 тест).
    5. `TestSagaLRAPropagationChecker` — static + CLI classification (2 теста).
    6. `TestSagaLRACompensationDeadlineWiring` — compensation kind in error (1 тест).

### Verification

```
python3.14 -m pytest tests/unit/dsl/engine/processors/test_saga_lra_deadline_focused.py -q
  → 13 passed in 1.01s

python3.14 tools/checks/check_deadline_propagation.py
  → saga_lra.py:497 (narrowing) → INTEGRATED

python3.14 -m compileall -q src/ extensions/ scripts/ tools/ tests/  → exit 0
python3.14 tools/checks/check_python3_syntax.py --root src/backend    → exit 0
ruff check ... --select F401,F841,F811,E9                             → All checks passed!
```

## Последствия

**Плюсы**:

* SagaLRA Critical Finding устранён — current branch теперь INTEGRATED.
* W2 P0-3 (слияние процессоров) больше не blocked deadline-разрывом.
* Новая публичная exception `SagaStepTimeoutError` доступна для
  downstream tests / observability.
* Helper graceful fallback: если `RequestContext` недоступен, поведение
  идентично pre-ADR-0305 (unbounded wait) — backward-compatible.

**Минусы / риски**:

* SagaStepTimeoutError дублируется между current и legacy. После W2
  (когда `dsl/processors/` будет удалён) дубликат исчезнет.
* In-memory fallback path не narrowing — но это documented design choice,
  не bug.

## Связанные изменения

* **`src/backend/dsl/engine/processors/saga_lra.py`** — SagaStepTimeoutError
  + _run_step_with_deadline + 3 call-sites (forward, compensation x2).
* **`tests/unit/dsl/engine/processors/test_saga_lra_deadline_focused.py`**
  (новый, ~360 строк, 13 тестов).
* **`docs/adr/INDEX.md`** — ADR-0308 зарегистрирован (101 ADRs total).
* **`CHANGELOG.md`** — запись цикла 152.
* **`docs/roadmap/PROGRESS_LEDGER.md`** — wave-memo для cycle 152.

Refs: MINIMAX W2 P0-3 (prerequisite), ADR-0305 deadline chain, ADR-0304
fail-closed AST, SagaLRA Critical Finding (cycle 152 recon).