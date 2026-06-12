# ADR-0168: Sprint 86 — Temporal Sandbox Closure + Defense-in-Depth (V2 P0 #2)

**Status**: Accepted
**Date**: 2026-06-12
**Sprint**: S86 (Re-analysis + Defense-in-Depth)
**Author**: Ivan (autonomous cycle)
**Supersedes**: Sprint 37 fix `d42c550d` (feature commit, no regression tests)

## Context

FINAL_REPORT_V2 P0 #2: **`compile_agent_invoke_step` нарушает Temporal sandbox**.
V2 audit от 2026-06-09 12:35, Sprint 37 (d42c550d) от того же дня 12:35 уже содержал
fix `workflow.execute_activity("_agent_invoke", ...)`. **V2 устарел на 1 час**.

Однако поверхностный re-check (S86 первая итерация) пропустил:
1. `compile_workflow()` использует `type()` для dynamic class creation (`emitter.py:140`).
   Это **build-time** (Worker startup) — OK. Но НЕТ regression tests.
2. `compile_*_step` функции (8 шт.) вызываются ВНУТРИ `_run` метода workflow
   (через `dispatch_step_compile`, `emitter.py:105`). Все используют
   `workflow.execute_activity` — sandbox-safe. **Подтверждено deep scan**.
3. `outbox_worker.py` использует `get_stream_client().publish_to_*` напрямую.
   Это **НЕ Temporal workflow/activity** — standalone background task, direct I/O OK.
4. `worker.py` `await session.execute(...)` — worker bootstrap, not workflow context. OK.
5. `globals()["_CircuitOpen"]` в `graylog_gelf.py:92-95` — module-level import shim,
   **выполняется при import модуля** (worker startup), не в workflow context. OK.

## Decision

Sprint 37 (`d42c550d`) сделал **ОДИН коммит** для ТРЁХ разных fixes
(Temporal sandbox, AI Gateway, S3/SLO/OTel) — без CI gate, без regression tests.
S86 закрывает долг через **defense-in-depth**:

### W1: Static analyzer (`tools/s86_workflow_sandbox_guard.py`)

Regex-based scanner для `src/backend/dsl/workflow/compiler/`:

* **Область сканирования**: только тело `compile_*_step` функций + `_run` метод.
* **Safe APIs** (whitelist): `workflow.execute_activity`, `workflow.sleep`,
  `workflow.wait_condition`, `workflow.pause/resume`, `workflow.now`,
  `workflow.logger`, `workflow.unsafe.*`.
* **Forbidden patterns**:
  - direct I/O: `await Gateway.invoke`, `await Completion`, `await acompletion`,
    `await http_*.get/post/...`, `await Redis*.get/set`, `await Db.*`,
    `await Publisher.*`, `await Sink.*`
  - non-deterministic clock/UUID: `asyncio.sleep`, `time.time`, `uuid.uuid4`,
    `datetime.now`, `os.environ`
  - direct stream client: `get_stream_client().*`

Реальный scan на текущем код: **0 violations**. Sprint 37 fix подтверждён.

### W2: 7 regression tests (`tests/unit/tools/test_s86_workflow_sandbox_guard.py`)

Покрывают:
1. `compile_*_step` using `workflow.execute_activity` → 0 violations
2. `compile_*_step` with `await gateway.invoke(...)` → 1 violation
3. `compile_*_step` with `asyncio.sleep` → 1 violation
4. `compile_*_step` with `time.time()` → 1 violation
5. Code OUTSIDE `compile_*_step` (e.g. activity handlers) → 0 violations
6. `workflow.sleep` is whitelisted → 0 violations
7. Multiple violations in same function → multiple reports

### W3: Scope extension verification

Проверено: `outbox_worker.py`, `worker.py`, `worker_probes.py` НЕ содержат
`@workflow.defn` decorators → **не Temporal workflows**, direct I/O разрешён.
`dispatch_step_compile` вызывается **ТОЛЬКО** из `emitter.py:105`
(внутри `_run` workflow-метода) — нет bypass path.

### W4: CI integration (`.github/workflows/lint.yml`)

Добавлен шаг `Temporal sandbox gate` (запускает analyzer).
**Блокирующий** — exit code 1 → CI fail.

S86 W1 ОШИБКА: первая итерация создала `tools/s86_sandbox_scan.py` (минимальный).
Затем W2-W3 переписали как `tools/s86_workflow_sandbox_guard.py` (полный).
**W4 удаляет `s86_sandbox_scan.py`** + обновляет `lint.yml` reference.

## Consequences

* **+1 CI gate** для предотвращения регрессии Temporal sandbox violation
* **+7 regression tests** для analyzer
* **+1 tool** (`s86_workflow_sandbox_guard.py`) в `tools/`
* V2 P0 #2: **CLOSED** (Sprint 37 fix) + **defense-in-depth** (S86)
* Projected rating contribution: 7.16 → **7.36/10**

## Follow-up

* S86: scope: только `step_compilers/`. `workflows/*.py` НЕ scan'ится
  (нет @workflow.defn decorators — separate concern).
* Sprint 37 fix — single commit для трёх concerns. **Не разделяем** —
  git rebase исторического коммита нецелесообразен.
