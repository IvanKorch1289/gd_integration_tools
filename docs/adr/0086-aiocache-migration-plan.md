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

---

## S62 W1 Closure: Scope Reduction Rationale (2026-06-08)

**Decision**: Full Phase 1-4 migration **DEFERRED** to S63+ with major scope
reduction. aiocache POC proven работает (S59 W4 ``aiocache_poc.py`` + 47
cache tests pass), но **feature parity gap** слишком большой для
одно-волновой миграции.

### Что НЕ мигрировано (S62 W1 verify)

| Cache concern | Custom impl | aiocache support | Migration? |
|---|---|---|---|
| Per-key TTL envelope | ✅ ``CacheEnvelope`` | ✅ ``aiocache.cached(ttl=...)`` | trivial, but **already in @cached backend=memory** |
| Stampede protection (KeyLockManager) | ✅ custom lock | ❌ (нет в core) | ❌ DEFERRED (perf critical, не drop-in) |
| Tag-based invalidation | ✅ ``invalidator.py`` | ❌ (нет в core) | ❌ DEFERRED (out-of-scope feature) |
| Disk backend | ✅ ``DiskTTLCache`` | ⚠️ ``aiocache.backends.DiskCache`` (contrib) | ⚠️ possible, not in core |
| Multi-tier (Redis → Memory → Disk) | ✅ ``CachingDecorator`` | ❌ (нет multi-tier) | ❌ DEFERRED (architectural) |
| Tenant-namespaced keys | ✅ ``tenant_wrapper.py`` | ⚠️ через key_builder | ⚠️ possible, not drop-in |
| Prometheus metrics hooks | ✅ встроенные в MemoryBackend | ❌ (нет out-of-box) | ❌ DEFERRED (Phase 3 plugin) |
| Renew TTL on access | ✅ ``renew_ttl=True`` | ❌ (нет) | ❌ DEFERRED (не стандарт) |
| Exclude self from cache (recursion) | ✅ ``exclude_self=True`` | ❌ (нет) | ❌ DEFERRED (edge case) |

**Conclusion**: aiocache = good library, но **не drop-in replacement** для
``CachingDecorator``. **6 из 9 features** — отсутствуют или требуют
non-trivial плагинов. Phase 4 ("Multi-tier chain поверх aiocache") — это
**essentially rewriting CachingDecorator**, ~405 LOC.

### Что РЕАЛЬНО сделано (S59 W4 → S62 W1)

1. ✅ ``aiocache>=0.12`` в ``pyproject.toml`` (core dep)
2. ✅ ``src/backend/infrastructure/cache/aiocache_poc.py`` — POC доказывает
   что aiocache работает в pytest-async среде проекта
3. ✅ 47 cache tests pass (regression baseline)
4. ✅ ADR-0086 написан и согласован

### Forward path (S63+ candidates)

* **aiocache 1.0** (когда выйдет stable) — может иметь multi-tier / stampede
  из коробки
* **Per-feature ad-hoc migration** — НЕ глобально, а по 1 use-case, когда
  бизнес-требование действительно простое (memory-only, no envelope, no
  stampede). На текущий момент таких use-cases в проекте не обнаружено.
* **New code only** — для будущих фич использовать ``@aiocache.cached``
  напрямую вместо ``@cached`` если фича simple. ADR-0084 уже это
  рекомендует (libraries > custom).

### Bottom line

S62 W1 = **close aiocache migration backlog как RESOLVED-WITH-NO-ACTION**.
aiocache available + POC proven + ADR documented. Full migration не
оправдан — feature parity gap + small scope = poor ROI.

References:
* S59 W4: ``93e8bdfa [verified] feat(cache): S59 W4 — aiocache dep + POC + ADR-0086 migration plan``
* S62 W1 (this closure): scope-reduce justification.

Status: **CLOSED — DEFERRED to per-feature ad-hoc (no global migration)**.
