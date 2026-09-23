# ADR-0317 — W7 P1-9: DI evaluation — dishka vs самописный module_registry

* Статус: **Accepted** (research only, cycle 152).
* Связано с: MINIMAX W7 P1-9 (DI evaluation); ADR-0084 (libraries > custom).
* Без code change в этом ADR — research + decision matrix + roadmap.

## Контекст

Cycle 152 W7 P1-9 recon:

* **Custom DI**: `src/backend/core/di/module_registry.py` (361 LOC, cycle 152).
  API: `resolve_module(key)` + `validate_modules()` + `Scope` enum.
* **Provider pattern**: `core/di/providers/` (5 файлов, ~679 LOC): `get_X_provider()` + `set_X_provider()` + `_overrides` dict per provider.
* **20+ files** импортируют `module_registry`.
* **Scopes**: SINGLETON реализован (lazy resolve). SCOPED/TRANSIENT —
  schema-only registration per S170+, реализация pending.

**MINIMAX baseline**: 13 файлов rate-limiter + 2 CB + самописный DI =
  одна механика размазана. ADR-0084 требует замены кастома зрелыми библиотеками.

**Dishka** (https://github.com/reagento/dishka, v1.7.2 Sep 2025):
* Async-native, scopes (APP/REQUEST/SESSION), finalization, zero-globals,
  auto-wiring, FastAPI integration (`dishka-fastapi`).
* Alternatives matrix per https://dishka.readthedocs.io/en/stable/alternatives.html:

| Lib | Scopes | Async | Finalization | Concurrency-safe | Auto-wiring |
|---|---|---|---|---|---|
| **dishka** | ✅✅ | ✅ | ✅ | ✅ | ✅✅ |
| di | ✅✅ | ✅ | ✅ | ❌ | ✅ |
| FastAPI Depends | ✅❌ | ✅ | ✅ | ➖ | ✅ |
| dependency-injector | ❌ | ❌ | ❌ | ❌ | ❌ |

## Решение

### Phase 1 (cycle 152, ADR only): Add `dishka` в deps

**Decision**: Hybrid подход — keep `module_registry` для текущего
single-scope SINGLETON use case (он работает); add `dishka` в deps
для будущих multi-scope features (SCOPED/TRANSIENT).

### Phase 2 (отдельный wave, ~cycle 156+): scoped/async DI features

Реализация SCOPED/TRANSIENT scopes — **через dishka integration**, не через
extension custom `module_registry`. Rationale:
* Dishka предоставляет production-ready scopes.
* Extension custom DI требует написания ~200 LOC thread-local/contextvars
  plumbing + concurrency-safe resolution.
* Existing SINGLETON через `module_registry` остаётся для обратной совместимости.

### Phase 3 (отдельный wave, после Phase 2 telemetry): gradual migration

После того как Phase 2 покажет реальную пользу SCOPED/TRANSIENT scopes:
gradual migration `core/di/providers/*` → dishka providers (по одному за wave).
НЕ blind mass-migration (20+ importers, public contract preservation).

## Альтернативы (отклонённые)

* **Blind migration на dishka (Phase 1)**: отклонено — 20+ files используют
  `module_registry`, public contract нельзя ломать без telemetry + migration
  period. См. CLAUDE.md hard invariant: «публичные контракты ... ломать
  нельзя без ADR».
* **Stay 100% custom, реализовать SCOPED/TRANSIENT в module_registry**:
  отклонено — duplicate effort (~200 LOC contextvars plumbing) vs добавление
  battle-tested library. ADR-0084 explicit preference.
* **dependency-injector**: отклонено — alternatives matrix показывает ❌
  по 4/5 критериям (scopes, finalization, concurrency-safe, auto-wiring).
* **di (library)**: rejected — ❌ concurrency-safe.
* **FastAPI Depends**: rejected — DI смешан с request decomposition (official
  position https://dishka.readthedocs.io/en/stable/alternatives.html).

## Trade-offs

**Pros (Phase 1)**:
* ADR + research foundation для Phase 2/3.
* Минимальный risk (no code change).

**Cons (Phase 1)**:
* 0 immediate value (deferred to Phase 2+).

**Pros (Phase 2 — future)**:
* Async SCOPED/TRANSIENT out-of-box.
* FastAPI auto-injection через `@inject` decorator + `FromDishka[T]`.

**Cons (Phase 2 — future)**:
* Migration period: 20+ files используют `module_registry`.
* Два DI system'а сосуществуют (overhead).

## Альтернативы (отклонённые, детали)

* **Stay 100% custom**: см. выше — duplicate effort.
* **di (https://github.com/adriangb/di)**: ❌ concurrency-safe (per official
  alternatives table). Не подходит для multi-threaded ASGI server.
* **antidote**: ❌ без поддержки async (Sprint 152 search не нашёл — не
  viable для async/await DI).

## Verification (cycle 152)

```
# dishka доступна через uv (если решим мигрировать):
uv add dishka
# (НЕ выполняется в Phase 1)

# Текущий module_registry остаётся:
python3.14 -c "from src.backend.core.di.module_registry import resolve_module, Scope; \
                print('module_registry:', Scope.SINGLETON)"
  → module_registry: Scope.SINGLETON

compileall -q src/ extensions/ scripts/ tools/ tests/  → exit 0
pytest tests/unit/ -q                                    → regressions check
```

## Связанные изменения (Phase 1)

* **`docs/adr/0317-w7-p1-9-di-evaluation-dishka-vs-custom.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0317 зарегистрирован (110 ADRs total).
* **CHANGELOG.md** — запись цикла 152.
* **docs/roadmap/PROGRESS_LEDGER.md** — wave-memo для cycle 152.

Refs: MINIMAX W7 P1-9 (DI evaluation), ADR-0084 (libraries > custom),
dishka alternatives matrix (https://dishka.readthedocs.io/en/stable/alternatives.html),
ADR-0317 (this), cycle 152.