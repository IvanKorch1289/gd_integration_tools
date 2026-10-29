# ADR-0391 — Primary cache-тир, tenant-ключи и деградация кэша (волна 18, кластер G2)

* Статус: Accepted (2026-10-29, wave 18, кластер G2 — «КЭШИРОВАНИЕ»)
* Cycle: 178
* Дата: 2026-10-29
- **Затрагивает**:
  - `src/backend/infrastructure/cache/factory.py`
  - `src/backend/infrastructure/cache/invalidator.py`
  - `src/backend/infrastructure/cache/tenant_wrapper.py`
  - `src/backend/infrastructure/cache/backends/redis.py`
  - `src/backend/infrastructure/cache/backends/disk.py`
  - `src/backend/infrastructure/clients/storage/redis/cache_mixin.py`
  - `src/backend/infrastructure/decorators/caching/__init__.py`
  - `src/backend/dsl/engine/processors/ai/cache_processor.py`
  - `src/backend/dsl/engine/processors/ai/cachewrite_processor.py`
  - `src/backend/services/cache/facade.py`
  - `src/backend/core/config/services/cache.py`
  - `config_profiles/base.yml`
  - удалён `src/backend/core/tenancy/cache.py` (`TenantNamespacedCache`)
  - удалён `tests/unit/core/tenancy/test_cache_namespace.py`
- **Связан с**:
  - ADR-0100 (прецедент удаления мёртвого кода)
  - ADR-0352 (консолидация cache-настроек; `CacheSettings`)
  - ADR-0354 (tenant prefix через `TenantCacheBackend`)
  - ADR-0383/ADR-0387 (принципы «честный статус» и «удаление мёртвого кода»)
  - ADR-0284 (межслойные зависимости — новых нет)

## Контекст

Повторный аудит (волна 18) нашёл 8 дефектов в контуре кэширования:

1. **Redis не использовался вообще.** `infrastructure/cache/factory.py::_redis_client()`
   брал `getattr(client, "_raw_client", None) or getattr(client, "client", None)`.
   У `RedisClient` нет `_raw_client`, а property `client` возвращает `self` →
   в `RedisBackend` попадала обёртка → `AttributeError: 'RedisClient' object has
   no attribute 'get'` → кэш работал только как per-process L1 (в k8s — 100% miss).
2. **Multi-key UNLINK → CROSSSLOT.** `cache_mixin.py` удалял ключи пачкой
   (`unlink(*keys)`, батч до 500) — в RedisCluster это исключение (волна 13
   починила только `RedisBackend.delete`).
3. **Cross-tenant коллизия ключей.** `cache:{owner}:{func}:{sha256(args[1:])}` —
   tenant в ключ не входил, тогда как БД фильтруется по ContextVar-tenant'у.
4. **Ошибка фабрики роняла DSL-роут.** `cache_processor.py` ловил только
   `ImportError`; провайдер бросал `RuntimeError` («Memcached-бэкенд требует
   aiomcache»).
5. **Tag-инвалидация — no-op.** `CacheInvalidator._backends` был пуст,
   `add_backend()` в `src/` не вызывался → `invalidate()` всегда возвращал 0.
6. **`socket_timeout: 600`** в `base.yml` (prod/staging не переопределяли) —
   зависший Redis держал HTTP-запрос до 10 минут; `RedisBackend` шёл мимо
   `RedisClient.execute()` (там circuit breaker есть).
7. **Нет лимита размера значения** — произвольный orjson-дамп попадал в Redis.
8. **`delete_pattern_ns` не чистил disk-тир** (stale при падении Redis);
   мёртвый `core/tenancy/cache.TenantNamespacedCache` (0 usages в `src/`).

## Решение

1. **Фабрика отдаёт настоящий raw-клиент.** Добавлен публичный accessor
   `CacheMixin.raw_cache_client()` (сырой `redis.asyncio.Redis`; общий
   connection pool с `get_client('cache')`, создание — ленивое, без сетевого
   I/O). `factory._redis_client()` использует его; обёртка (`raw is client`)
   отвергается с понятным `RuntimeError`.
2. **UNLINK по одному ключу.** Хелпер `_unlink_each()` в `cache_mixin.py`
   удаляет ключи по одному (тот же приём, что в `RedisBackend.delete`) —
   CROSSSLOT не возникает.
3. **Tenant-сегмент в ключах декоратора.** `response_cache_key`,
   `metadata_cache_key`, `existence_cache_key` включают tenant из
   ContextVar (`_unscoped_`, если контекста нет) — согласуется с
   `TenantCacheBackend`.
4. **Деградация вместо падения.** `CacheProcessor`/`CacheWriteProcessor`
   ловят любое исключение провайдера фасада и ошибки чтения/записи →
   cache miss + warning, роут продолжает работу.
5. **Регистрация backend'ов.** `factory.create_cache_backend()` регистрирует
   созданный backend в глобальном `CacheInvalidator` (идемпотентно);
   `CacheInvalidator` получил публичное свойство `backends`.
   `TenantCacheBackend` научился проксировать `bind_key_to_tag`,
   `delete_by_tag`, `delete_by_pattern` — с tenant-префиксом, чтобы
   инвалидация не выходила за пределы тенанта.
6. **Разумный таймаут + CB.** `socket_timeout: 600 → 10`,
   `socket_connect_timeout: 60 → 5` в `base.yml` (prod/staging наследуют).
   Значение 10 с больше максимального blocking-таймаута
   (`stream_read: block_ms=5000`), иначе XREAD отвалился бы по сокету.
   `RedisBackend` обёрнут в `ClientCircuitBreaker` (`cache.redis`): после
   5 отказов fast-fail (`CircuitOpen`) → фасад сразу деградирует в
   memory/disk, не дожидаясь сокета.
7. **Лимит размера значения.** Новое поле `CacheSettings.max_value_bytes`
   (default 1 MiB, `config_profiles/base.yml: cache.max_value_bytes`).
   `UnifiedCacheFacade.set_ns` отклоняет превышение с `ValueError`
   («Cache value too large … exceeds max_value_bytes=…»); DSL-процессор
   ловит его и пишет warning.
8. **Disk-тир чистится; мёртвый код удалён.** `DiskCacheBackend` держит
   in-memory индекс записанных ключей и умеет `delete_pattern` (раньше был
   no-op) → `delete_pattern_ns` чистит primary + memory + disk.
   `core/tenancy/cache.py::TenantNamespacedCache` удалён (0 usages, прецедент
   ADR-0100) вместе со своим тестом; docstring-ссылка в
   `tenant_wrapper.py` обновлена.

## Альтернативы (отклонённые)

1. **Оставить `_raw_client`/`.client` и «починить» RedisClient.** Отклонено:
   `.client` — это backward-compat self-reference для
   `redis_client.client.*`; менять его ломало бы чужие вызовы. Добавлен
   отдельный accessor с честным именем.
2. **Pipeline с per-key командами вместо gather по одному ключу.** Отклонено
   сейчас: pipeline в cluster-режиме разносит команды по нодам, но требует
   адаптации под `RedisCluster.pipeline()`; выигрыш — один RTT вместо N —
   не покрывает риск регрессий в cluster-режиме. Зафиксировано как путь
   апгрейда (ponytail-комментарий в коде).
3. **Фабрика деградирует в `MemoryBackend` при недоступном backend'е.**
   Отклонено: `create_cache_backend` — это явный контракт (провайдер бросает
   `RuntimeError` с подсказкой), менять его поведение — ломать существующие
   тесты и прятать конфигурационные ошибки. Деградация сделана на уровне
   DSL-процессора (пункт 4) — там, где ошибка действительно не должна ронять
   роут.
4. **CB на пути фасада через `RedisClient.execute()`.** Отклонено: фасад
   работает с raw-клиентом (пункт 1), а `execute()` — async и живёт на
   `RedisClient`; связать их без async-конструктора фасада нельзя. CB
   добавлен на уровне `RedisBackend` — та же точка отказа, тот же fast-fail.
5. **Оставить `TenantNamespacedCache` «на будущее».** Отклонено: 0
   потребителей в `src/`, нет публичного реэкспорта, дублирует
   `TenantCacheBackend` — прецедент ADR-0100 (удаление).

## Последствия

* **Позитивные:** Redis снова работает как primary-тир (в k8s — общий кэш
  между подами, а не per-process L1); ключи tenant-изолированы на всех
  трёх key-builder'ах декоратора; падение фасада кэша не роняет DSL-роут;
  tag/pattern-инвалидация перестала быть no-op; зависший Redis больше не
  держит запрос 10 минут (10 с socket + fast-fail по CB); в Redis не попадает
  мусор больше 1 MiB; stale в disk-тире чистится pattern-инвалидацией.
* **Негативные:** `UNLINK`/`DEL` по одному ключу — до N round-trip'ов на
  батч (осознанный размен на cluster-корректность); in-memory индекс ключей
  disk-бэкенда живёт в пределах процесса (после рестарта ранее записанные
  ключи pattern-delete не заденет — апгрейд: on-disk индекс);
  `socket_timeout=10` меньше прежних 600 — операции, которым нужен
  длинный blocking (>10 с), должны использовать отдельный kind-клиент.
* **Вне зоны (чужие файлы):**
  - `src/backend/plugins/composition/service_setup.py` — регистрация
    memory/disk fallback'ов в `CacheInvalidator` не выполнялась (вне зоны);
    primary-регистрация сделана в фабрике.
  - `src/backend/core/di/providers/cache.py` — провайдер фасада по-прежнему
    ловит только `(KeyError, ImportError)`; деградация добавлена на стороне
    DSL-процессоров (пункт 4), поэтому менять провайдер не требовалось.
  - `src/backend/core/tenancy/cache.py` удалён, но
    `.claude/DECISIONS.md` / `.claude/KNOWN_ISSUES.md` содержат исторические
    упоминания модуля — исторические документы не переписываются.
  - `docs/adr/INDEX.md` — индекс ADR обновляется генератором
    (`tools/build_adr_index.py`), в этой задаче не редактировался.

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/cache tests/unit/services/cache \
    tests/unit/dsl/engine/processors/ai/test_cache_processor.py \
    tests/unit/dsl/engine/processors/ai/test_cachewrite_processor.py \
    tests/unit/infrastructure/decorators/caching \
    tests/unit/infrastructure/clients/storage/redis -q -p no:randomly
.venv/bin/python -m ruff check src/backend/infrastructure/cache \
    src/backend/infrastructure/clients/storage/redis \
    src/backend/infrastructure/decorators/caching \
    src/backend/dsl/engine/processors/ai \
    src/backend/services/cache src/backend/core/config/services/cache.py \
    tests/unit/infrastructure/cache tests/unit/services/cache \
    tests/unit/dsl/engine/processors/ai/test_cache_processor.py \
    tests/unit/dsl/engine/processors/ai/test_cachewrite_processor.py
.venv/bin/python tools/config_audit.py --scope orphans
.venv/bin/python tools/check_layers.py --strict
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
```

Результат на момент сдачи: `376 passed, 1 skipped` (pytest), ruff — clean,
`config_audit --scope orphans` — 0, `check_layers --strict` — 41 (baseline),
`check_docstrings` — 1 пропуск в чужом файле
(`src/backend/dsl/builders/infra_logging_mixin.py`, вне зоны G2).

## Связи с другими ADR

* **ADR-0100** — прецедент удаления мёртвого кода (`TenantNamespacedCache`).
* **ADR-0352** — `CacheSettings` как единственный источник cache-настроек
  (сюда добавлен `max_value_bytes`).
* **ADR-0354** — tenant prefix через `TenantCacheBackend`; wave 18 дополнил
  его tag/pattern-инвалидацией и tenant-ключами в декораторе.
* **ADR-0387** — «честный статус вместо зелёного»: падение кэша деградирует
  с warning, а не маскируется; мёртвый код удалён с обоснованием.
* **ADR-0284** — новых межслойных импортов не добавлено (`infrastructure` →
  `infrastructure`/`core`, `services` → `core`).
