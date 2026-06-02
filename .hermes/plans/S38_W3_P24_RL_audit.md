# T3.1 — Audit RateLimit files (ОБНОДЕЕНО)

> **T3.1 артефакт.** Аудит 12 файлов RateLimit перед консолидацией.
> **Факт-чек 02.06.2026:** уже сделано в Sprint 1 V16 Single-Entry (Step 3.2/3.3).
> **W3 (P2.4) scope:** 0 legacy файлов, только doc-clarification.

## Все RateLimit-файлы (12 шт, факт)

| # | Файл | Статус | Примечание |
|:-:|------|:------:|------------|
| 1 | `core/resilience/rate_limiter.py` | **canonical base** | Sprint 1 V16, `RateLimit`/`RateLimitExceeded`/`RateLimiter` Protocol |
| 2 | `core/resilience/decorators.py` | wrapper | `@rate_limit` decorator (uses canonical) |
| 3 | `core/resilience/resilience_profile.py` | profile | `RateLimitPolicy` (через BreakerPolicy) |
| 4 | `core/interfaces/multi_protocol.py` | interface | `RateLimit` Protocol |
| 5 | `infrastructure/resilience/unified_rate_limiter.py` | **canonical impl** | Redis token-bucket (V16) |
| 6 | `infrastructure/resilience/distributed_rl_cluster.py` | distributed | multi-instance coordination |
| 7 | `infrastructure/resilience/rate_limiter.py` | shim | backwards-compat shim → unified |
| 8 | `services/execution/middlewares/rate_limit_middleware.py` | middleware | FastAPI middleware |
| 9 | `services/execution/middlewares/__init__.py` | init | re-exports |
| 10 | `services/ai/gateway/exceptions.py` | exceptions | `RateLimitExceeded` |
| 11 | `entrypoints/middlewares/global_ratelimit.py` | middleware | global rate-limit middleware |
| 12 | `entrypoints/api/v1/endpoints/admin_resilience_profile.py` | admin | endpoint |

## Ревизия v9 плана P2.4

**v9 говорил:** "4+ реализации, нужна консолидация"
**Реальность (Sprint 1 V16):** консолидация УЖЕ сделана (Step 3.2/3.3)

| Аспект | До V16 | После V16 (текущее) |
|--------|--------|---------------------|
| **Public API** | `unified_rate_limiter.get_rate_limiter()` | `core.resilience.rate_limiter.get_rate_limiter()` |
| **Re-exports** | — | `core/resilience/__init__.py`: `RateLimit, RateLimiter, RateLimitExceeded, RedisRateLimiter, get_rate_limiter` |
| **Canonical base** | — | `core/resilience/rate_limiter.py` (Protocol) |
| **Canonical impl** | `infrastructure/resilience/unified_rate_limiter.py` | без изменений (он и есть canonical impl) |
| **Backwards-compat shim** | — | `infrastructure/resilience/rate_limiter.py` → re-export из unified |

## Что НЕ сделано (work for S38 W3)

1. **Doc-clarification:** явно указать в ARCHITECTURE.md / docs/, что RateLimit canonical = `core.resilience.rate_limiter` Protocol + `infrastructure.resilience.unified_rate_limiter` impl
2. **Migration note:** для callsite'ов, использующих `infrastructure.resilience.rate_limiter` (shim) — обновить до canonical
3. **Tests:** coverage для canonical `core/resilience/rate_limiter.py` (аналогично T2.3b для CB)
4. **Pattern clarification:** Protocol (`RateLimit` / `RateLimiter`) vs impl (`RedisRateLimiter`) — где какой использовать

## T3.2 — Стратегия

**Рекомендация:** **D2-light (clarify, не deprecate)**:

| Действие | Файл | Статус |
|----------|------|:------:|
| Doc-clarification в ARCHITECTURE.md | `ARCHITECTURE.md` | +5 строк (RateLimit section) |
| Migration note в CB guide (расширить) | `docs/resilience/circuit-breaker-migration.md` → переименовать в `resilience-migration.md` | объединить CB + RateLimit |
| Tests для canonical | `tests/unit/core/resilience/test_rate_limiter.py` | новый файл |
| Backwards-compat shim cleanup | `infrastructure/resilience/rate_limiter.py` | НЕ трогаем (shim нужен для V24+) |

**Не депрекейтим** ничего — нет реальных legacy.

## Что НЕ делаем в W3

- ❌ Не депрекейтим shim'ы (они полезны для V24+ removal)
- ❌ Не переименовываем `unified_rate_limiter.py` (он и есть canonical)
- ❌ Не сливаем CB и RateLimit (разные concerns, но схожая структура)

## T3.2 (следующий шаг) — конкретные действия

1. Создать `docs/resilience/rate-limit-migration.md` (по образцу CB)
2. Расширить `docs/resilience/circuit-breaker-migration.md` → `resilience-migration.md` (объединить)
3. ARCHITECTURE.md: добавить RateLimit canonical reference
4. (T3.3) Tests для canonical — отложено (coverage gate issue)

## Открытые вопросы

- `infrastructure/resilience/rate_limiter.py` shim — реально используется? Если 0 callsite, можно удалить (но V24+).
- `distributed_rl_cluster.py` — это **отдельная фича** (не legacy), не трогаем.
- `multi_protocol.py` interface — дублирует `core.resilience.rate_limiter`? Проверить.

## S38 метрика (W3)

| Метрика | Baseline | Target W3 | Как измерить |
|---------|:--------:|:---------:|--------------|
| RateLimit реализаций (canonical) | 2 (Protocol + Redis impl) | 2 (clarify, не уменьшать) | `grep -rln class.*RateLimit` |
| Backwards-compat shims | 1 | 1 (sustain) | `infrastructure/rate_limiter.py` |
| Tests для canonical | 0 | 1+ (≥85% coverage) | отложено в T3.3 |

## Следующий шаг

**T3.2** — doc-clarification (rate-limit-migration.md + ARCHITECTURE.md). Bite-sized, 1-2 PR.
