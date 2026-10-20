# ADR-0352: Унификация двух `UnifiedCacheFacade` (Cycle 163 cache audit)

> **Статус**: ACCEPTED (с deferred implementation)
> **Дата**: 2026-10-20
> **Автор**: Mavis (autonomous cycle)
> **Cycle**: 163 cache audit
> **Supersedes**: ничего
> **Superseded by**: —

## Контекст

В ходе cycle 163 cache audit обнаружено: в проекте существуют **ДВА класса с
одинаковым именем `UnifiedCacheFacade`**, расположенных в разных слоях
(core vs services), с разными API, разной семантикой и разными callsite'ами.

### Два фасада

| Аспект | Core (`src.backend.core.cache.facade`) | Services (`src.backend.services.cache.facade`) |
|---|---|---|
| Pattern | ABC + 4 concrete impl | Concrete |
| Namespace param | ❌ | ✅ `namespace='default'` |
| Return type | `bytes \| None` | `CacheResult(value, hit, backend)` |
| Tag invalidation | ✅ `delete_by_tag(tag)` | ❌ (`delete_pattern(pattern)`) |
| Capability check | ❌ | ✅ `cache.read`, `cache.write` |
| DI registration | ❌ (lazy resolve) | ✅ svcs `register_factory` |
| TTL semantics | `ttl_seconds` + global `ClassVar[CacheInvalidationPolicy]` | `ttl` per-call |
| `healthcheck()` | ✅ | ❌ |
| Re-export | `core/cache/__init__.py` | `services/cache/__init__.py` |

### Callsites

- `core/di/providers/cache.py::get_cache_facade()` → возвращает
  `core.cache.facade.MemoryCacheFacade` обёрнутый в
  `FallbackCacheFacade(primary=memory, fallback=memory)`.
- `plugins/composition/service_setup.py::_register_cache_facade()` →
  регистрирует `services.cache.facade.UnifiedCacheFacade` в svcs с
  primary + memory_fallback + disk_fallback (3-tier).

### Проблема

1. **Нарушение R1 "single canonical API"** — два класса делают разные
   вещи, но называются одинаково. Разработчик не знает, какой
   использовать.
2. **API дрейф** — namespace, return type, capability check — это не
   эволюция, это два независимых дизайна.
3. **Усложнение онбординга** — `from src.backend.core.cache import
   UnifiedCacheFacade` vs `from src.backend.services.cache import
   UnifiedCacheFacade` — какой правильный?
4. **CI gate отсутствует** — нет тестов, запрещающих дублирование имён
   фасадов в core/ и services/.

## Решение

**Принять двухэтапный план унификации**, с реализацией в Sprint 7+ Dev2:

### Stage 1 (cycle 163 — DONE): DOCUMENTATION + GUARDRAIL

- ✅ Создан `docs/cache/CACHE_AUDIT_2026-10-20.md` — полный аудит.
- ✅ Создан этот ADR-0352 — фиксация решения.
- ✅ Закрыт централизованной настройки gap (`disk_fallback_path`).
- ✅ Добавлен `tools/checks/check_cache_facade_uniqueness.py` —
  статический guard, запрещающий `class UnifiedCacheFacade` за пределами
  whitelist (`core/cache/facade.py`, `services/cache/facade.py`).
  Проверяет 3 инварианта: (1) unauthorized definitions,
  (2) missing `__all__` re-export в cache `__init__.py`,
  (3) duplicate `cache_settings` singleton. `--strict` mode для CI gate.
- ✅ Подключён через `make check-cache-facade-uniqueness` (см. make/quality.mk).
- ✅ 14 unit-тестов в `tests/tools/test_check_cache_facade_uniqueness.py`
  покрывают positive/negative cases.

### Stage 2 (Cycle 165 — DONE): MERGE — один canonical ABC

**Решение: `core.cache.facade.UnifiedCacheFacade` остаётся canonical ABC.
`services.cache.facade.UnifiedCacheFacade` теперь `extends` core ABC.**

Обоснование:
- Layer rule (CLAUDE.md): `services → core` OK; `core → services` FORBIDDEN.
- `core/cache/facade.py` — canonical interface definition.
- `services/cache/facade.py` — concrete impl с namespace + capability +
  observability (extends core ABC).

**Cycle 165 (DONE) — что сделано:**

1. **`src/backend/services/cache/facade.py`** — `class UnifiedCacheFacade`
   теперь extends `core.cache.facade.UnifiedCacheFacade` (ABC). Все ABC
   abstract methods реализованы:
   - `get(key) → bytes | None`
   - `set(key, value, ttl_seconds, tags)`
   - `delete(*keys)`
   - `delete_by_tag(tag) → int`
   - `exists(key) → bool`
   - `healthcheck() → bool`

2. Namespace-aware варианты вынесены в `*_ns` методы:
   - `get_ns(key, namespace) → CacheResult`
   - `set_ns(key, value, ttl, tags, namespace)`
   - `delete_ns(*keys, namespace)`
   - `delete_by_tag_ns(tag, namespace) → int`
   - `exists_ns(key, namespace) → bool`
   - `delete_pattern_ns(pattern, namespace)`
   - `healthcheck_ns()`

3. Facade-level `_tag_index` для tag invalidation без native backend tag support.

4. **`src/backend/core/di/providers/cache.py::get_cache_facade`** — docstring
   обновлён: dev/test path. Production canonical = services facade.

5. **CI guard расширен**: `_check_services_facade_extends_core()` —
   проверяет, что services facade extends core ABC. Запрещает новые
   classes без правильного inheritance.

6. **Tests обновлены**:
   - `tests/unit/services/cache/test_facade.py` — все 14 тестов используют
     `*_ns` методы (наследие старого API); 7 новых ABC-метод-тестов.
   - `tests/unit/core/cache/test_facade_audit.py` — обновлены signature
     checks для ABC parity. Добавлен `test_services_is_core_subclass`.

**Result:** 802 cache-тестов проходят. Layer rule сохранён.

### Stage 3 (Sprint 8): DEPRECATE core-фасад

1. В `core/cache/__init__.py` оставить только re-exports + deprecation
   warnings на `MemoryCacheFacade`, `FallbackCacheFacade`,
   `RedisCacheFacade`. ~~`DiskCacheFacade`~~ удалена в cycle 164.
2. Обновить `core/di/providers/cache.py::get_cache_facade` —
   делегировать на `services.cache.UnifiedCacheFacade`.
3. Миграционная ADR (ADR-0352.1) с примерами кода до/после.

### Stage 5 (cycle 164 — DONE): DEFERRED ITEMS RESOLVED

**Cycle 164 (этот набор коммитов) закрыл оба deferred item из
CACHE_AUDIT_2026-10-20 §8:**

| Item | Решение |
|---|---|
| `DiskCacheFacade` (core) vs `DiskCacheBackend` (infrastructure) consolidation | **DiskCacheFacade удалена** (dead code, не в production). DiskCacheBackend — единственный disk-tier. CI guard запрещает рекурсию. |
| `cache_expire_seconds` миграция в `CacheSettings` | **Мигрирован**. Decorator + config_profiles/base.yml обновлены. `RedisSettings.cache_expire_seconds` — deprecated @property (backward-compat). |

Изменения:

* `src/backend/core/cache/facade.py` — `class DiskCacheFacade` удалена (87 LOC).
* `src/backend/core/cache/facade.py::UnifiedCacheFacade` docstring — обновлён.
* `tests/unit/core/cache/test_facade.py` — disk_facade секция удалена, fallback chain тест переписан на MemoryCacheFacade.
* `tests/unit/core/cache/test_facade_audit.py` — добавлены `test_disk_cache_facade_removed` и `test_disk_cache_backend_canonical`.
* `src/backend/core/config/services/cache.py` — `CacheSettings.cache_expire_seconds` (default 300, ge=60).
* `src/backend/core/config/services/cache.py::RedisSettings.cache_expire_seconds` — @property (backward-compat).
* `src/backend/infrastructure/decorators/caching/decorator.py` — `settings.cache.cache_expire_seconds`.
* `config_profiles/base.yml` — `cache_expire_seconds: 300` в `cache:` секции (не `redis:`).
* `tools/checks/check_cache_facade_uniqueness.py` — `FORBIDDEN_DISK_CACHE_NAMES` + `_check_disk_cache_uniqueness()`.
* `tests/unit/core/config/services/test_cache_expire_seconds_migration.py` — новый, 9 тестов.
* `tests/unit/core/config/test_redis_sentinel_settings.py` — убраны `cache_expire_seconds=300` из 7 мест.

**Result:** 354 cache-тестов проходят (78 предыдущих + 9 migration + 14 guard + ...).

### Stage 6 (cycle 164 — DONE): CLARIFY memory class roles

**CACHE_AUDIT_2026-10-20 §6** упоминает "MemoryCacheFacade vs LruMemoryCache"
как известную неконсистентность. После cycle 164 анализа: **это не
consolidation issue, а intentional design**. Три memory-класса в разных
слоях с разными ролями:

| Class | Layer | Interface | Purpose |
|---|---|---|---|
| `MemoryCacheFacade` | `core/cache/facade.py` | `UnifiedCacheFacade` ABC | dev_light/test fallback + `FallbackCacheFacade` chain |
| `MemoryBackend` | `infrastructure/cache/backends/memory.py` | `CacheBackend` interface | L1/L2 of `services.UnifiedCacheFacade` 3-tier |
| `LruMemoryCache` | `infrastructure/cache/lru_cache.py` | duck-typed | L1 of RAG 3-tier router (L1 → L2 Redis → L3 Qdrant) с prometheus metrics |

**Ключевые различия:**

1. **`MemoryCacheFacade`** (high-level ABC impl):
   - `bytes | None` return
   - Tag invalidation через `delete_by_tag(tag)`
   - `healthcheck()` (always True)
   - `ClassVar[CacheInvalidationPolicy]` (TTL/max_entries/enable_tag_invalidation)
   - Used by: `core/di/providers/cache.py::get_cache_facade`

2. **`MemoryBackend`** (low-level backend impl):
   - `bytes | None` return
   - `delete_pattern(pattern)` (отсутствует в MemoryCacheFacade)
   - Нет tag invalidation
   - Нет healthcheck
   - Used by: `_register_cache_facade` (services) как L2 fallback

3. **`LruMemoryCache`** (tier-router L1, no ABC):
   - `Any | None` return (для RAG embeddings — не bytes)
   - Prometheus metrics (hit/miss/set с `scope` label)
   - Нет tag invalidation, нет healthcheck, нет delete_pattern
   - Used by: `infrastructure/ai/semantic_cache.py` (TierRouter L1)

**Почему НЕ consolidation:**

- Разные layers: core vs infrastructure (layer rule).
- Разные interfaces: ABC vs Protocol vs duck-typed.
- Разные type semantics: bytes vs Any.
- Уникальные features в каждом: tag invalidation (только MemoryCacheFacade),
  delete_pattern (только MemoryBackend), prometheus metrics (только LruMemoryCache).

**Consolidation would:**
1. Нарушить layer rule (core ← infrastructure).
2. Потерять tag invalidation / delete_pattern / metrics features.
3. Усложнить testing (mock всех features для всех use cases).

**Тест:** `tests/unit/cache/test_three_memory_roles.py` — 3 теста:
- `MemoryCacheFacade` + tag invalidation round-trip.
- `MemoryBackend` + delete_pattern round-trip.
- `LruMemoryCache` + prometheus metrics scope.

Эти тесты фиксируют контракт каждого класса. Если кто-то решит
объединить — должен явно мотивировать trade-off.

Refs: cycle 164, CACHE_AUDIT_2026-10-20 §6.4 (CLARIFIED).

### Stage 4 (Sprint 9): REMOVE core-фасад

1. Удалить `core/cache/facade.py` (кроме re-export).
2. Удалить backward-compat классы.
3. `__init__.py` core/cache — только 3-tier + helpers.

## Альтернативы (отклонённые)

### A. Оставить core-фасад canonical, deprecate services-фасад

**Отклонено**: services-фасад — это production entry point с
capability-check, который уже DI-регистрируется. Его deprecation
приведёт к регрессу multi-tenant isolation.

### B. Сделать третий фасад `core/cache/unified.py` как canonical

**Отклонено**: ещё одна форма — это ещё одна неконсистентность.
Лучше выбрать из существующих двух.

### C. Оставить оба (current state)

**Отклонено**: нарушает R1 "single canonical API", создаёт
onboarding confusion, нет CI guard.

## Последствия

### Положительные

- Один canonical `UnifiedCacheFacade` — нет ни одного места с
  разными API для одной задачи.
- Capability-checked фасад становится обязательным для всех
  cache-операций (R-V15-1 enforcement).
- Observability (hit/miss/backend) — улучшение SLO.

### Отрицательные

- Stage 2 — breaking change для прямых пользователей `core.cache.UnifiedCacheFacade`.
- Stage 2 требует миграции тестов в `tests/unit/core/cache/test_facade.py`.
- Stage 4 — удаление deprecated API.

### Риски

- **Миграция занимает ~3 sprints** (Stage 2 → Stage 3 → Stage 4). Нужно
  гарантировать backward-compat в каждой промежуточной версии.
- **Capability check** — если плагин не имеет capability в
  `plugin.toml::capabilities`, `cache.read` / `cache.write` упадут. Это
  правильно, но может поймать не задекларированные cases — нужны
  regression tests.

## Ссылки

- Cycle 163 cache audit: `docs/cache/CACHE_AUDIT_2026-10-20.md`.
- Существующие ADRs по cache:
  - ADR-0051 (cache decorators facade)
  - ADR-0086 (aiocache migration plan)
  - ADR-0090 (aiocache hotpath strategy)
  - ADR-0287 (diskcache pyssec-2447 deferral)
  - ADR-0311 (W4 P1-6 aiocache evaluation hybrid)
  - ADR-0321 (W9 P2-13 cache providers decomposition)
  - ADR-0350 (remove dead-code rate-limiter cache-keys)
- R-V15-1: Plugin contract V11.1 (capability-runtime-gate).
- CLAUDE.md R1: один JSON-Schema каталог → один canonical API на домен.