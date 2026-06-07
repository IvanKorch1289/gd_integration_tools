# ADR-0086 — aiocache Migration Plan (S60+)

**Status:** Proposed (S59 W4 scope-reduced)
**Date:** 2026-06-07
**Authors:** K3
**Sources:** v22 final report (R22.1 — libraries), S59 W4 inventory
**Supersedes:** — (additive, не заменяет существующее)
**See also:** ADR-0084 (libraries migration plan, parent), ADR-0005 (cache layer)

## Context

V22 final report (R22.1) recommends adopting ``aiocache>=0.12`` library
как replacement для кастомной cache-инфраструктуры (1778 LOC):

* ``infrastructure/decorators/caching/`` — 683 LOC (``CachingDecorator``,
  ``CacheEnvelope``, ``KeyLockManager``, disk backend);
* ``infrastructure/cache/`` — 1095 LOC (Redis backend, Memory backend,
  KeyDB backend, validator, factory, metrics, cluster).

**Custom cache features** (все нужны проекту, не все есть в aiocache):

| Feature | Custom (project) | aiocache 0.12 |
|---|---|---|
| Memory backend | ✅ ``MemoryBackend`` (LRU + TTL) | ✅ SimpleMemoryCache |
| Redis backend | ✅ ``RedisBackend`` (async) | ✅ RedisCache |
| KeyDB backend | ✅ ``backends/keydb.py`` | ❌ (использует ``RedisCache``) |
| Disk backend | ✅ ``DiskTTLCache`` | ❌ (нет в core, есть ``aiocache.backends.DiskCache`` в contrib) |
| Envelope serialization (compression) | ✅ ``CacheEnvelope`` (gzip + JSON) | ❌ (plain pickle/json) |
| Stampede protection | ✅ ``KeyLockManager`` (asyncio.Lock per key) | ❌ (есть через plugins) |
| Multi-tier chain (memory → redis → disk) | ✅ ``cache_chain.py`` | ❌ (одно backend на cache) |
| Per-key TTL | ✅ через envelope | ✅ ``aiocache.cached(ttl=...)`` |
| Cache key builder | ✅ ``build_cache_key`` (hash-based) | ✅ ``key_builder=`` |
| Tenant isolation | ✅ ``tenant_wrapper.py`` | ❌ (нужно вручную) |
| Metrics | ✅ ``metrics_collector.py`` | ❌ (через plugins) |
| Circuit breaker integration | ✅ (через ``cache_chain``) | ❌ (нет) |
| FastAPI integration | ✅ (через Depends) | ✅ (через Depends) |

**Анализ** (S59 W4): 1:1 replacement не реалистичен. Custom cache имеет
6+ features которые aiocache не предоставляет из коробки. Полная миграция
потребует либо:
* (a) Расширить aiocache через custom serializer + plugins;
* (b) Сохранить custom cache для этих features, использовать aiocache
  только для **новых** use-cases (memory-only, no envelope, no stampede).

**Принятое решение** (S59 W4 honest scope):

* **S59 W4**: inventory + ADR + POC + pyproject dep;
* **S60+**: per-feature migration по частям, **только для use-cases
  где aiocache достаточен** (memory-only cache без envelope, без stampede).
* Custom cache ОСТАЁТСЯ для critical path (envelope, stampede, disk).

## Decision

1. **Добавить ``aiocache>=0.12,<1.0`` в core deps** (S59 W4) — library
   доступна для **opt-in** использования в новом коде.
2. **POC** (S59 W4): ``infrastructure/cache/aiocache_poc.py`` — 1 функция,
   декорированная ``@aiocache.cached``, с тестами.
3. **Per-feature migration plan** (S60+):
   * **Phase 1** (S60+): migrate simple memory-only caches (no envelope,
     no stampede, no tenant isolation) — низкорисковое, ~200 LOC;
   * **Phase 2** (S60+): migrate Redis-only caches (1 backend) — средний
     риск, ~400 LOC, требует audit каждого callsite;
   * **Phase 3** (S60+): НЕ мигрировать caches с envelope/stampede/disk
     (custom cache остаётся primary).
4. **Metrics + observability**: aiocache plugins для prometheus metrics
   (S60+).

## Consequences

### Positive

* v22 finding R22.1 частично закрыт (aiocache installed + available);
* Library > custom для SIMPLE cache use-cases;
* Async-native (как custom cache);
* Multi-backend из коробки (memory, redis, memcached).

### Negative

* aiocache НЕ заменяет custom cache полностью (envelope/stampede/disk
  отсутствуют);
* Два cache stacks в проекте = confusion для новых разработчиков (нужна
  документация);
* aiocache plugins для metrics/serializers — дополнительный overhead.

### Risks

* **R1**: developers используют aiocache там где нужен custom cache
  (envelope/stampede) → silent data loss / perf degradation. **Mitigation**:
  docstring warning в ``aiocache_poc.py`` + ADR + code review.
* **R2**: aiocache pinned to ``<1.0`` — breaking changes при major bump.
  **Mitigation**: tests + pyproject constraint.

## Alternatives Considered

### Option A: Полная миграция (1:1) custom → aiocache

*Rejected*: aiocache не предоставляет envelope, stampede, disk backend,
tenant isolation. Требует написания custom plugins — и тогда library >
custom не работает (мы переписали бы aiocache в кастомный код).

### Option B: НЕ мигрировать (status quo)

*Rejected*: v22 finding R22.1 рекомендовал library adoption. Полный
ignore → backlog carryover + library analysis stale.

### Option C: Phase-by-phase migration (принятое)

*Selected*: incremental migration только для use-cases где aiocache
достаточен. Custom cache остаётся для critical path.

## Implementation Plan (S60+)

| Phase | Scope | LOC | Risk | Sprint |
|---|---|---|---|---|
| 1 | Memory-only simple caches (no envelope, no stampede) | ~200 | Low | S60 W1 |
| 2 | Redis-only single-tier caches | ~400 | Med | S60 W2 |
| 3 | Plugin: prometheus metrics для aiocache | ~100 | Low | S60 W3 |
| 4 | Multi-tier chain (memory → redis) — КАСТОМНЫЙ поверх aiocache | ~300 | High | S60 W4 |

Total: ~1000 LOC migration (out of 1778 custom cache LOC). Остальные
~800 LOC (envelope, stampede, disk, tenant) — кастомные, остаются.

## References

* v22 final report (R22.1, R22.5) — library recommendations;
* ADR-0084 (libraries migration plan, parent);
* ADR-0005 (cache layer, original design);
* aiocache docs: https://aiocache.readthedocs.io/
* S59 W4 inventory: ``src/backend/infrastructure/decorators/caching/`` +
  ``src/backend/infrastructure/cache/`` (~1778 LOC total).
