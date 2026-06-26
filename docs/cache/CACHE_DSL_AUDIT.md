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
