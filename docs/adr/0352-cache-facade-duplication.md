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

### Stage 2 (Sprint 7+ Dev2): MERGE — один фасад

**Решение: оставить `services.cache.facade.UnifiedCacheFacade` как canonical,
перенести ABC-семантику из `core/cache/facade.py` через композицию.**

Обоснование:
1. Services-фасад DI-регистрируется → доступен через `get_service()` →
   правильный pattern для V15 multi-tenant production.
2. Services-фасад имеет capability check → обязательно для V15 R-V15-1
   (Plugin contract + capability-runtime-gate).
3. Services-фасад возвращает `CacheResult` → даёт observability
   (hit/miss/backend) для SLO / dashboard.
4. Namespace param в Services-фасаде → правильная изоляция между
   плагинами и тенантниками (особенно при работе с `tenant:{id}:` prefix).

**План merge:**

1. Создать `src/backend/core/cache/facade.py::UnifiedCacheFacade` как
   **alias** (re-export) на `services.cache.facade.UnifiedCacheFacade`:

   ```python
   # core/cache/facade.py
   from src.backend.services.cache.facade import (
       CacheResult,
       UnifiedCacheFacade,
   )
   ```

2. Перенести ABC-семантику (`MemoryCacheFacade`, `FallbackCacheFacade`,
   `RedisCacheFacade`, `DiskCacheFacade`) в `services/cache/facade.py`
   как **internal implementations**, НЕ re-exported из `core/cache/__init__.py`.

3. Сохранить `MemoryCacheFacade`, `FallbackCacheFacade`,
   `RedisCacheFacade`, `DiskCacheFacade` для backward-compat в
   `core/cache/facade.py` НО пометить как `Deprecated` (будут алиасы на
   новые internal implementations).

4. Добавить `namespace`, `cache_result` в `UnifiedCacheFacade` API
   (из Services-фасада).

5. Добавить `delete_by_tag` в Services-фасад (из Core-фасада) — для
   tag-invalidation parity.

6. **CI gate**: `tools/checks/check_cache_facade_uniqueness.py` —
   проверяет, что только два файла могут определять `UnifiedCacheFacade`:
   - `src/backend/core/cache/facade.py` (как re-export alias)
   - `src/backend/services/cache/facade.py` (canonical implementation)

### Stage 3 (Sprint 8): DEPRECATE core-фасад

1. В `core/cache/__init__.py` оставить только re-exports + deprecation
   warnings на `MemoryCacheFacade`, `FallbackCacheFacade`,
   `RedisCacheFacade`, `DiskCacheFacade`.
2. Обновить `core/di/providers/cache.py::get_cache_facade` —
   делегировать на `services.cache.UnifiedCacheFacade`.
3. Миграционная ADR (ADR-0352.1) с примерами кода до/после.

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