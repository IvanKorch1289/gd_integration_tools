# ADR-005: tenacity — единственный механизм retry

* Статус: accepted
* Дата: 2026-04-21
* Фазы: A4 (Resilience consolidation)

## Контекст

В проекте одновременно жили два retry-механизма:

1. `tenacity` — промышленный стандарт, уже применялся в `http.py`
   (`@retry`-декоратор).
2. `RetryProcessor` в `src/dsl/engine/processors/control_flow.py` —
   собственный цикл `for attempt in range(...)` с ручной логикой
   backoff, без jitter, без интеграции с circuit breaker.

Параллельные реализации ведут к расхождениям в обработке таймаутов
(`asyncio.TimeoutError` vs `tenacity.RetryError`), дублируют тесты (если
бы они были) и создают ложное впечатление, что retry настраивается
по-разному в разных слоях.

Отдельная проблема: `CircuitBreakerMiddleware` держал один глобальный
`@circuit`-декоратор на всё FastAPI-приложение. Любой endpoint,
выдавший порог ошибок, размыкал цепь для всех — classic global-state
bug. Эта middleware удалена в A2.

## Решение

1. `RetryProcessor` переписан как тонкая обёртка над
   `tenacity.AsyncRetrying`:
   - `stop_after_attempt(max_attempts)` из tenacity.
   - Стратегия wait — `wait_fixed` или `wait_exponential`; опционально
     `+ wait_random(0, jitter)` для anti-thundering-herd.
   - Наш код отвечает только за сброс `Exchange` между попытками и
     корректное завершение при исчерпании retries.
2. `HttpxClient` (новый, ADR-009) использует `tenacity.retry`-декоратор
   с `retry_if_exception_type((httpx.TransportError,
   httpx.TimeoutException))`.
3. Circuit breaker остаётся на `aiocircuitbreaker`, но применяется
   **per-host** внутри `HttpxClient`, а не как middleware. Сбой одного
   даунстрима не разрывает circuit к другим хостам.
4. Новый пакет `app.infrastructure.resilience`:
   - `Bulkhead` + `BulkheadRegistry` — process-local изоляция.
   - `TimeLimiter` — adaptive timeout по EWMA p95/p99.
   - `RetryBudget` — ограничение доли retry в скользящем окне.
   - `ResourceRateLimiter` — per-resource presets поверх Redis
     token-bucket.
5. Комбинация (Bulkhead + RateLimiter + Retry + CircuitBreaker +
   TimeLimiter) применяется в `HttpxClient.request()` в одной
   последовательности — это единственный production-путь для исходящего
   HTTP.

## Альтернативы

- Оставить `RetryProcessor` как «более простой» вариант: отвергнуто,
  дублирование не окупается.
- Заменить tenacity на `backoff`: отвергнуто, tenacity богаче, у
  `backoff` нет встроенной интеграции с `@circuit`.
- Реализовать собственный retry «чище»: отвергнуто, не добавляет
  ценности.

## Последствия

- В будущем удалить или пометить deprecated собственные backoff-хелперы
  (их больше нет).
- DSL получает новые параметры: `.with_retry(max=3, backoff="exp",
  jitter=0.3)` — единообразно с HTTP-клиентом.
- Глобальный CircuitBreakerMiddleware удалён (A2). Если нужен
  circuit breaker на уровне FastAPI — он собирается в route-guard
  декоратор per-route, не в middleware.
