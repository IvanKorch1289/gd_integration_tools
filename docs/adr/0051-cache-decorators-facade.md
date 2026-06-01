# ADR-0051 — Cache-декораторы как фасад поверх CachingDecorator

* Статус: Accepted (Wave [s1/k2-1-cache-decorator], 2026-05-12)
* Связано с: PLAN.md V16 §S1 К2 DoD ("@cached / @invalidate / @multi_cached"), CLAUDE.md «dependency-decision».

## Контекст

DoD Sprint 1 К2 требует публичный API из трёх декораторов:

* `@cached(ttl, key, backend)` — кэшировать результат async-функции;
* `@invalidate(key_pattern)` — снять кеш по pattern'у после mutating-вызова;
* `@multi_cached(ttls)` — multi-slot кеш с разными TTL.

Очевидным внешним кандидатом является [aiocache](https://github.com/aio-libs/aiocache).
Однако:

* публикация на PyPI на момент решения — `1.0.0a0` (alpha), последний
  стабильный релиз `0.12.x` не имеет `multi_cached` API в нужной форме;
* проектная политика (`.claude/rules/dependency-decision.md`) запрещает
  добавлять alpha-зависимости в production-стек без сильного обоснования;
* in-house `infrastructure.decorators.caching.CachingDecorator` уже
  предоставляет суперсет фичей aiocache: multi-layer (Redis → Memory →
  Disk), stampede-protection (KeyLockManager), `stale_if_error`,
  Redis-failure cooldown.

## Решение

Реализуем декораторы как **тонкий фасад** в `core/resilience/cache_decorators.py`:

* `@cached` строит `CachingDecorator(use_redis, use_memory, use_disk)`
  по параметру `backend` и регистрирует custom `key_builder`, который
  рендерит template вида `"bki:{args[0]}"`;
* `@invalidate(pattern)` после успешного `func()` вызывает
  `redis_client.cache_delete_pattern(pattern)` (best-effort);
* `@multi_cached(ttls)` использует минимальный TTL из `ttls` поверх
  `multi`-backend (полная per-slot семантика — follow-up К2 в S2).

Фасад экспортируется из `src.backend.core.resilience` рядом с `Breaker`,
`RateLimit` и `RetryPolicy` — это позволяет писать единый импорт
для compose-декораторов `@policy(cb=, rl=, retry=, cache=)` (см. ADR-0052).

## Альтернативы

1. **Прямое использование `aiocache>=1.0.0a0`**.
   Минусы: alpha-релиз; конфликт с проектной политикой; повтор фич, уже
   реализованных в `CachingDecorator`.

2. **Прямое использование `CachingDecorator`**.
   Минусы: не SOLID — пользователь конфигурирует storage слоями (memory/
   redis/disk) на каждом callsite. Фасад скрывает эту сложность и даёт
   четыре читаемых имени `backend`.

3. **`functools.lru_cache`**.
   Минусы: in-process only; нет TTL, нет distributed-инвалидации.

## Последствия

* Один источник истины для кеша: `CachingDecorator` остаётся живым,
  тесты и метрики сохраняют валидность.
* `@invalidate` использует `redis_client.cache_delete_pattern` напрямую;
  pattern'ы должны включать prefix (например `bki:*`, не `*`) — задокументировано.
* `@multi_cached` сейчас деградирует до min-TTL multi-backend; full
  per-slot semantics запланирована на S2 К2 (track-c follow-up).
* Линт `check_layers.py`: фасад в `core/`, использует lazy-import
  `infrastructure.decorators.caching` (allowlist-friendly).

## Проверка

* Unit-тесты `tests/unit/core/resilience/test_cache_decorators.py` (5+
  кейсов: hit/miss, TTL expiry, key templating, invalidate, multi_cached);
* DoD Sprint 1 К2 закрывается через эти декораторы.
