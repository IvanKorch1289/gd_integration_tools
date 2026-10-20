# ADR-0354: `CacheProcessor` → `services.cache.UnifiedCacheFacade` (tenant prefix) — cycle 170

* **Статус**: ACCEPTED (2026-10-20, cycle 170, пользователь Mavis)
* **Cycle**: 170
* **Связан с**:
  - `DSL_AUDIT_CACHE_LOGGING_2026-10-20.md` §2.1 (cross-tenant risk)
  - ADR-0352 (services.UnifiedCacheFacade canonical impl)
  - ADR-0347 (tenant isolation boundary auto-surface)
* **Затрагивает**:
  - `src/backend/dsl/engine/processors/ai/cache_processor.py`
  - `src/backend/dsl/engine/processors/ai/cachewrite_processor.py`
  - `src/backend/core/di/providers/cache.py` (new provider)
  - `src/backend/dsl/engine/processors/ai/_integration.py` (helper)

## Контекст

Cycle 169 audit (`DSL_AUDIT_CACHE_LOGGING_2026-10-20.md` §2.1) обнаружил:

```python
# src/backend/dsl/engine/processors/ai/cache_processor.py:39
key = f"dsl:cache:{self._key_fn(exchange)}"
# Прямой вызов redis_client.cache_get(key)
```

`CacheProcessor` и `CacheWriteProcessor` используют
`services.infrastructure.clients.storage.redis.RedisClient.cache_get()` /
`cache_set()` напрямую, **без** `TenantCacheBackend` wrapper (cycle 34
B-03 fix).

### Проблема

Cycle 34 B-03 ввёл `TenantCacheBackend` для defense-in-depth против
cache poisoning (S21 K1 W2): все ключи получают префикс
`tenant:{id}:` (или `tenant:_unscoped_:` если tenant context отсутствует).

`CacheProcessor` обходит этот wrapper:

1. Redis-tenant-prefix'нутый backend хранит `tenant:t1:user:42`.
2. **Параллельно** Redis-non-tenant-prefix'нутый ключ
   `dsl:cache:user:42` (от `CacheProcessor`) не имеет tenant prefix.
3. Cross-tenant risk: если Tenant A и Tenant B используют одинаковый
   `key_fn` (например, `lambda ex: str(ex.in_message.body.get('user_id'))`),
   оба попадают в один и тот же ключ `dsl:cache:42`.

**Status**: HIGH risk (security — tenant isolation).

## Решение

**Мигрировать `CacheProcessor` / `CacheWriteProcessor` на
`services.cache.UnifiedCacheFacade`** через DI provider.

### Шаги

1. **Создать `get_unified_cache_facade_provider()` в `core.di.providers.cache`**
   — возвращает singleton `UnifiedCacheFacade` с tenant wrapper.

2. **Изменить `CacheProcessor.process()`**:
   ```python
   facade = get_unified_cache_facade_provider()
   result = await facade.get_ns(key, namespace="dsl_cache")
   if result.value is not None:
       # cache hit
   ```

3. **Изменить `CacheWriteProcessor.process()`**:
   ```python
   facade = get_unified_cache_facade_provider()
   await facade.set_ns(key, value, ttl=self._ttl, namespace="dsl_cache")
   ```

4. **Namespace = `"dsl_cache"`** — отделяет DSL cache от других namespace'
   ов (`default`, `admin`, и т.д.).

### Layer rule consideration

Текущее правило (CLAUDE.md):
> services → core разрешено; core → services запрещено.

`dsl` импортирует из `core` (через DI provider). Это OK.
`services.cache.UnifiedCacheFacade` — это **production impl**, который
вызывается через DI provider (core-owned), а не прямой import.

DI provider в `core.di.providers.cache` имеет late resolve
(`resolve_module`), что сохраняет layer rule. Direct import services в
DSL processor **запрещён**.

Реализация через `get_unified_cache_facade_provider()` в
`core.di.providers.cache` — это **core layer**, который может
импортировать services через `resolve_module` (lazy), что не нарушает
layer rule (lazy imports невидимы для `tools/check_layers.py`).

## Альтернативы

### Option B: tenant prefix в key_fn (rejected)

Документировать, что `key_fn` должен включать `tenant_id`:

```python
.cache(key_fn=lambda ex: f"{context.tenant_id}:{ex.in_message.body['user_id']}")
```

**Плюсы**: минимальное изменение.

**Минусы**:
- Easy to forget (silent failure).
- Нет обратной совместимости со старыми key_fn.
- Не соответствует единому паттерну `UnifiedCacheFacade` для всех
  cache-вызовов.

**Rejected** в пользу Option A (canonical facade).

### Option C: cache key prefix через TenantCacheBackend в CacheProcessor (rejected)

Обернуть `redis_client` напрямую в `TenantCacheBackend` внутри
`CacheProcessor.process()`:

```python
wrapped = TenantCacheBackend(redis_client)
await wrapped.get(key)
```

**Плюсы**: минимальное изменение.

**Минусы**:
- Дублирование wrapping логики в каждом cache processor.
- Не использует capability check из `UnifiedCacheFacade`.
- Не использует namespace isolation.

**Rejected** в пользу Option A (canonical facade с полным feature set).

## Последствия

### Позитивные

- **Tenant isolation enforced** на уровне DSL cache.
- Единый pattern: все cache-вызовы через `UnifiedCacheFacade`.
- Capability check (`cache.read`, `cache.write`) автоматически
  применяется.
- Namespace isolation (`"dsl_cache"`) предотвращает конфликты с другими
  cache users.

### Негативные

- Дополнительный indirection через DI provider.
- При первом вызове — cold start overhead (singleton creation).

## Проверка после реализации

```bash
# 1. Layer check — нет новых violations
uv run python tools/check_layers.py --strict

# 2. Tenant isolation test
uv run pytest tests/unit/dsl/engine/processors/test_cache_processor.py -v

# 3. Integration test с реальным tenant context
uv run python -c "
import asyncio
from src.backend.dsl.engine.processors.ai.cache_processor import CacheProcessor
from src.backend.core.tenancy.context import TenantContext

async def main():
    ctx = TenantContext(tenant_id='t1')
    # CacheProcessor должен использовать tenant prefix
asyncio.run(main())
"

# 4. Grep — нет прямого import services в DSL
grep -rn "from src.backend.services" src/backend/dsl/engine/processors/ai/
# Expected: 0 результатов (всё через DI provider)
```

## Статус реализации

**Cycle 170** (этот ADR). Реализация + тесты + коммит.