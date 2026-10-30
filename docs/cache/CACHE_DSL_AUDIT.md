# Caching DSL Audit (S171 M17.2)

## Existing cache infrastructure

| Component | File | Status |
|-----------|------|--------|
| **Cache facade** | `core/cache/facade.py` | ✅ UnifiedCacheFacade + Memory + Fallback + Redis |
| **Cache backends** | `infrastructure/cache/backends/` | ✅ Redis, KeyDB, Memcached, Disk, Memory |
| **S3 cache adapter** | `infrastructure/storage/s3_cache.py` | ✅ Read-through + write-invalidation |
| **Tiered cache** | `infrastructure/cache/tiered.py` | ✅ L1 (memory) + L2 (Redis) |
| **Tenant wrapper** | `infrastructure/cache/tenant_wrapper.py` | ✅ Per-tenant prefix |
| **Invalidator** | `infrastructure/cache/invalidator.py` | ✅ Tag-based |
| **RAG cache** | `core/cache/rag.py` | ✅ Semantic cache |
| **Idempotency** | `services/execution/middlewares/idempotency_middleware.py` | ✅ |

## DSL for caching

| Component | File | Capability |
|-----------|------|-----------|
| **Per-route policy** | `dsl/builders/policy_mixin.py` | cache/CB/rate_limit/timeout/retry/bulkhead/adaptive_timeout/idempotency (8 types) |
| **Cache middleware** | `entrypoints/middlewares/response_cache.py` | HTTP response cache |
| **Request cache** | `entrypoints/middlewares/request_body_cache.py` | Request body cache |
| **S3 DSL** | `dsl/engine/processors/infra_s3.py` | S3 storage operations |
| **Storage DSL** | `dsl/engine/processors/storage/` | multi-backend storage |

## DSL usage example

```python
from src.backend.dsl.builder import RouteBuilder

route = (
    RouteBuilder.from_("api.users.list", source="internal:admin")
    .policy.cache(ttl_seconds=300, key="users-list", backend="redis")
    .policy.idempotency(key="users-idem", ttl_seconds=3600)
    .db_crud(operation="read", entity="user")
    .response_cache(ttl_seconds=60)
    .build()
)
```

## Cache facade usage (4 backends)

```python
from src.backend.core.cache import (
    RedisCacheFacade,
    MemoryCacheFacade,
    FallbackCacheFacade,
)

# Single backend
redis_cache = RedisCacheFacade(url="redis://localhost:6379/0")

# Fallback chain
cache = FallbackCacheFacade(
    primary=redis_cache,
    secondary=MemoryCacheFacade(),
    tertiary=DiskCacheFacade(path="/tmp/cache"),
)
```

## Инвалидация по всем уровням кэша (ADR-0401)

Глобальный `CacheInvalidator` (единственный потребитель —
`services/core/base/cache_mixin.py`) работает с **backend'ами**, а не с
фасадом. Primary-уровень (Redis) в него регистрировался, а memory (L1) и
disk (L3) создавались напрямую в `plugins/composition/service_setup.py` и
в инвалидатор **не попадали**. Итог: tag/pattern-инвалидация чистила
только primary-тир, и после отказа Redis клиент получал **stale-значения**
из L1/L3.

Теперь:

* `MemoryBackend` и `DiskCacheBackend` получили tag-индекс
  (`bind_key_to_tag` / `delete_by_tag`, `delete_by_pattern` → int у memory);
* `infrastructure/cache/factory.py::_register_invalidator_backend` стал
  публичным `register_backend_in_invalidator`; новая
  `create_cache_fallback_backends()` создаёт L1/L3 (обёрнутые в
  `TenantCacheBackend` — defense-in-depth против cross-tenant leak через
  shared L1/L3) и регистрирует их в глобальном `CacheInvalidator`;
* `plugins/composition/service_setup.py` вызывает её, передавая
  `disk_path=cache_settings.disk_fallback_path` (прямое чтение поля, без
  `getattr` — гейт cycle 163).

## Квоты файлов (ADR-0401)

`core/di/providers/storage.py` теперь создаёт quota-manager
(`get_quota_manager_provider()`), и `get_storage_facade_provider()`
передаёт фасаду `quota_manager` и `enforce_quota` (из
`FileStorageSettings.enforce_quota`). Раньше фасад, отданный extensions'ам,
получал `quota_manager=None` и `enforce_quota=False` — режим enforcement
не доходил.

Вторая половина долга: в `infrastructure/storage/s3.py` не было метода
`size()`, поэтому при удалении объекта счётчик байт квоты не уменьшался
(уменьшался только счётчик файлов). Теперь `S3ObjectStorage.size()`
(`head_object` → `ContentLength`, 0 для 404), а `TenantObjectStorage`
проксирует `size()` — удаление уменьшает счётчик **байт**.

## Audit verdict

M17.2: cache DSL coverage 100% — все типы кэширования покрыты:
- HTTP response/request cache (middlewares)
- Per-route policy (policy_mixin.py, 8 types)
- Storage cache (S3 read-through)
- Tenant-aware cache (prefix per tenant)
- Tiered cache (L1 + L2)
- Semantic cache (RAG)
- Idempotency cache

M17.2 done — 0 gaps, 0 missing DSL.

Refs:
- M17.2 audit phase
- S171 Sprint 36 production readiness
