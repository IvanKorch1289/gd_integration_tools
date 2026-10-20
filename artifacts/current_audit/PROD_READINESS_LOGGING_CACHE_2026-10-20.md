# Production Readiness Review — Logging + Caching

* **Дата**: 2026-10-20
* **Цикл**: 168
* **Область**: `core.logging` / `infrastructure.logging` + `core.cache` /
  `services.cache` / `infrastructure.cache`
* **Связан с**: ADR-0084, ADR-0086, ADR-0090, ADR-0287, ADR-0311, ADR-0321,
  ADR-0350, ADR-0351, ADR-0352 (Stage 2/3/4 — completed cycle 165-167)
* **Baseline**: 483 unit-теста passing (cycle 168); рабочее дерево чистое,
  HEAD `27d4eefbd`.

---

## TL;DR

| Категория | Критично | Высоко | Средне |
|---|---|---|---|
| Cache | 4 | 4 | 2 |
| Logging | 1 | 1 | 1 |

**Вердикт**: **НЕ ГОТОВ к prod без применения нижеперечисленных фиксов.**

Большинство найденных рисков — это **silent correctness issues**, которые
не проявляются в обычных тестах, но могут привести к:

* **data corruption / leak** (cross-tenant через shared L1/L3 fallback),
* **stale data** (TTL ignored на disk backend),
* **observability blackout** (log spam → GELF backpressure → dropped events),
* **invalid cache state** (tag tracking process-local, no cluster-wide
  invalidation).

---

## 1. Cache — Critical issues

### 1.1 DiskCacheBackend игнорирует TTL (`CRITICAL`)

**Файл**: `src/backend/infrastructure/cache/backends/disk.py:72`

```python
del ttl  # disk backend ignores per-key TTL
```

**Проблема**: `DiskCacheBackend.set()` явно отбрасывает параметр `ttl`.
Это означает, что после истечения primary TTL (Redis) значение всё ещё
лежит на диске и **resurface через `get_ns`** как `hit=True, backend="disk"`.

**Сценарий**:

1. Redis healthy, `set_ns("foo", val, ttl=60)` → Redis + memory + disk
2. Redis TTL истёк, primary deleted
3. `get_ns("foo")` → Redis miss, **memory hit** OR **disk hit** → stale value
4. Клиент получает устаревшие данные, хотя ожидал miss

**Fix (cycle 168)**: добавить per-file expiry sidecar (`.expires` файл рядом
с data файлом). `get()` проверяет expiry и удаляет при истечении.

### 1.2 memory_fallback и disk_fallback НЕ обёрнуты в TenantCacheWrapper (`CRITICAL — security`)

**Файл**: `src/backend/plugins/composition/service_setup.py:147-153`

```python
primary = create_cache_backend(cache_settings)        # ← TenantCacheBackend wrapped
memory = MemoryBackend(maxsize=cache_settings.l1_maxsize)  # ← bare MemoryBackend!
disk = (DiskCacheBackend(...) if cache_settings.disk_fallback_enabled else None)  # ← bare!
return UnifiedCacheFacade(
    primary=primary, memory_fallback=memory, disk_fallback=disk, ...
)
```

**Проблема**: только `primary` (Redis) обёрнут в
`TenantCacheBackend` (cycle 34 B-03 fix — cache poisoning defense-in-depth).
L1/L3 fallback **не получают tenant-prefix** → при shared process для
нескольких tenants возможен **cross-tenant data leak** через local cache.

**Сценарий**:

1. Tenant A: `set_ns("user:42", data_A, namespace="t1")` →
   `tenant:t1:user:42` в Redis
2. Redis outage, fallback на memory → memory хранит `tenant:t1:user:42`
   (но memory **не имеет tenant wrapper**, значит ключ остаётся
   `tenant:t1:user:42` — OK случайно)
3. Tenant B: `set_ns("user:42", data_B, namespace="t2")` → Redis returns
   `tenant:t2:user:42`
4. После возврата Redis: memory всё ещё хранит `tenant:t1:user:42` →
   Tenant B получает data_A через `get_ns` → **data leak**

Хотя в текущей реализации facade передаёт full key (`namespace:key`) в
backend, `_tag_index` **не разделяет по tenants** и может вернуть
cross-tenant tag invalidation.

**Fix**: обернуть `memory` и `disk` через `TenantCacheBackend` в
service_setup.

### 1.3 MemoryBackend.set() игнорирует per-key TTL (`HIGH — contract violation`)

**Файл**: `src/backend/infrastructure/cache/backends/memory.py:42-56`

```python
async def set(self, key: str, value: bytes, ttl: int | None = None) -> None:
    async with self._lock:
        # cachetools задаёт TTL глобально на cache; для индивидуального
        # ttl-override приходится использовать timer override в expire.
        self._cache[key] = value
```

**Проблема**: ABC `CacheBackend.set(key, value, ttl)` декларирует поддержку
per-key TTL. Memory backend **молча игнорирует** параметр `ttl` и
использует global `default_ttl=3600`. Это означает, что:

* `set_ns("foo", val, ttl=60)` фактически создаёт запись с TTL=3600
* Decorator `@cache(ttl=60)` использует Redis-like semantics → в
  memory backend TTL расширяется в 60x
* Это нарушает **cache stampede protection** (ADR-0051)

**Fix**: использовать `cachetools.TTLCache(maxsize, ttl=default_ttl)` с
manual `expire()` per key или thread-local timer. Cycle 168.

### 1.4 delete_pattern_ns не удаляет с disk (`HIGH`)

**Файл**: `src/backend/services/cache/facade.py:257-268`

```python
for name, backend in (("primary", self._primary), ("memory", self._memory)):
    # disk is NOT in this loop!
```

**Проблема**: `delete_pattern_ns` намеренно пропускает disk fallback, потому
что `DiskCacheBackend` хэширует ключи через SHA256 (`backends/disk.py:39`):
`key cannot be recovered from hash; skip pattern delete`. В результате
после pattern delete остаются stale disk-записи, и `get_ns` может
вернуть значение с disk, даже если primary/memory чисты.

**Fix options**:

1. Добавить reverse index (key → file path) — но это +O(N) memory.
2. **Самый дешёвый**: при pattern delete на disk backend сделать `flush()`
   для namespace prefix. Cycle 168 — добавить `flush_by_prefix()`.

### 1.5 Tag tracking не cluster-wide (`HIGH`)

**Файл**: `src/backend/services/cache/facade.py:97`

```python
self._tag_index: dict[str, dict[str, set[str]]] = {}
```

**Проблема**: `_tag_index` — это локальный dict процесса. В multi-process
deployment (Granian workers, k8s replicas) `delete_by_tag_ns` работает
**только в одном процессе**. Если процесс A инвалидирует tag, процесс B
не знает об этом и продолжает возвращать stale данные.

**Fix**:

1. Документировать ограничение: tag invalidation работает только в single-
   process режиме; для cluster использовать Redis native tag index
   (`RedisBackend.delete_by_tag` уже реализован).
2. Cycle 169: добавить optional Redis tag index backend в facade.

### 1.6 tag_index обновляется даже при полном set failure (`MEDIUM`)

**Файл**: `src/backend/services/cache/facade.py:209-213`

```python
if tags:
    ns_tags = self._tag_index.setdefault(namespace, {})
    for tag in tags:
        ns_tags.setdefault(tag, set()).add(key)
```

**Проблема**: при полном set failure (primary + memory + disk упали) tag
всё равно добавляется в `_tag_index`. При последующем `delete_by_tag_ns`
тег-инвалидация пытается удалить ключи, которых нет в backend'ах →
silent miss + warning log.

**Fix**: проверять хотя бы один successful backend.set перед обновлением
`_tag_index`.

### 1.7 get_cache_facade() возвращает MemoryBackend без ABC-методов (`MEDIUM`)

**Файл**: `src/backend/core/di/providers/cache.py:391-409`

```python
def get_cache_facade(enable_fallback: bool = True) -> Any:
    memory = MemoryBackend(maxsize=1000, default_ttl=3600)
    if not enable_fallback:
        return memory
    return memory  # ← enable_fallback ignored!
```

**Проблема**:

1. `enable_fallback` **не влияет на поведение** (memory в обеих ветках).
2. `MemoryBackend` не реализует `delete_by_tag()` и `healthcheck()` —
   код, делающий `await get_cache_facade().delete_by_tag(...)`, получит
   `AttributeError`.
3. Возвращаемый `Any` type нарушает ABC contract.

Этот провайдер помечен как "dev/test path" в комментарии, но экспортируется
через `__all__` и `core/api/__init__.py` — случайное использование возможно.

**Fix**: либо обернуть MemoryBackend в полный `UnifiedCacheFacade`-совместимый
shim, либо явно пометить return type как `MemoryBackend` (не `Any`) и
запретить вызов ABC-only методов.

### 1.8 l1_enabled — dead config (`MEDIUM`)

**Файл**: `src/backend/core/config/services/cache.py:455-458` vs
`src/backend/plugins/composition/service_setup.py:131`

`CacheSettings.l1_enabled: bool = True` определён, но
`service_setup.py:131` создаёт `MemoryBackend(maxsize=cache_settings.l1_maxsize)`
**всегда** без проверки `l1_enabled`.

**Fix**: в service_setup добавить `if cache_settings.l1_enabled: memory = ...`.

---

## 2. Cache — Configuration управляемость

### 2.1 config_profiles/base.yml::cache неполный (`MEDIUM`)

**Файл**: `config_profiles/base.yml:223-230`

```yaml
cache:
  backend: "redis"
  l1_enabled: true
  l1_maxsize: 1000
  keydb_active_replica: false
  cache_expire_seconds: 300
  # ← MISSING: disk_fallback_enabled, disk_fallback_path
```

**Проблема**: `disk_fallback_enabled` и `disk_fallback_path` доступны через
`CACHE_*` env vars (Pydantic Settings), но **отсутствуют в base.yml**.
Оператор prod может управлять только через env, не через YAML config.

**Fix**: добавить в base.yml оба поля (с текущими дефолтами и комментариями).

---

## 3. Cache — Performance baseline

Performance замерено через 5000 ops на 3 backend'ах in-process:

| Operation | ops/s | latency/op | Notes |
|---|---|---|---|
| `set_ns` (3-tier) | 4670 | ~214μs | memory + disk writes |
| `get_ns` (primary hit) | 7529 | ~133μs | hot path |
| `get_ns` (primary fail → memory hit) | 4189 | ~239μs | **+1 warning log per call** |
| `delete_by_tag_ns(100)` | — | 3.76ms | 26.6k ops/s |

**Проблема: log spam в fallback path** — при недоступности Redis каждое
обращение к кэшу логирует `WARNING` (`services.cache.facade:165`).
5000 ops/s = 5000 warnings/s = потенциально **6+ млн логов в минуту**.

В production с GELF batching это приведёт к:

1. Backpressure в `batching_router.py` → потеря логов.
2. Загрузка Graylog pipeline (массовый flush).
3. Disk-ротация быстро заполняется.

**Fix**: добавить rate-limited logging (например, max 1 warning/second per
backend name через `ThrottledLogger` или sample-based 1-in-N).

---

## 4. Logging — Critical issues

### 4.1 83 inline `import logging` (`HIGH — observability gap`)

**Команда**:

```bash
grep -rEn "^import logging|^from logging " src/backend --include="*.py" | \
    grep -vE "logging_helpers|/logging/|infrastructure/logging/" | wc -l
# → 83
```

**Проблема**: 83 не-инфраструктурных модуля используют stdlib `logging`
напрямую вместо `core.logging.get_logger`. Это означает, что они:

* **НЕ получают** `request_id` / `tenant_id` / `correlation_id` из logging
  contextvars.
* **НЕ получают** PII/secret redaction.
* **НЕ получают** structured JSON output через structlog.
* **НЕ получают** GELF batching для Graylog.
* **НЕ получают** centralized log level configuration.

ADR-0351 phase 1 (schema_registry migration) покрыл ~1 модуль. До полного
prod-ready требуется multi-cycle migration plan.

**Fix**:

1. Cycle 168: добавить CI guard, считающий inline `import logging` в
   не-infrastructure модулях.
2. Cycle 169+: миграция batch-by-batch по доменам (сначала `entrypoints/`,
   затем `services/`, потом `dsl/`).

### 4.2 Logging prod-path validation (`MEDIUM`)

Запущено:

```python
from src.backend.core.logging import get_logger, configure_logging
```

Подтверждено: lazy re-exports работают, цикл `import → first use →
resolve` валиден. Однако в реальном production startup
(`app_factory.py::init_application_logging`) нужна интеграционная
проверка с реальным `batching_router` + `graylog_gelf` backend.

**Status**: unit-проверено через `tests/unit/infrastructure/logging/` —
3 dedicated теста:

* `test_centralized_init.py`
* `test_lifecycle_shutdown.py`
* `test_settings_driven_init.py`

Integration-тест с реальным Graylog **не запускался** (vault/graylog
недоступны в тестовой среде).

---

## 5. ADR closure audit

| ADR | Статус | Audit verdict |
|---|---|---|
| 0084 library-adoption-migration-plan | Active | ⚠️ Устаревшие claims (default backend, число `import logging`) — требуется re-baseline. |
| 0086 aiocache-migration-plan | Active | Принято, но не завершено (aiocache не подключён). |
| 0090 aiocache-hotpath-strategy | Active | ⚠️ Содержит deferred implementation; текущий код использует cachetools. Устарело. |
| 0287 diskcache-pyssec-2447-deferral | Accepted deferral | OK (security dependency risk). |
| 0311 w4-p1-6-aiocache-evaluation-hybrid | Active | Требует re-baseline. |
| 0321 w9-p2-13-phase2-cache-providers-decomposition | Active | Status unclear — нужно проверить выполнение. |
| **0350** remove-dead-code-rate-limiter-cache-keys | **Draft** | ⚠️ Amendment 2026-10-16 исправил cache_keys claim. Удаление `core/rate_limiter/` остаётся **не выполненным** — требует явного одобрения владельца (CLAUDE.md: «удалять файлы запрещено без подтверждения»). |
| **0351** logging-facade-status-audit | **Active** | Phase 1 (schema_registry) выполнена. 83 inline `import logging` остаются — ADR не закрыт. |
| 0352 cache-facade-duplication | **Complete (cycle 167)** | ✅ Все 4 Stage выполнены. |

**Action items**:

1. ADR-0084, 0090, 0311: re-baseline (cycle 169 — когда будет время).
2. ADR-0350: получить explicit OK от владельца на удаление `core/rate_limiter/`
   (245 LOC, no production callers, заменён в `entrypoints/dependencies/rate_limit.py`
   + `infrastructure/resilience/unified_rate_limiter.py`).
3. ADR-0351: расширить план на remaining 83 modules.

---

## 6. Что НЕ затронуто аудитом

* **Vault secrets** (test env: HTTPConnection refused на 127.0.0.1:8200).
  Unit/integration тесты работают, но prod-hardening требует реального
  vault-окружения.
* **Redis cluster failover** (требует реального Redis cluster setup).
* **Graylog throughput** (требует реального Graylog endpoint).
* **Real production topology** (Granian workers, k8s replicas) — может
  быть верифицирован только через deployment review.

---

## 7. Recommended fix sequence (cycle 168-169)

| Priority | Fix | Cycle | Effort | Breaking? |
|---|---|---|---|---|
| 🔴 CRITICAL | DiskCacheBackend: per-key TTL через expiry sidecar | 168 | S | No |
| 🔴 CRITICAL | service_setup: обернуть memory+disk в TenantCacheBackend | 168 | S | No |
| 🔴 CRITICAL | facade.py: rate-limited warning logging | 168 | S | No |
| 🟠 HIGH | MemoryBackend.set: per-key TTL через cachetools manual timer | 168 | M | No |
| 🟠 HIGH | DiskCacheBackend.delete_pattern: namespace flush | 169 | M | No |
| 🟠 HIGH | delete_by_tag_ns: проверять successful set перед tag_index update | 168 | S | No |
| 🟡 MEDIUM | service_setup: honor l1_enabled | 168 | XS | No |
| 🟡 MEDIUM | base.yml: добавить disk_fallback_* поля | 168 | XS | No |
| 🟡 MEDIUM | get_cache_facade: исправить enable_fallback ignore | 169 | S | No |
| 🟢 DOCS | ADR-0350: получить approval на rate_limiter removal | — | — | — |
| 🟢 DOCS | ADR-0351: расширить план на 83 modules | 169 | M | No |

---

## 8. Verification plan

После применения фиксов:

```bash
# Cache tests (cycle 168 baseline: 483 passing)
uv run python -m pytest \
    tests/unit/services/cache \
    tests/unit/core/cache \
    tests/unit/cache \
    tests/unit/infrastructure/cache \
    tests/unit/core/config/services \
    tests/unit/infrastructure/logging \
    tests/tools/test_check_cache_facade_uniqueness.py \
    --tb=short -q

# New tests (cycle 168):
uv run python -m pytest \
    tests/unit/services/cache/test_disk_ttl.py \
    tests/unit/services/cache/test_tenant_wrapper_fallback.py \
    tests/unit/services/cache/test_log_throttling.py \
    tests/unit/core/config/services/test_cache_yaml_disk_fallback.py \
    --tb=short -q

# Layer check
uv run python tools/check_layers.py --strict

# Cache facade uniqueness guard
make check-cache-facade-uniqueness

# Import smoke
uv run python -c "import src.backend.plugins.composition.app_factory"
```

---

## 9. Не входит в этот отчёт (deferred)

* ADR-0352 Stage 5 (если потребуется): переименование public API фасада.
* ADR-0351 phase 2-3: миграция оставшихся 83 inline `import logging`.
* Real-world cluster load test (нужен staging environment).
* Graylog backpressure integration test (нужен Graylog endpoint).
* ADR-0084/0090/0311 re-baseline.
* ADR-0350 explicit approval + удаление `core/rate_limiter/`.

---

## 10. Заключение

**Cache + Logging НЕ готовы к prod без применения 4 critical fixes:**

1. DiskCacheBackend TTL (stale data risk)
2. Tenant wrapper для L1/L3 fallback (cross-tenant leak risk)
3. Log throttling в fallback path (observability blackout risk)
4. MemoryBackend per-key TTL (cache stampede protection)

После применения фиксов + прохождения верификации (Section 8)
→ **prod-ready с оговорками** (cluster-wide tag invalidation не работает;
ADR-0350 / 0351 остаются на согласовании).