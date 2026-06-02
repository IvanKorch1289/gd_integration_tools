# Rate Limit Migration Guide (S38)

> **Audience:** разработчики, работающие с RateLimit в gd_integration_tools.
> **Status:** v1 (S38 W3 T3.2) | **Note:** никаких изменений API не требуется —
> консолидация уже сделана в Sprint 1 V16 Single-Entry (Step 3.2/3.3).

## TL;DR

| Аспект | Canonical (Sprint 1 V16) |
|--------|--------------------------|
| **Public API** | `from src.backend.core.resilience import RateLimit, RateLimiter, RateLimitExceeded, RedisRateLimiter, get_rate_limiter` |
| **Protocol** | `core/resilience/rate_limiter.py` — `RateLimit`, `RateLimiter` Protocol |
| **Implementation (Redis)** | `infrastructure/resilience/unified_rate_limiter.py` — `RedisRateLimiter` |
| **Singleton** | `get_rate_limiter()` — Redis-backed (lazy) |
| **Backwards-compat shim** | `infrastructure/resilience/rate_limiter.py` — re-export из unified |

## Структура

```
core/resilience/rate_limiter.py          # Protocol (RateLimit, RateLimiter)
        ↑ re-export
core/resilience/__init__.py             # Public API
        ↑ uses (in canonical code)
infrastructure/resilience/unified_rate_limiter.py  # Redis impl (RedisRateLimiter)
        ↑ re-export
infrastructure/resilience/rate_limiter.py         # backwards-compat shim
```

## Где какой использовать

| Use case | Что использовать |
|----------|------------------|
| **Новый код, нужна абстракция** | `RateLimiter` Protocol + своя реализация |
| **Нужна Redis-based защита** | `RedisRateLimiter` или `get_rate_limiter()` |
| **Process-local in-memory** | `pyrate_limiter.Limiter` (singleton в `entrypoints/dependencies/rate_limit.py`) |
| **Decorate функцию** | `@rate_limit` из `core.resilience.decorators` |
| **Middleware** | `services/execution/middlewares/rate_limit_middleware.py` |
| **Distributed coordination** | `infrastructure/resilience/distributed_rl_cluster.py` (отдельный модуль) |

## Примеры кода

### Базовый (Redis-based)

```python
from src.backend.core.resilience import get_rate_limiter, RateLimitExceeded

limiter = get_rate_limiter()
try:
    async with limiter.acquire("user:123", limit=10, period=60):
        result = await external_api.call()
except RateLimitExceeded:
    return {"error": "rate limit exceeded"}
```

### Decorator

```python
from src.backend.core.resilience.decorators import rate_limit

@rate_limit(limit=10, period=60, key="user_id")
async def my_endpoint(user_id: str):
    return await external_api.call()
```

### Protocol-based custom impl

```python
from src.backend.core.resilience import RateLimit, RateLimiter

class MyCustomRateLimiter:
    """Implements RateLimiter Protocol."""
    async def acquire(self, key: str, limit: int, period: int) -> None: ...
    async def release(self, key: str) -> None: ...

# Dependency injection
limiter: RateLimiter = MyCustomRateLimiter()
```

## Coexistence (S38 → V24+)

- ✅ **Никаких deprecations** — консолидация уже сделана в Sprint 1 V16
- ✅ `infrastructure/resilience/rate_limiter.py` остаётся как backwards-compat shim
- ✅ Старые callsite'ы (`from ...unified_rate_limiter import`) продолжают работать
- ⚠️ V24+: возможно cleanup shim'ов (не сейчас)

## Где НЕ искать RateLimit

| Не использовать | Почему |
|-----------------|--------|
| `pyrate_limiter.Limiter` напрямую (кроме entrypoints/dependencies) | Process-local, не multi-instance-safe |
| `redis_coordinator.throttle` | Другая фича (resource coordination, не rate-limit) |
| Кастомные impl в extensions/ | Используйте Protocol + DI |

## Edge cases

| Случай | Поведение |
|--------|-----------|
| `distributed_rl_cluster.py` | Отдельный модуль для **distributed coordination** (не путать с rate-limit). Не rate-limit. |
| `multi_protocol.py` interface | Protocol-определение `RateLimit`. Дубликат `core.resilience.rate_limiter`? Уточнить. |
| `infrastructure/rate_limiter.py` shim | Backwards-compat. Используйте `core.resilience.rate_limiter` напрямую. |
| `entrypoints/middlewares/global_ratelimit.py` | HTTP middleware, использует canonical. |

## Тесты (отложено в S38 backlog)

- `tests/unit/core/resilience/test_rate_limiter.py` — Protocol coverage
- `tests/unit/infrastructure/resilience/test_unified_rate_limiter.py` — Redis impl coverage

**Причина отсрочки:** `make coverage-gate` таймаутит 600s (TECH_DEBT
`pre-prod-check-coverage-timeout`). Используем `make lint` как gate.

## См. также

- `docs/resilience/circuit-breaker-migration.md` — аналогичный guide для CB
- `.hermes/plans/S38_W3_P24_RL_audit.md` — полный audit
- `.hermes/plans/S38_V23_PLAN.md` — S38 план
- Sprint 1 V16 Single-Entry (Step 3.2/3.3) — V22 release notes
