# ADR-009: httpx с HTTP/2 заменяет aiohttp

* Статус: accepted
* Дата: 2026-04-21
* Фазы: A4 (Resilience + aiohttp→httpx)

## Контекст

Проект использует aiohttp 3.12 в четырёх местах:

- `src/infrastructure/clients/transport/http.py` — legacy `HttpClient`
  (~546 LOC).
- `src/entrypoints/webhook/handler.py` — outbound webhook POST.
- `src/dsl/importers/postman_parser.py` — загрузка Postman-коллекций.
- `src/core/config/constants.py` — `aiohttp.ClientError` в tuple
  `RETRY_EXCEPTIONS`.

Ограничения aiohttp:

1. Нет нативной HTTP/2 (требуется отдельный `aiohttp-http2` plugin,
   maintained слабо).
2. Нет streaming iterable-формат ответа с `orjson`.
3. Connection-pool менее гибкий: `limit_per_host` работает, но без
   sliding-window и без exposed-hook на saturation.
4. Взаимодействие с `anyio` (и `sniffio`) менее удобное — в будущем
   часть async-кода переходит на `anyio` (structured concurrency).

## Решение

1. Добавлен `httpx[http2] ^0.28.0` — новый дефолт.
2. Создан `HttpxClient` в
   `app.infrastructure.clients.transport.http_httpx` — тонкий клиент,
   интегрированный с пакетом `app.infrastructure.resilience`:
   - Bulkhead per-host.
   - Adaptive TimeLimiter (EWMA p99).
   - Per-host CircuitBreaker.
   - Per-resource RateLimiter (Redis).
   - Tenacity retry с jitter.
3. `webhook/handler.py` и `postman_parser.py` уже переведены на
   `httpx.AsyncClient` в A4.
4. `core/config/constants.py :: RETRY_EXCEPTIONS` расширен:
   `(aiohttp.ClientError | httpx.HTTPError | asyncio.TimeoutError)` —
   обрабатывает оба источника, пока legacy live.
5. Legacy `http.py` остаётся до H3 Cleanup: при импорте выдаёт
   `DeprecationWarning`. Перенос скваш-миграции call-sites
   (orders/skb/dadata/ai_agent/scraping/components/antivirus/base_external_api)
   на `HttpxClient` — последовательно в C-фазах по мере миграции
   соответствующих коннекторов.

## Альтернативы

- **Оставить aiohttp**: отвергнуто, нет HTTP/2 и хуже развитие.
- **grequests / async-httpx-forks**: не maintained.
- **Написать тонкий wrapper поверх низкоуровневого `asyncio`**:
  отвергнуто, повторяет работу httpx/aiohttp.

## Последствия

- Новые коннекторы пишутся на `HttpxClient` из коробки.
- В `pyproject.toml` одновременно присутствуют `aiohttp` и `httpx` —
  промежуточное состояние до H3.
- Tenacity-retry становится единым механизмом (ADR-005).
- HTTP/2 auto-negotiation: если сервер не поддерживает h2, httpx
  падает на h1 без дополнительной конфигурации.
