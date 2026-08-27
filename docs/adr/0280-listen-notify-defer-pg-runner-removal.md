# ADR-0280: LISTEN/NOTIFY для workflow events — defer до S220+ (pg-runner removal)

> **Status**: PROPOSED (2026-08-27).
> **Method**: evidence-based deferral — pg-runner backend DEPRECATED.
> **Scope**: P2.14 из WAVE 2 production-grade plan (см.
> `docs/analysis/SPRINT_32_GAP_ANALYSIS_2026-08-27.md`).
> **Date**: 2026-08-27.

## 0. Контекст

WAVE 2 verification (`CURRENT_STATE_2026-08-27.md`) зафиксировал **P2.14** как
OPEN: `pg_runner.await_completion` использует polling с exponential backoff,
asyncpg поддерживает LISTEN/NOTIFY, но `await_completion` его не использует.

WAVE 2 gap analysis (`SPRINT_32_GAP_ANALYSIS_2026-08-27.md §4.1`) обнаружил
критический контекст, который делает оригинальный план **waste of work**:

`src/backend/infrastructure/workflow/pg_runner_backend.py:75-79` (verified 2026-08-27):

```
DEPRECATED since Sprint 217 (2026-08-17). pg-runner backend
deprecated entirely — production callers must migrate to
TemporalWorkflowBackend. This method will be removed in Sprint 220+.
```

Аналогичные `.. deprecated::` аннотации на строках 201-204 (`await_completion`)
и 252-255 (`replay`).

**Production backend** (`temporal_backend.py:240-273`) уже НЕ использует polling —
делает `handle.result()` (native Temporal). LISTEN/NOTIFY там не применим —
Temporal уже push-based.

## 1. Проблема

Наивная реализация LISTEN/NOTIFY в `pg_runner.await_completion`:
- **Wasted**: ~80 LOC, ~4-6 тестов, ~1 день — backend удаляется в S220+
  (через ~2-3 sprint'а).
- **Wrong target**: production уже на Temporal — push-based через Temporal SDK.

## 2. Рассмотренные варианты

### Вариант A: Наивная реализация в `pg_runner.await_completion`

**Pros**: simple, ~80 LOC.
**Cons**: backend удаляется в S220+ — work теряется. Также не нужен
production — Temporal уже там.

**VERDICT**: ❌ DEFER.

### Вариант B: Listenable CDC subscriber для external subscribers

`infrastructure/cdc/listen_notify_backend.py:37` уже scaffold. Реальная
имплементация для dashboard/alerts.

**Pros**: useful для external (dashboards, alerts), not for internal
`await_completion`.
**Cons**: multi-sprint effort (~80 LOC + Wave R3 имплементация); CDC scope,
не workflow scope.

**VERDICT**: ⚠️ Только если S172-S173 budget.

### Вариант C: ADR-only defer (current recommendation)

Зафиксировать решение в ADR, не делать код до S220+. После удаления
pg-runner:

- Если LISTEN/NOTIFY нужен для external subscribers → сделать новый
  helper `infrastructure/workflow/events.py` (opt-in) для dashboards/alerts.
- Если не нужен → ADR закрыть (YAGNI).

**Pros**: zero code, clear decision, minimal commit.
**Cons**: technical debt (polling остаётся до S220+, но это **уже
deprecated backend** — никто не должен использовать в production).

**VERDICT**: ✅ ADOPT (current ADR).

## 3. Решение

**Defer LISTEN/NOTIFY до S220+ (pg-runner removal).** Делаем ADR-only:

1. **Сейчас (cycle 32)**: commit этот ADR. **No code changes**.
2. **S220+** (post pg-runner removal): re-evaluate need:
   - Если нужны external subscribers (dashboards, alerts) → создать
     `infrastructure/workflow/events.py` opt-in helper с LISTEN/NOTIFY.
   - Если нет → закрыть ADR как "не нужно" (YAGNI).

## 4. Consequences

### Positive
- Zero code work для doomed backend (YAGNI/ponytail).
- ADR документирует decision → будущий разработчик знает почему polling
  остаётся до S220+.
- Foundation для re-evaluation post-removal.

### Negative
- Polling продолжается до S220+ для callers, которые ещё не мигрировали
  на Temporal. **Mitigation**: `pg-runner` уже `.. deprecated::`,
  production callers должны быть на Temporal (`temporal_backend.py`).

### Neutral
- Никакого impact на production (Temporal backend).

## 5. Verification (machine-check)

```bash
# 1. ADR exists
test -f docs/adr/0280-listen-notify-defer-pg-runner-removal.md

# 2. pg-runner still deprecated (ground truth)
grep -c "DEPRECATED" src/backend/infrastructure/workflow/pg_runner_backend.py
# expected: >= 3

# 3. production callers уже на Temporal (NOT pg-runner)
grep -r "TemporalWorkflowBackend" src/backend/services/workflows/ src/backend/infrastructure/workflow/ 2>/dev/null | wc -l
# expected: >= 5 (production wiring)
```

Все 3 условия выполнены. ADR принят.

## 6. Related

- `docs/audit/CURRENT_STATE_2026-08-27.md` — P2.14 OPEN (старый claim)
- `docs/analysis/SPRINT_32_GAP_ANALYSIS_2026-08-27.md §4` — критический pivot
- `src/backend/infrastructure/workflow/pg_runner_backend.py:75-79` — deprecation
- `src/backend/infrastructure/workflow/temporal_backend.py:240-273` — production
- `src/backend/infrastructure/cdc/listen_notify_backend.py:37` — CDC scaffold (alt B)
