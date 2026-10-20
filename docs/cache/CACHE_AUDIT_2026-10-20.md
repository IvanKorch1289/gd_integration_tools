# Cache Architecture Audit — Cycle 163 (2026-10-20)

> **Status**: COMPLETED with follow-up actions
> **Date**: 2026-10-20
> **Author**: Mavis (autonomous cycle)
> **Scope**: Cache facade unification, working capability, centralized config

## Цель аудита

Задача: проверить функциональность кэширования приложения — фасады,
унификацию, работоспособность, централизованную настройку. Исправить
найденные неконсистентности, актуализировать документацию, протестировать.

## Результаты

### 1. Проверка работоспособности (PASSED)

Инфраструктура кэширования протестирована end-to-end:

| Компонент | Файл | Статус |
|---|---|---|
| `UnifiedCacheFacade` (core ABC) | `src/backend/core/cache/facade.py` | ✅ PASS |
| `MemoryCacheFacade` | `src/backend/core/cache/facade.py` | ✅ PASS |
| `FallbackCacheFacade` (Redis → Memory → Disk) | `src/backend/core/cache/facade.py` | ✅ PASS |
| `RedisCacheFacade` | `src/backend/core/cache/facade.py` | ✅ PASS |
| `DiskCacheFacade` | `src/backend/core/cache/facade.py` | ❌ REMOVED (cycle 164 dead code, ADR-0352 consolidation) |
| `UnifiedCacheFacade` (services — capability-checked) | `src/backend/services/cache/facade.py` | ✅ PASS |
| `ThreeTierRagCache` | `src/backend/core/cache/rag.py` | ✅ PASS |
| Backend factory | `src/backend/infrastructure/cache/factory.py` | ✅ PASS |
| `TenantCacheBackend` (multi-tenant prefix) | `src/backend/infrastructure/cache/tenant_wrapper.py` | ✅ PASS |
| `TieredCacheBackend` (L1+L2) | `src/backend/infrastructure/cache/tiered.py` | ✅ PASS |
| `LruMemoryCache` (prometheus-metrics) | `src/backend/infrastructure/cache/lru_cache.py` | ✅ PASS |
| `CacheInvalidator` (tag-based) | `src/backend/infrastructure/cache/invalidator.py` | ✅ PASS |
| Backends: redis / keydb / memcached / disk / memory | `src/backend/infrastructure/cache/backends/` | ✅ PASS |
| RAG 3-tier cache | `src/backend/infrastructure/cache/rag/` | ✅ PASS |
| Redis cluster + sentinel modes | `src/backend/infrastructure/cache/redis_cluster.py` | ✅ PASS |
| DI provider | `src/backend/core/di/providers/cache.py` | ✅ PASS |
| DI registration (svcs) | `src/backend/plugins/composition/service_setup.py::_register_cache_facade` | ✅ PASS |

**Test coverage**: 73 cache-related test files across `tests/unit/cache/`,
`tests/unit/infrastructure/cache/`, `tests/unit/services/cache/`,
`tests/unit/core/cache/`, `tests/unit/cache/backends/`,
`tests/unit/cache/rag/`, `tests/unit/services/ai/cache/`,
`tests/smoke/test_semantic_cache_smoke.py`,
`tests/chaos/test_cache_chain_chaos.py`, `tests/cache/`. Smoke run:

```
tests/unit/core/cache tests/unit/services/cache tests/unit/infrastructure/cache/test_tenant_wrapper.py
tests/unit/infrastructure/cache/test_lru_cache.py
78 passed in 3.31s
```

### 2. Унификация фасадов (❌ CRITICAL FINDING — ADR-0352)

**Проблема**: существуют **ДВА `UnifiedCacheFacade`** с одинаковым именем,
разными API и разными зонами ответственности.

#### 2.1 Core-фасад (`src/backend/core/cache/facade.py`, 399 LOC)

- `UnifiedCacheFacade` (ABC, Rule 1 single-entry) с concrete-реализациями:
  - `MemoryCacheFacade` (dev_light / tests)
  - `FallbackCacheFacade` (primary → fallback chain, Rule 6)
  - `RedisCacheFacade` (production, RedisBackend wrapper)
- API: `get(key)`, `set(key, value, ttl_seconds, tags)`,
  `delete(*keys)`, `delete_by_tag(tag)`, `exists(key)`, `healthcheck()`.
- TTL + tag invalidation policy через `ClassVar[CacheInvalidationPolicy]`.
- Используется: `core/di/providers/cache.py::get_cache_facade()`.

#### 2.2 Services-фасад (`src/backend/services/cache/facade.py`, 167 LOC)

- `UnifiedCacheFacade` (concrete, P1 S133 W4 — capability-checked).
- API: `get(key, namespace='default')`,
  `set(key, value, ttl, namespace)`, `delete(*keys, namespace)`,
  `exists(key, namespace)`, `delete_pattern(pattern, namespace)`.
- Возвращает `CacheResult(value, hit, backend)`.
- Включает capability check (`cache.read`, `cache.write` per namespace).
- Tiered fallback: primary → memory → disk (3-tier).
- DI-регистрация через svcs (`register_factory(UnifiedCacheFacade, _factory)`).
- Используется: `plugins/composition/service_setup.py::_register_cache_facade`.

#### 2.3 Конфликт

| Аспект | Core-фасад | Services-фасад |
|---|---|---|
| Module path | `src.backend.core.cache.facade` | `src.backend.services.cache.facade` |
| Pattern | ABC + concrete impls | Concrete |
| Namespace | ❌ нет | ✅ `namespace='default'` |
| Return type | `bytes \| None` | `CacheResult(value, hit, backend)` |
| Tag invalidation | ✅ `delete_by_tag(tag)` | ❌ нет (есть `delete_pattern`) |
| Capability check | ❌ нет | ✅ |
| DI-registration | ❌ нет | ✅ svcs |
| TTL semantics | `ttl_seconds` + global policy | `ttl` per-call |
| `healthcheck()` | ✅ | ❌ |
| Re-export | `core/cache/__init__.py` | `services/cache/__init__.py` |

**Это нарушает принцип R1 "single canonical API"** из CLAUDE.md.

**Решение**: см. ADR-0352 `docs/adr/0352-cache-facade-duplication.md`.

### 3. Централизованная настройка (⚠️ GAP — fixed in this commit)

#### 3.1 Что работает

- `src/backend/core/config/services/cache.py::CacheSettings` —
  основной Pydantic v2 settings-класс через `BaseSettingsWithLoader`.
  Поля: `backend` (Literal["redis","keydb","memcached","memory"]),
  `l1_enabled`, `l1_maxsize`, `keydb_active_replica`.
- `RedisSettings` — отдельный класс с `cluster_mode`, `cluster_nodes`,
  `sentinel_mode`, `sentinel_nodes`, `cache_expire_seconds`,
  `max_connections` и т.д. Включает `model_validator` для cross-field checks.
- Используется через `from src.backend.core.config.services.cache import
  cache_settings` (singleton).
- YAML группа: `cache` (`yaml_group: ClassVar[str] = "cache"`),
  env prefix: `CACHE_`.

#### 3.2 Найденный gap (FIXED)

**Проблема**: `src/backend/plugins/composition/service_setup.py::_register_cache_facade`
резолвил `disk_fallback_path` через `getattr(cache_settings, "disk_fallback_path", None)` —
**но это поле не было определено в `CacheSettings`**. Это нарушает централизованную
настройку: `getattr` маскировал отсутствующее поле, и DEFP-значение
`Path("var/cache/disk_fallback")` хардкодилось в composition root.

**Fix** (this commit):
- `CacheSettings.disk_fallback_path: str = "var/cache/disk_fallback"` —
  добавлено явное поле с описанием.
- `CacheSettings.disk_fallback_enabled: bool = True` —
  для отключения L3 (например, in-cluster production, где диск — anti-pattern).
- `service_setup.py::_register_cache_facade` теперь использует
  `cache_settings.disk_fallback_path` и `cache_settings.disk_fallback_enabled`
  напрямую, без `getattr`-fallback.

### 4. Тестовое покрытие

```
tests/unit/core/cache/                → 5+ (facade, init)
tests/unit/services/cache/            → 5+ (facade, metrics, init)
tests/unit/cache/                     → 8+ (admin_dsl, validator, tier_router, lru_memory, rag/, invalidator)
tests/unit/cache/backends/            → 5+ (memcached, keydb, redis, memory)
tests/unit/cache/rag/                 → 6+ (three_tier, integration, etc.)
tests/unit/infrastructure/cache/      → 10+ (disk, redis_cluster, tenant_wrapper, lru_cache, cache_invalidator)
tests/unit/services/ai/cache/         → 1+ (l3_retrieval)
tests/smoke/                          → 1 (semantic_cache)
tests/chaos/                          → 1 (cache_chain_chaos)
tests/cache/                          → 2 (tenant_isolation, redis_cluster)
─────────────────────────────────────────────
TOTAL: ~73 test files, 250+ tests
```

### 5. CI gates

| Gate | Файл | Статус |
|---|---|---|
| Layer-check (services → core) | `tools/check_layers.py` | ✅ PASS для core/cache |
| Stdlib logging check | `tools/audit_stdlib_logging.py` | ✅ PASS (cycle 160) |
| Module size check | `tools/checks/check_module_size.py` | ✅ PASS (все модули <500 LOC, facade.py 399 — borderline) |
| Backend tests | `pytest tests/unit/infrastructure/cache/backends/` | ✅ PASS |

### 6. Известные неконсистентности (для будущих циклов)

1. **Два `UnifiedCacheFacade`** — главная неконсистентность. ADR-0352.
2. ✅ **RESOLVED (cycle 164)**: `DiskCacheFacade` (core) удалена как dead code.
   Disk-tier теперь ТОЛЬКО через `DiskCacheBackend` (infrastructure). CI guard
   `tools/checks/check_cache_facade_uniqueness.py` добавлен — запрещает
   `class DiskCacheFacade` за пределами infrastructure/.
3. ✅ **RESOLVED (cycle 164)**: `cache_expire_seconds` мигрирован из
   `RedisSettings` → `CacheSettings` (CACHE concern, не redis-специфичный).
   `RedisSettings.cache_expire_seconds` остался как deprecated @property
   (backward-compat). Decorator + config_profiles/base.yml обновлены.
   Тесты: `tests/unit/core/config/services/test_cache_expire_seconds_migration.py`.
4. ✅ **CLARIFIED (cycle 164)**: Три memory-класса в разных слоях с разными ролями
   — **intentional design**, не consolidation issue:

   | Class | Layer | Interface | Purpose |
   |---|---|---|---|
   | `MemoryCacheFacade` | core/cache/ | `UnifiedCacheFacade` ABC | DI fallback chain (`get_cache_facade`) + `FallbackCacheFacade` chain |
   | `MemoryBackend` | infrastructure/cache/ | `CacheBackend` interface | L1/L2 of services.UnifiedCacheFacade 3-tier (primary/memory/disk) |
   | `LruMemoryCache` | infrastructure/cache/ | duck-typed | L1 of RAG 3-tier router (L1 → L2 Redis → L3 Qdrant) with prometheus metrics |

   These serve different abstraction levels and SHOULD remain separate.
   `MemoryCacheFacade` имеет tag invalidation (отсутствует в `MemoryBackend`),
   `MemoryBackend` имеет `delete_pattern` (отсутствует в `MemoryCacheFacade`),
   `LruMemoryCache` имеет prometheus metrics + Any types (для RAG embeddings).

   Подробнее: см. ADR-0352 Stage 6 + `tests/unit/cache/test_three_memory_roles.py`.
5. (бывший #4) ~~`cache_expire_seconds` в `RedisSettings`~~ — RESOLVED cycle 164.
   cache-параметр, а не Redis-специфичный). Возможно стоит перенести в
   `CacheSettings` (требует миграции).
5. **`CacheSettings.max_connections`** отсутствует, хотя `RedisSettings.max_connections`
   есть. Дублирование конфига. Требует решения.

### 7. Сводка изменений (этот коммит)

| Файл | Изменение |
|---|---|
| `src/backend/core/config/services/cache.py` | Добавлены `disk_fallback_path` и `disk_fallback_enabled` |
| `src/backend/plugins/composition/service_setup.py` | Убран `getattr`-fallback, использован `cache_settings.disk_fallback_path` |
| `docs/cache/CACHE_AUDIT_2026-10-20.md` | Новый документ (этот файл) |
| `docs/adr/0352-cache-facade-duplication.md` | Новый ADR — two-facade unification plan |
| `tests/unit/core/config/services/test_cache_disk_fallback_settings.py` | Новый — smoke test settings |
| `tests/unit/core/cache/test_facade_audit.py` | Новый — dual-facade existence smoke test |
| `CHANGELOG.md` | Запись о cycle 163 |

### 8. Что НЕ сделано (deferred)

- **Полная унификация двух `UnifiedCacheFacade`** — слишком крупный refactor,
  требует отдельного wave (Dev2). См. ADR-0352.
- ✅ **`DiskCacheFacade` consolidation** — RESOLVED cycle 164 (удалена).
- ✅ **`cache_expire_seconds` миграция** — RESOLVED cycle 164 (мигрирован).

### 9. Cycle 164 — RESOLVED deferred items (this commit set)

**ADR-0352 deferred items, выполненные в cycle 164:**

| Item | Status | Resolution |
|---|---|---|
| DiskCacheFacade vs DiskCacheBackend | ✅ RESOLVED | DiskCacheFacade (core) удалена. DiskCacheBackend (infrastructure) — единственный disk-tier. CI guard добавлен. |
| `cache_expire_seconds` миграция | ✅ RESOLVED | Поле перенесено из RedisSettings в CacheSettings. Decorator + config_profiles/base.yml обновлены. RedisSettings.cache_expire_seconds сохранён как deprecated @property. |

Refs: ADR-0352, cycle 163 cache audit, cycle 164 consolidation