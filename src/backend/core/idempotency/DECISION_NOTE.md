# Decision note: `core/idempotency` vs `entrypoints/middlewares/idempotency.py`

## State (2026-09-21)

Два parallel implementation:

| Component | Layer | Pattern |
|---|---|---|
| `src/backend/entrypoints/middlewares/idempotency.py` | entrypoint | HTTP-header based (`Idempotency-Key`), ASGI middleware, Redis backend |
| `src/backend/core/idempotency/` | core | Function-level API (`execute_or_replay`, `@idempotent` decorator), InMemory/Redis/Postgres backends |

## Аудит finding

`scan_isolated_modules.py` показывает: `core/idempotency` имеет **0 production callers**.
При этом `entrypoints/middlewares/idempotency.py` уже используется в production.

## Рекомендация (НЕ выполнено в этой сессии — требует решение owner)

Три варианта, в порядке убывания риска:

### Option A: DELETE `core/idempotency/` (рекомендуется)

- **За**: устраняет duplicate, уменьшает surface, middleware уже покрывает use case.
- **Против**: 54 focused tests будут удалены; пользователи `execute_or_replay` decorator (если такие есть вне тестов) сломаются.
- **Effort**: 30min + verify no external callers + delete tests.

### Option B: WIRE `core/idempotency` → middleware

- **За**: единая storage backend, decorator API становится available для HTTP path.
- **Против**: refactor middleware (243 LOC), риск regression, требует thorough test coverage.
- **Effort**: 4-8h.

### Option C: EXPERIMENTAL (status quo + flag)

- **За**: минимальный риск, deferred decision.
- **Против**: surface остаётся, документация путается, audits продолжат flag.
- **Effort**: 1h documentation.

## Owner decision pending

Зафиксировано в `docs/FEATURE_INVENTORY.md` (Status: DECISION-PENDING).
Sprint 36 W4 или 37 должен выбрать A/B/C.

## Пока — статус

`core/idempotency` помечен как **DECISION-PENDING**.
НЕ считается production-ready до consolidation.
Production код должен использовать `entrypoints/middlewares/idempotency.py`.
