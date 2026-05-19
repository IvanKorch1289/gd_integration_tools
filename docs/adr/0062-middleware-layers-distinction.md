# ADR-0062 — Distinction между ASGI и Action-dispatch middleware

* Статус: Accepted (Wave [s9/k5-w7-execution-middleware-dedup], 2026-05-19)
* Связано с: GAP-15.1, V15.1 Single-Entry, PLAN.md V19.1 §S9 K5 W7.

## Контекст

В кодовой базе сосуществуют два каталога с похожим названием `middlewares/`:

1. **`entrypoints/middlewares/`** — pure ASGI middleware между HTTP/SOAP/etc
   слоями и services. Примеры: `correlation.py`, `tenant.py`, `api_key.py`,
   `security_headers.py`. Интерфейс — `ASGIApp` (Starlette-style).

2. **`services/execution/middlewares/`** — middleware для
   `DefaultActionDispatcher` (Action Activator pattern). Примеры:
   `AuditMiddleware`, `IdempotencyMiddleware`, `RateLimitMiddleware`.
   Интерфейс — `ActionMiddleware` (custom Protocol).

После наблюдения от GAP-аналитики возникла гипотеза о дублировании.

## Решение

**Не консолидировать. Это разные слои с разными контрактами.**

Подтверждено:

* ASGI middleware работает с raw HTTP-фреймворком (Starlette),
  обрабатывает request/response (bytes, headers, status).
* Action middleware работает с типизированным `DispatchContext` после
  парсинга в action invocation; не имеет HTTP-семантики.
* Один и тот же aspect (idempotency, audit) может требоваться в обоих
  слоях с разными контрактами:
  - ASGI: `X-Idempotency-Key` header через snok/asgi-idempotency-header.
  - Action: `DispatchContext.idempotency_key` для action-level dedup.

## Документная маркировка

* В `entrypoints/middlewares/__init__.py` docstring явно говорит
  "pure ASGI слой" (уже есть).
* В `services/execution/middlewares/__init__.py` docstring явно говорит
  "middleware для DefaultActionDispatcher" (уже есть).
* Этот ADR — explicit reference для будущих ревью.

## Открытые вопросы

* Если в будущем появится единая трассировка через OpenTelemetry, оба
  слоя могут share общую span-структуру. Это не консолидация
  middleware'ов, а их correlation.
