# ADR-0311 — W4 P1-6: aiocache evaluation + HYBRID decision (sync=cachetools, simple async=aiocache opt-in, advanced=custom)

* Статус: **Accepted** (2026-09-23, cycle 152).
* Связано с: MINIMAX W4 P1-6 (aiocache вместо ~681 LOC самописного кэша);
  ADR-0084 (библиотеки > кастом).
* Добавлено: `aiocache>=0.12.3` в `[project.optional-dependencies.caching]`.
* Pilot: `AiocacheMemoryBackend` (opt-in, не подключён в factory).

## Контекст

MINIMAX baseline зафиксировал ~681 LOC самописных async cache-декораторов
в `infrastructure/decorators/caching/` (1014 LOC total) + god-module
`core/di/providers/cache.py` (868 LOC). ADR-0084 требует замены кастома
зрелыми библиотеками.

Cycle 152 recon: проект уже имеет:

* **`cachetools>=5.3.0,<8.0.0`** в deps — sync in-memory TTL+LRU.
* **`redis>=5.0.0,<6.0.0`** в deps — Redis client (используется напрямую).
* **Кастомные backends** в `infrastructure/cache/backends/` (memory,
  redis, keydb, memcached, disk) — реализуют `CacheBackend` ABC.

## Оценка aiocache (W4 P1-6)

### Что такое aiocache?

`aiocache` — async cache manager (aio-libs org, v0.12.3 latest на Sep
2024). Поддерживает backends: memory, redis, memcached, dynamodb.
Decorators: `@cached`, `@cached_stampede` (с `RedLock`), `@multi_cached`.
Сериализаторы: String/Json/Pickle + custom. Плагины: pre/post hooks.

### Feature parity matrix (custom CachingDecorator vs aiocache)

| Feature | Custom CachingDecorator | aiocache | Decision |
|---|---|---|---|
| Memory backend | ✅ (`MemoryBackend`) | ✅ (`SimpleMemoryCache`) | **tie** |
| Redis backend | ✅ (`RedisBackend`) | ✅ (`RedisCache`) | **tie** |
| KeyDB backend | ✅ (`KeyDBBackend`) | ❌ (use Redis) | **keep custom** |
| Memcached backend | ✅ (optional, `aiomcache`) | ✅ (built-in) | **tie** |
| Disk backend | ✅ (`DiskCacheBackend`) | ❌ | **keep custom** |
| `@cached` decorator | ✅ (`__call__` wrapper) | ✅ (`@cached`) | **tie** |
| Stampede protection | ✅ (`stampede.py` + lock) | ✅ (`@cached_stampede` + RedLock) | **tie** |
| **Stale-while-revalidate** | ✅ (`envelope.py`) | ❌ (manual) | **keep custom** |
| **Pattern invalidation** | ✅ (`delete_pattern` ABC) | ❌ (only `delete(key)`) | **keep custom** |
| **Envelope (cached metadata + value)** | ✅ (`CacheEnvelope`) | ❌ (raw values) | **keep custom** |
| TTL per-key | ✅ | ✅ | **tie** |
| **Prometheus-метрики** | ✅ (через `metrics_registry`) | ❌ (manual) | **keep custom** |
| **Tenant-aware wrapper** | ✅ (`TenantCacheBackend`) | ❌ (manual) | **keep custom** |

### Совместимость с Python 3.14

aiocache v0.12.3 (Sep 2024) тестировался с Python 3.13 (setup.py update
Nov 2024). Cycle 152 verification на Python 3.14.0:

```python
@cached(ttl=10)
async def expensive_call(x: int) -> int:
    await asyncio.sleep(0.01)
    return x * 2
# call 1 (miss): 10
# call 2 (hit): 10
# aiocache Python 3.14 async test: OK
```

**Pass**. aiocache 0.12.3 совместим с Python 3.14.

## Решение: HYBRID подход

**Не полная миграция, а opt-in aiocache для простых случаев**:

1. **`cachetools`** (sync in-memory) — **KEEP как есть**. Уже используется
   в `infrastructure/cache/lru_cache.py` (195 LOC). Подходит для sync-кода.

2. **`aiocache`** (opt-in) — добавлен в `[project.optional-dependencies.caching]`.
   Активируется через `uv sync --extra caching` или `pip install -e ".[caching]"`.
   Pilot: `AiocacheMemoryBackend` — реализация `CacheBackend` ABC поверх
   `aiocache.SimpleMemoryCache`.

3. **Custom `CachingDecorator`** — **KEEP** для advanced use cases:
   - SWR (stale-while-revalidate) — критично для RAG cache.
   - Pattern invalidation — критично для multi-tenant cache poisoning defense.
   - Envelope (metadata + value) — для observability.
   - Prometheus-метрики + Tenant-wrapper — defense-in-depth.

4. **`AiocacheMemoryBackend`** — НЕ подключён в `create_cache_backend()`
   factory. Пользователи импортируют напрямую (`from infrastructure.cache.backends.aiocache_backend import
   AiocacheMemoryBackend`).

## Альтернативы (рассмотренные, отклонённые)

* **Полная миграция на aiocache (все ~681 LOC заменить)**: отклонено —
  aiocache не покрывает SWR/envelope/pattern-invalid (feature gap
  ~30% от custom CachingDecorator).
* **`cachetools` + custom (без aiocache)**: отклонено — cachetools sync-only,
  не покрывает async Redis scenarios, которые есть в `CachingDecorator`.
* **`diskcache` вместо кастомного `DiskCacheBackend`**: отклонено —
  diskcache не async (threading-based), требует дополнительной обёртки.

## Pilot: AiocacheMemoryBackend

**Файл**: `src/backend/infrastructure/cache/backends/aiocache_backend.py`
(новый, ~165 LOC).

**Реализует**: `core.interfaces.cache.CacheBackend` ABC (get/set/delete/
delete_pattern/exists/close).

**Особенности**:

* Lazy import aiocache (после `_ensure_aiocache_available()`). ImportError →
  `AiocacheBackendImportError` с подсказкой про `[caching]` extra.
* `cache_class=SimpleMemoryCache` (class object, не string — aiocache API
  требует именно class).
* `delete_pattern` — approximation через `_cache.keys()` (private API
  aiocache memory backend) + `fnmatch`. Documented limitation: для
  production pattern deletion рекомендуется `RedisBackend`.
* TTL per-key через `aiocache.Cache.set(ttl=...)`.

**Тесты** (cycle 152 manual verification):

```
backend = AiocacheMemoryBackend(maxsize=100, default_ttl=60)
await backend.set('foo', b'bar_value', ttl=10)
assert await backend.get('foo') == b'bar_value'
assert await backend.exists('foo')
await backend.set('user:1:profile', b'p1', ttl=10)
await backend.set('user:2:profile', b'p2', ttl=10)
await backend.set('order:1', b'o1', ttl=10)
await backend.delete_pattern('user:*:profile')
assert not await backend.exists('user:1:profile')
assert not await backend.exists('user:2:profile')
assert await backend.exists('order:1')
await backend.close()
# All assertions passed.
```

## Roadmap для W4 P1-6 дальнейшие фазы

* **Phase 2** (отдельный wave): интегрировать `AiocacheMemoryBackend` в
  `create_cache_backend()` factory (`case "aiocache-memory"`). Требует
  добавления нового значения в `CacheSettings.backend` enum.
* **Phase 3** (W9 god-objects): декомпозиция `core/di/providers/cache.py`
  (868 LOC) — **отдельная задача**, не W4.
* **Phase 4** (P2): рассмотреть `aioredis` → `redis>=5.0.0` (уже сделано)
  + `cachetools` patterns. Уже сделано.

## Verification (cycle 152)

```
uv add --optional caching aiocache
  → + aiocache==0.12.3 → pyproject.toml [project.optional-dependencies.caching]

uv run python -c "import aiocache; print(aiocache.__version__)"
  → 0.12.3

uv run python -c "<async @cached test>"
  → aiocache Python 3.14 async test: OK

python3.14 -c "<import AiocacheMemoryBackend, basic get/set test>"
  → All assertions passed.

python3.14 -m compileall -q src/ extensions/ scripts/ tools/ tests/  → exit 0
```

## Связанные изменения

* **`pyproject.toml`** — добавлен `aiocache>=0.12.3` в
  `[project.optional-dependencies.caching]`.
* **`src/backend/infrastructure/cache/backends/aiocache_backend.py`** —
  новый opt-in backend (165 LOC).
* **`docs/adr/0311-w4-p1-6-aiocache-evaluation-hybrid.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0311 зарегистрирован (104 ADRs total).
* **`CHANGELOG.md`** + **`docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W4 P1-6 (aiocache), ADR-0084 (libraries > custom),
ADR-0311 (this), cycle 152.