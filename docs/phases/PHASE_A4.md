# Фаза A4 — Resilience consolidation + aiohttp → httpx (миграция)

* **Статус:** done
* **Приоритет:** P0
* **Связанные ADR:** ADR-005, ADR-009
* **Зависимости:** A3

## Цель

1. Убрать дубль retry-логики: собственный `RetryProcessor` vs
   `tenacity` — оставить tenacity как единственный путь retry.
2. Ввести единый пакет `app.infrastructure.resilience` (Bulkhead,
   TimeLimiter, RetryBudget, ResourceRateLimiter).
3. Начать миграцию коннекторов aiohttp → httpx; добавить новый
   `HttpxClient` с HTTP/2; перевести webhook и postman на httpx;
   legacy `http.py` пометить deprecated.

## Выполнено

### Resilience package

- `src/infrastructure/resilience/__init__.py` — публичный API.
- `bulkhead.py` — `Bulkhead` (asyncio.Semaphore) + `BulkheadRegistry`
  + `BulkheadExhausted`.
- `time_limiter.py` — `TimeLimiter` с EWMA p95/p99 adaptive timeout.
- `retry_budget.py` — `RetryBudget` с sliding-window.
- `rate_limiter.py` — `ResourceRateLimiter` (facade over Redis RL с
  per-resource presets: http/grpc/kafka/mqtt/websocket).

### RetryProcessor переписан (ADR-005)

- `src/dsl/engine/processors/control_flow.py` — `RetryProcessor` стал
  обёрткой над `tenacity.AsyncRetrying`:
  - `stop_after_attempt(max_attempts)`.
  - `wait_fixed` / `wait_exponential` + `wait_random(0, jitter)`.
  - Сброс состояния `Exchange` между попытками, корректный final-fail.

### httpx-based HTTP client (ADR-009)

- `src/infrastructure/clients/transport/http_httpx.py` — новый
  `HttpxClient`:
  - `httpx.AsyncClient(http2=True, http1=True)` — авто-fallback.
  - Bulkhead per-host.
  - Adaptive TimeLimiter.
  - Per-host CircuitBreaker (`aiocircuitbreaker`).
  - ResourceRateLimiter (Redis).
  - Tenacity retry с jitter.

### Коннекторы мигрированы

- `src/entrypoints/webhook/handler.py` — `aiohttp.ClientSession` →
  `httpx.AsyncClient(http2=True)`.
- `src/dsl/importers/postman_parser.py` — то же.
- `src/core/config/constants.py :: RETRY_EXCEPTIONS` — добавлен
  `httpx.HTTPError`, оставлен `aiohttp.ClientError` (try/except импорт)
  — поддержка обоих источников до H3.

### Legacy http.py

- Добавлен `warnings.warn(DeprecationWarning)` при импорте модуля.
- Запись в `docs/DEPRECATIONS.md` (удаление в H3, 2026-07-01).
- `check_deps_matrix.py`: `aiohttp` перемещён из `A4.REMOVE` в
  `H3.REMOVE` — реалистичная точка полного выключения.

## Definition of Done

- [x] `RetryProcessor` переписан на tenacity; сохранён публичный API.
- [x] Пакет `infrastructure.resilience` создан; 4 модуля; публичный
      `__init__.py`.
- [x] `HttpxClient` с HTTP/2 + bulkhead + CB per-host + adaptive TL.
- [x] webhook и postman на httpx.
- [x] constants.py `RETRY_EXCEPTIONS` поддерживает оба стека.
- [x] Legacy http.py отмечен deprecated.
- [x] ADR-005 + ADR-009.
- [x] `docs/phases/PHASE_A4.md` (этот файл).
- [x] PROGRESS.md / PHASE_STATUS.yml (A4 → done).

## Как проверить вручную

```bash
# RetryProcessor теперь использует tenacity:
grep -n 'AsyncRetrying' src/dsl/engine/processors/control_flow.py
# → должен найти

# Resilience package importable:
python -c "
from app.infrastructure.resilience import Bulkhead, TimeLimiter, RetryBudget, ResourceRateLimiter
print(Bulkhead(name='test', max_concurrent=4).max_concurrent)
"

# HttpxClient работает:
python -c "
import asyncio
from app.infrastructure.clients.transport.http_httpx import get_httpx_client
async def m():
    c = get_httpx_client()
    r = await c.request('GET', 'https://httpbin.org/get')
    print(r.status_code)
    await c.close()
asyncio.run(m())
"
```

## Follow-up

- C1–C11: по мере миграции коннекторов переводим call-sites legacy
  http.py на HttpxClient.
- H3: полное удаление legacy http.py и aiohttp из pyproject.
