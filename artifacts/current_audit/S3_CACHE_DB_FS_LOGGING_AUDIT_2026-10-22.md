# S3 / Cache / Database / Filesystem-scanning / Logging — Production-Readiness Audit

**Date**: 2026-10-22
**Cycle**: 172
**Base**: HEAD `1d9f2c0a9` (post cycle-171)
**Branch**: `audit/s3-cache-logging-cycle-171` (продолжается)
**Scope**: S3/object storage, cache, **internal + external DB**, **filesystem scanning**, logging
**Method**: grilling (3 rounds, 12 decisions) + 2 dispatched fact-finders + direct code
verification + runtime proof

---

## 0. Executive verdict

**Цикл 171 закрыл S3/кэш/логи частично и оставил два неверных утверждения в
собственном отчёте.** Главное открытие цикла 172 — не в S3, а в двух подсистемах,
которые **никогда не аудировались**: база данных и сканирование файловой системы.

| Подсистема | Вердикт | Критичность находок |
|---|---|---|
| **S3 / object storage** | ⚠️ **Бэкенд неработоспособен в среде** (`aioboto3` не объявлен и не установлен). Весь объём правок цикла 171 существует, но не проверяем. | 1 CRITICAL, 2 HIGH |
| **Cache** | ⚠️ **Основное — правда**, но `delete_by_tag` в Redis-кластере тихо ломается, `policy.cache_policy()` — no-op без предупреждения | 2 HIGH, 1 MEDIUM |
| **Database (internal)** | 🔴 **Весь DB-DSL мёртв.** `get_db_manager` не существует → `db_query`/`db_insert`/`db_update`/`db_upsert`/`db_delete` падают на каждом вызове. Прод-БД без TLS. | 4 CRITICAL, 8 HIGH |
| **Database (external)** | 🔴 **PG→SQLite failover-цепочка неимпортируема**; внешние профили поддерживают только PG+Oracle при рекламируемых 7 | 2 CRITICAL, 4 HIGH |
| **Filesystem scanning** | 🔴 **YAML `watch_files` сканирует любой каталог хоста** — без capability-гейта и без path-allowlist. `directory_scan` всегда умирает по deny-by-default, тест это маскирует. | 2 CRITICAL, 6 HIGH |
| **Logging** | ✅ Основное цикла 171 — правда и проверено. Остаточный долг — стиль (86 inline `import logging`). | 0 CRITICAL, 0 HIGH |

**Итог**: 58 дефектов, из них **9 CRITICAL**. Два из них (мёртвый DB-DSL и
негейтный FS-сканер) означают, что заявленные в `ARCHITECTURE.md` и `CLAUDE.md`
возможности отсутствуют в рантайме.

---

## 1. Methodology note — claims were verified, not trusted

Цикл 171 зафиксировал два процесса-правила, которые цикл 172 расширил третьим.

**1.1 Цикл 171 содержит ложное утверждение о собственной работе.**
Отчёт §8 и §8 «Regression evidence» утверждают:

> «7d8f07268 — Wave 0 — restore S3 test evidence»;
> «The branch consistently shows *fewer* failures than `master`, consistent with
> Wave 0 restoring `moto` and converting 24 silently-skipped S3 tests into a real
> suite».

Фактически на HEAD:

```
$ pytest tests/unit/storage/ -q
SKIPPED [1] tests/unit/storage/test_s3_object_storage.py:40:
  aioboto3 undeclared: aiobotocore pins boto3/botocore incompatible with uv.lock 1.43.75
38 passed, 1 skipped
```

`moto[s3]` действительно добавлен в `pyproject.toml:413`, но `aioboto3` не
установлен, поэтому тест **пропускается на 100%**. Причинно-следственная связь
«добавили moto → тесты стали реальными» ложна: тест упирается в `aioboto3`, а не
в `moto`. Вывод «branch показывает меньше падений» — не следствие Wave 0.

**1.2 «Заблокированный» CRITICAL-05 оказался разрешимым.**
Отчёт 171 утверждал: *«aiobotocore pins boto3/botocore to narrow ranges that are
incompatible with the boto3/botocore 1.43.75 pinned in uv.lock»*. Проверка на
PyPI (первичный источник) даёт иную картину:

| Пакет | Версия | Ограничение на botocore | Совместимо с 1.43.75? |
|---|---|---|---|
| `aiobotocore` | 3.9.1 (2026-09-07) | `botocore<1.43.76,>=1.43.66` | ✅ **да** |
| `aiobotocore` | 2.25.1 (2025-10-28) | `botocore<1.40.62,>=1.40.46` | ❌ нет |
| `aioboto3` | 15.5.0 (2025-10-30) | → `aiobotocore[boto3]==2.25.1` | ❌ нет |

**Суть блокера верна, формулировка — нет.** Ни один опубликованный `aioboto3` не
совместим с `botocore 1.43.75`, потому что весь `aioboto3` (12.x–15.x) жёстко
пинит `aiobotocore==2.x`. Но `aiobotocore 3.9.1` **уже находится в `uv.lock`
(транзитивно) и уже установлен**, и он совместим. `aiobotocore` предоставляет
`get_session().create_client(...)` — drop-in для `aioboto3.Session().client(...)`:
все используемые kwargs (`service_name`, `endpoint_url`, `aws_access_key_id`,
`aws_secret_access_key`, `config`, `use_ssl`, `verify`) присутствуют в сигнатуре
`botocore.session.Session.create_client`.

> **Process rule 3 (новое)**: утверждение «зависимость несовместима» проверяется
> запросом к PyPI по реальным метаданным (`requires_dist`) цепочки, а не по
> версии верхнего пакета.

**1.3 Два расхождения с dispatched fact-finder'ом.** Оба исправлены по коду:
(а) explorer утверждал, что `pytest-timeout` **не установлен** и 7 маркеров
`@pytest.mark.timeout(5)` инертны — фактически `pytest_timeout` **найден** в
`.venv`; (б) explorer считает `pool_monitor.py:80` опечаткой — она опечаткой
**является**, но в том же файле на строке 144 написано правильно, что
подтверждает дефект, а не опровергает его.

---

## 2. S3 findings

### 🔴 CRITICAL-06 — бэкенд S3 неработоспособен; весь объём правок 171 не проверяем
- **Where**: `infrastructure/storage/s3.py:49-57,125`; `pyproject.toml` (нет в `[project.dependencies]`)
- **What**: `aioboto3` отсутствует и в `pyproject.toml`, и в `uv.lock`, и в `.venv`.
  `S3ObjectStorage.__init__` вызывает `_import_aioboto3().Session()` → `ImportError`.
  В проде это приводит к `ProductionConfigError` (провайдер не может подняться),
  в dev/staging — к тихой деградации в LocalFS.
- **Evidence**: `ModuleNotFoundError: No module named 'aioboto3'`; `uv.lock` содержит
  только `aiobotocore 3.9.1`, `grep 'name = "aioboto3"' uv.lock` → пусто.
- **Impact**: **тесты S3 — единственный реальный тест-сьют бэкенда — пропускаются
  полностью.** Все «FIXED»-статусы цикла 171 по S3 (CRITICAL-01/02/03, HIGH-02/03/04,
  MEDIUM-01/02) не имеют исполненной доказательной базы.
- **Fix**: переход на `aiobotocore` (см. §1.2) — конфликта версий нет.

### 🔴 HIGH-01 (подтверждён, не закрыт) — пул соединений по-прежнему мёртв
- **Where**: `s3.py:152-154` (`_open`), `s3.py:80-90` (`_S3Session.__aenter__`)
- **What**: план 171 выбрал механизм «один долгоживущий `aioboto3.Session`» —
  он **не решает задачу**. `Session` владеет *ресурсами*, а **пул соединений живёт
  в клиенте**. `_S3Session.__aenter__` вызывает `self._session.client(**kwargs)` —
  новый клиент на каждую операцию — и закрывает его в `__aexit__`.
  `max_pool_connections=20` применяется к пулу, который умирает сразу.
- **Evidence**: `s3.py:81` — `self._cm = self._storage._session.client(**...)`.
- **Self-documented**: докстринг `s3.py:113-114` прямо признаёт «Соединение
  устанавливается на каждую операцию». То есть дефект задокументирован, но в
  плане 171 помечен как закрытый выбором неработающего механизма.

### ⚠️ HIGH-05 — `s3_cache.py` несовместим с production-бэкендом
- **Where**: `infrastructure/storage/s3_cache.py:40-47,223`
- `S3ClientProtocol` требует `get_object_bytes(key)`; `S3ObjectStorage` такого
  метода **не имеет** (`grep get_object_bytes s3.py` → пусто). Адаптер
  read-through-кэша не может работать с production-бэкендом.

### ⚠️ MEDIUM-06 — DSL-контролируемый `endpoint_url` в `from_s3`
- **Where**: `dsl/builders/eip/sources.py:363-369`
- `from_s3(bucket, key, endpoint_url=...)` принимает endpoint из DSL → SSRF-поверхность.

### ✅ Проверено как исправленное (цикл 171) — подтверждено кодом
| Finding | Доказательство |
|---|---|
| CRITICAL-01 fail-open → fail-closed для багов | `fallback.py` — суженный `fallback_exceptions`, ERROR-лог, метрика, quarantine |
| CRITICAL-02 квота | `facade.py:148` `_check_quota` вызывается в `upload` |
| CRITICAL-03 tenant-изоляция ключей | `infrastructure/storage/tenant_wrapper.py` (152 LOC) |
| HIGH-02 YAML→S3 | `dsl/builders/infrastructure_dsl.py:475-542` — `to_s3`/`s3_get`/`s3_presign`/`s3_delete`/`s3_list` |
| HIGH-03 capability-gate | `dsl/engine/processors/storage/s3.py` — гейт резолвится из registry |
| MEDIUM-01 `ServiceError` | `s3.py:187-199` — `BotoCoreError` обёрнут |
| MEDIUM-02 SSE + presign TTL | `core/config/services/storage.py:133-149` — `server_side_encryption`, `presign_ttl_max_seconds` |
| HIGH-08 `DiskCache.exists` TTL | `cache/backends/disk.py` |

---

## 3. Cache findings

### 🔴 HIGH-07 (подтверждён, не закрыт) — `delete_by_tag` не работает в Redis-кластере
- **Where**: `infrastructure/cache/backends/redis.py:107-132`
- `await self._client.delete(*str_keys)` — один клиент, много ключей. На
  `RedisCluster` ключи в разных hash-слотах → `CROSSSLOT`. Fan-out по узлам
  отсутствует.
- **Doc**: cycle 170 предлагал этот метод как cluster-wide обходной путь; cycle 171
  исправил документ, но не код.

### ⚠️ MEDIUM-05 — `policy.cache_policy()` — no-op без предупреждения
- **Where**: `dsl/builders/policy_mixin.py:61-73`
- Добавляет `PolicyMarkerProcessor`; `CacheProcessor` не запускается. Код,
  полагающийся на ADR-0355, **молча** теряет кэширование.
- **Signature incompatibility**: реальный `RouteBuilder.cache(key_fn: Callable, *, ttl)`
  (`dsl/builders/ai_rpa/rpa.py:251`) и `policy.cache_policy(key: str, backend: str)`
  несовместимы → делегирование невозможно без нового string-key процессора.

### ⚠️ MEDIUM-03 — presigned-URL не разграничены по правам
- **Where**: `services/storage/facade.py:240-247`
- Проверяется только `storage.read`. В vocabulary есть лишь `storage.read` /
  `storage.write` — отдельного права на выдачу ссылок нет. Внутри тенанта любой
  плагин с `storage.read` может получить URL на любой ключ.

### ✅ Проверено как исправленное
`TenantCacheBackend` (tenant-префикс), RedisError-widening (ADR-0356), per-key TTL в
`MemoryBackend`, TTL-sidecar в `DiskCacheBackend`, обёртка memory/disk-fallback,
удаление `core/rate_limiter/` (ADR-0353) — подтверждены чтением кода.

---

## 4. Database findings — **впервые в аудите**

> Подсистема не была охвачена ни одним циклом 168–171. Путь в коде —
> `src/backend/infrastructure/database/` (не `infrastructure/db/`).

### 🔴 CRITICAL-07 — весь DB-DSL мёртв: `get_db_manager` не существует
- **Where**: `core/di/providers/db.py:303-312` → `infrastructure/database/database/accessors.py:66-72`
- `get_db_manager_provider()` возвращает `module.get_db_manager`; такого атрибута
  нет — `accessors.__getattr__` бросает `AttributeError`.
- **Runtime proof**:
  ```
  get_db_manager_provider() -> AttributeError:
    module '...database.database.accessors' has no attribute 'get_db_manager'
  ```
- **Impact**: `DatabaseQueryProcessor` (`dsl/engine/processors/components/databasequeryprocessor.py:56`)
  вызывает этот провайдер → **каждый** DSL-шаг `db_query`, `db_insert`, `db_update`,
  `db_upsert`, `db_delete` падает в `exchange.fail(...)`.

### 🔴 CRITICAL-08 — `db_crud` выбрасывает bind-параметры
- **Where**: `dsl/engine/processors/db_crud.py:388-413`
- `sql, _params = build_insert_sql(...)` — `_params` отброшен; далее
  `DatabaseQueryProcessor(sql=sql, result_property=...)` — у этого класса **нет**
  параметра `params` (`databasequeryprocessor.py:24-31`), он выводит параметры из
  `exchange.in_message.body`. Сгенерированные `:column`-плейсхолдеры не биндятся →
  `StatementError`.

### 🔴 CRITICAL-09 — прод-БД без TLS
- **Where**: `config_profiles/prod.yml:67-68` (`ssl_mode: "require"`, `ca_bundle: null`);
  `infrastructure/database/database/initializer.py:192-194`
- TLS включается **только** при непустом `ca_bundle`. При `ca_bundle: null`
  production-соединение с PostgreSQL идёт **без TLS**, несмотря на
  `ssl_mode: "require"`. `ssl_mode` — мёртвая настройка (никогда не читается).

### 🔴 CRITICAL-10 — failover-цепочка БД неимпортируема
- **Where**: `infrastructure/resilience/components/database_chain.py:35`
- `from ...database.database import get_db_session` — `get_db_session` **не
  определён нигде**. Runtime: `ImportError`. То же в `audit_chain.py:61` и
  `mongo_chain.py:44` → PG→SQLite failover, audit-fallback и mongo-fallback
  падают с ImportError вместо деградации.

### 🔴 HIGH-09 — `infra_db_query` и `db_crud` недостижимы из YAML
- `infra_db.py:23` регистрирует процессор, но метода `RouteBuilder` нет →
  `ValueError: Unknown or forbidden processor 'infra_db_query'`.
  `db_crud` не существует вовсе, но документирован в `docs/dsl/CRUD_DSL_AUDIT.md:55,78`.
- Проверено: `hasattr(RouteBuilder, 'infra_db_query') == False`, `db_crud == False`.

### 🔴 HIGH-10 — `crud_create(body=...)` из `CLAUDE.md` не работает
- **Where**: `dsl/builders/entity.py:116-122` — сигнатура
  `crud_create(entity, *, payload_from, result_property)`; параметра `body` нет.
- **Where**: `CLAUDE.md:294` и `CLAUDE.md:312` содержат именно `body=`.
  Проектные инструкции описывают неработающий шаг.

### ⚠️ HIGH-11 — circuit breaker `db:main` не на CRUD-пути
- **Where**: `session_manager.py:67` (guard в `create_session`) vs `session_manager.py:122`
  (`connection()` использует `self.session_maker()` — guard'а нет).
- Все 11 методов `SQLAlchemyRepository` идут через `connection()` → breaker
  `db:main` на основном пути не срабатывает никогда.

### ⚠️ HIGH-12 — `pool_pre_ping` — мёртвая конфигурация
- `initializer.py:149` хардкодит `pool_pre_ping: True`; поля
  `core/config/database.py:120` и `core/config/external_databases/connection.py:66`
  не читаются, хотя заданы в `config_profiles/prod.yml:76,90`.

### ⚠️ HIGH-13 — DSN основной БД не URL-энкодится
- `core/config/database.py:231` интерполирует `username`/`password` сырым; внешний
  путь корректно использует `quote_plus` (`external_databases/connection.py:154-155`).
  Пароль с `@ : / #` ломает DSN.

### ⚠️ HIGH-14 — `db_call_procedure` шлёт PostgreSQL-синтаксис в Oracle
- `dsl/builders/transport/persistence.py:32` и
  `infrastructure/database/external_database_facade.py:325` по умолчанию
  `dialect="postgres"`; `facade.py:409-415` для всего, что не `mssql`/`oracle`,
  строит PG-`CALL`. Oracle-профиль получает невалидный SQL.

### ⚠️ HIGH-15 — внешние БД: 7 заявленных, 2 поддержаны
- `core/enums/database.py:21-24` рекламирует `mssql`/`mysql`/`db2`;
  `external_databases/connection.py:175` бросает `NotImplementedError`;
  `services/io/external_database/dispatch_mixin.py:147,173` — `DatabaseError`.
- `docs/backends.md:19-23` честно относит их к «Tier B — Smoke only», но enum
  обещает больше, чем даёт код.

### ⚠️ MEDIUM-07 — `PoolMonitor` не собирает ничего
- `pool_monitor.py:80` читает `db_initializer._async_engine`; атрибут называется
  `async_engine` (`initializer.py:45`). `AttributeError` глотается на `:99-100` →
  `collect_stats()` **всегда** возвращает `None`. В том же файле `:144` написано
  правильно — внутреннее противоречие файла.
- Тест `tests/unit/infrastructure/database/test_pool_monitor.py:65` **воспроизводит
  опечатку в моке**, поэтому зелёный.

### ⚠️ MEDIUM-08 — `base_extensions` — мёртвый код со сломанным контрактом
- `services/core/base_extensions.py:52-57` (`@transactional` — no-op: у
  `SQLAlchemyRepository` нет `session_manager`), `:56` (`transaction()` без
  обязательного аргумента), `:118,153` (`session_manager.session()` — такого
  метода нет). Ни один импортёр в `src/`/`extensions/`.

### ⚠️ MEDIUM-09 — реплика не сконфигурирована и не используется
- `replica_dsn` отсутствует во всех `config_profiles/*.yml`;
  `get_smart_read_session`/`get_smart_write_session` (`session_manager.py:177,190`)
  не имеют потребителей; единственный production-пользователь `SmartSessionManager`
  — `dsl/engine/processors/saga_lra.py:73-107` с `mode="write"`.

### ⚠️ MEDIUM-10 — `max_retries` не читается; пулы внешних БД не прогреваются
- `core/config/database.py:170` `max_retries` — ни одного читателя в DB-слое.
- `database/registry.py:57-60` и `database/initializer.py:201-209` (warmup) — без
  вызывающих; `PoolWarmup` греет только `pg`/`pg_replica`/`redis`/`clickhouse`.

### ⚠️ MEDIUM-11 — расхождение семантики исключений между путями сессии
- `connection()` пробрасывает `NotFoundError` как есть (`session_manager.py:136-137`);
  `create_session()` оборачивает всё, включая `NotFoundError`, в `DatabaseError`
  (`:70-79`). Один и тот же отказ — два типа исключений.

### ⚠️ MEDIUM-12 — `RepositoryProtocol` не описывает реальный контракт
- `core/interfaces/repositories.py:36-66` не содержит `get_paginated`, `count`,
  `bulk_create` — при этом `services/core/base/crud_mixin.py:198` вызывает
  `self.repo.get_paginated(...)`.
- `ExternalSessionManagerProtocol` (`core/interfaces/integrations.py:259-261`)
  объявляет только `create_session()`, хотя реализация даёт ещё `transaction`,
  `connection`, `get_session`, `get_transaction_session`.

### ⚠️ MEDIUM-13 — `SQLAlchemyRepository` — God-object
- `infrastructure/repositories/base/sqlalchemy.py` — 491 LOC, **11 публичных
  методов** (порог проекта: >10). 10 из 11 методов несут
  `# type: ignore[override]` из-за расхождения с `AbstractRepository`
  (`base.py:11-74`): `get_all_versions` требует лишний `order`, `first_or_last` —
  лишний `limit`.

### ⚠️ LOW-03 — `get_external_session_manager` не кэшируется
- `session_manager.py:168-175` — новый `DatabaseSessionManager` на каждый вызов
  (в отличие от `get_main_session_manager`, `@lru_cache` на `:160`).

---

## 5. Filesystem-scanning findings — **впервые в аудите**

### 🔴 CRITICAL-11 — YAML `watch_files` сканирует любой каталог хоста
- **Where**: `dsl/engine/processors/file_watch.py:38-39,79-80`;
  `dsl/engine/processors/base.py:101-102`; `dsl/builders/sources_mixin/file_sources_mixin.py:99-123`
- Процессор объявляет `capabilities=("fs.watch",)`, но **не имеет**
  `required_capability` → `BaseProcessor.auth_check` возвращает `True` немедленно.
- `fs.watch` **не зарегистрирован** в vocabulary
  (`core/security/capabilities/vocabulary/defaults/base.py` содержит только
  `fs.read` и `fs.write`).
- Путь берётся из DSL/exchange без какой-либо валидации.
- **Итог**: YAML-маршрут с шагом `watch_files` читает произвольный каталог
  файловой системы — без capability-объявления, без allowlist, без path-traversal
  защиты.

### 🔴 CRITICAL-12 — ни один сканер/вочерёдник не валидирует путь
- **Where**: единственный guard — `dsl/engine/processors/_path_safety.py:36-73`
  (`validate_path`: запрет `..`, resolve симлинков, allowlist-префикс с
  границей разделителя). Вызывается **только** из
  `filereadprocessor.py:57` и `filewriteprocessor.py:69`.
- **Не вызывают**: `file_watch.py:185-217`, `fs_directory_scan.py:155-189`,
  `rpa/operations/filtereddirectoryscanprocessor.py:87`,
  `rpa/operations/filelistprocessor.py:61`, `rpa/operations/filewatchprocessor.py:104`,
  `entrypoints/filewatcher/watcher_manager.py:82-84`,
  `infrastructure/sources/file_watcher.py:118`.
- `fs_directory_scan.py:139` в докстринге **заявляет** проверку path-traversal,
  которой в коде нет (`:163-171` — только `realpath` + `isdir`, причём сканируется
  **неразрешённый** путь).

### ⚠️ HIGH-16 — `directory_scan` всегда умирает; тест это маскирует
- `rpa.directory.scan` не зарегистрирован в vocabulary → deny-by-default
  (`gate/check_mixin.py:134-148`) → `exchange.stop()` на каждом вызове.
- `tests/unit/dsl/engine/processors/test_directory_scan.py:28` мокает
  `FilteredDirectoryScanProcessor.auth_check` → тест зелёный на неработающей
  фиче.

### ⚠️ HIGH-17 — allowlist путей живёт только в env
- `_path_safety.py:25-33` — `DSL_ALLOWED_PATHS` (env-only). Отсутствует в
  `config/services/*` и во всех `config_profiles/*.yml` → в контейнере без
  переменной окружения allowlist деградирует до дефолта
  `/data/uploads, /data/exports, /tmp/dsl, /var/data`.

### ⚠️ HIGH-18 — вочерёдники умирают навсегда
- `entrypoints/filewatcher/watcher_manager.py:177-178` — исключение внутри
  `async for` завершает цикл; задача мертва, рестарта нет.
- `infrastructure/sources/file_watcher.py:190-191` — ловит только
  `asyncio.CancelledError`; удалённый каталог убивает watch-задачу.
- `dsl/yaml_watcher.py:210-212` — потребитель умирает и не перезапускается.
- `core/config/hot_reload.py:137` — у `awatch` нет `except` вовсе.

### ⚠️ HIGH-19 — `Observer.join()` блокирует event loop
- `dsl/engine/processors/rpa/operations/filewatchprocessor.py:110` —
  `observer.join(timeout=2.0)` выполняется на потоке event loop (до 2 с блокировки).

### ⚠️ HIGH-20 — `except Exception: pass`
- `dsl/engine/processors/rpa/operations/filtereddirectoryscanprocessor.py:139-141`
  — запрещено доктриной, скрывает любую ошибку.

### ⚠️ MEDIUM-14 — `max_results` не ограничивает стоимость сканирования
- `file_watch.py:222-235` — cap применяется **после** полного обхода;
  `os.walk` на `:297` без ограничения глубины.

### ⚠️ MEDIUM-15 — `LocalFSStorage`: проверка префикса без границы разделителя
- `infrastructure/storage/local_fs.py:102` — `str(path).startswith(str(self._base))`
  → `/data/storage` пропускает `/data/storage-evil/x`.

### ⚠️ MEDIUM-16 — `LocalFSStorage.list_keys` — неограниченный `rglob`
- `local_fs.py:187` — без лимита числа ключей.

### ⚠️ MEDIUM-17 — `from_filewatcher` как YAML-шаг — тихий no-op
- `dsl/builders/sources_mixin/file_sources_mixin.py:15-17` — `@classmethod`,
  возвращающий **новый** builder; `_apply_processor` (`dsl/yaml_loader/build.py:198-206`)
  возвращаемое значение отбрасывает.

### ⚠️ MEDIUM-18 — YAML-ключ `file_watch` не грузится; round-trip `to_yaml` сломан
- `file_watch.py:56-68` документирует `- file_watch: {...}`; такого метода
  `RouteBuilder` нет → `ValueError` на загрузке.
- `file_watch.py:250-264` `to_spec()` отдаёт `{"file_watch": spec}` →
  `Pipeline.to_yaml()` emits негодный YAML.

### ⚠️ LOW-04 — мёртвая настройка с противоречивым описанием
- `core/config/features/experimental.py:45-53` — `eventbus_file_watcher`,
  default `True`, описание «default-OFF», **не читается** в production-коде.

### ⚠️ LOW-05 — `dsl.hot_reload_debounce_ms` не доходит до hot-reload
- `core/config/hot_reload.py:49,147` — debounce хардкод 500 мс.

---

## 6. Logging findings

Цикл 171 закрыл CRITICAL-04 (TLS в Graylog TCP), HIGH-09 (`basicConfig`),
HIGH-10 (`AIWorkspaceCleaner` не запускался) — **подтверждено чтением кода**.

Остаточный долг — стиль, не дефект:
- **LOW-06**: 86 файлов с inline `import logging` (в отчёте 171 указано 74 —
  расхождение в методике подсчёта). Ruff-правила на это нет; основная масса —
  4 в `entrypoints/middlewares/` и 11 в `dsl/engine/processors/` (hot path).

---

## 7. Documentation findings

| ID | Документ | Дефект |
|---|---|---|
| **DOC-01** | `artifacts/current_audit/S3_CACHE_LOGGING_AUDIT_2026-10-21.md:379,435` | Ложное утверждение «Wave 0 восстановил S3-тесты» — см. §1.1 |
| **DOC-02** | `CLAUDE.md:294,312` | `crud_create(body=...)` — нерабочий параметр |
| **DOC-03** | `docs/dsl/CRUD_DSL_AUDIT.md:55,78` | `route.db_crud(...)` — метода не существует |
| **DOC-04** | `docs/dsl/CRUD_DSL_AUDIT.md:62,79` | `.db_call_procedure(name=..., params=...)` → `TypeError` (нет `params`, `profile` обязателен) |
| **DOC-05** | `docs/rpa/RPA_GUIDE.md:22-34,119-126` | capability `rpa.*` в vocabulary отсутствуют; 4 настройки `rpa:`-профиля не существуют в коде |
| **DOC-06** | `docs/runbooks/pool-warmup-tuning.md:46` | `POOL_WARMUP_DISABLED` — 0 вхождений в коде |
| **DOC-07** | `docs/runbooks/disaster_recovery.md:34` | `db_replica_enabled` — 0 вхождений; реальный переключатель — `replica_dsn` + `multi_replica_failover` |
| **DOC-08** | `dsl/engine/processors/file_watch.py:4` | «Использует `watchdog`» — watchdog не импортируется, это одноразовый скан |
| **DOC-09** | `dsl/engine/processors/fs_directory_scan.py:139` | «проверяет path-traversal» — проверки нет |
| **DOC-10** | `docs/config/HOT_RELOAD.md` | Утверждает, что hot-reload не подключён; подключён (`plugins/composition/setup_infra/lifecycle.py:351-394`) |
| **DOC-11** | `dsl/yaml_watcher.py:5` | Ссылается на «ADR-041 `fs-watcher-unification`» — такого файла в `docs/adr/` нет |
| **DOC-12** | `docs/analysis/storage-coverage-status.md:15` | Утверждает «20 (S61 W1+W3) unit-тестов» для S3 — фактически 100% skip |

**Отсутствует**: `docs/infra/database.md` (настройки БД, отказоустойчивость,
операции) — аналог `docs/infra/object-storage.md` для БД отсутствует.

---

## 8. Что НЕ было сделано

- **Нет живых контейнеров** (Docker Hub недоступен) → MinIO / KeyDB / PostgreSQL /
  Redis-кластер не поднимались. S3 доказан через `ThreadedMotoServer` (реальный
  S3 wire-протокол); БД — через настоящий `aiosqlite` + подлинные исключения
  SQLAlchemy; Redis-кластер — через эмуляцию multi-node на одном сервере.
- **Не проверялось**: реальная производительность под нагрузкой; поведение
  Oracle/MSSQL/MySQL/DB2 (драйверы не установлены); S3 SSE-KMS (нет KMS).
- **`mutants/tests/unit/storage/*`** — дубликаты канонического набора, не аудировались.

---

## 9. Decision record (grilling, 3 rounds, 12 решений)

| # | Вопрос | Решение |
|---|---|---|
| 1 | Границы цикла | Полный объём: S3 + кэш + БД + сканирование ФС + логи |
| 2 | CRITICAL-05 | Заменить `aioboto3` → `aiobotocore` напрямую |
| 3 | HIGH-01 (пул S3) | Долгоживущий клиент с явным lifecycle + закрытие на shutdown + замер рукопожатий |
| 4 | Стандарт доказательств | Runtime-proof на реальных классах + `ThreadedMotoServer` |
| 5 | Глубина правок БД | **Все 26**, включая рефакторинг протоколов и разбиение `SQLAlchemyRepository` |
| 6 | Доказательства БД | SQLite-backed реальные тесты (настоящий initializer + repository + процессор) |
| 7 | Capability-модель ФС | Зарегистрировать `fs.watch` + `rpa.file.watch`/`rpa.directory.scan`/`rpa.file.list`, назначить `required_capability` |
| 8 | Безопасность путей ФС | Allowlist в конфиг-систему, `validate_path` везде, рестарт с бэкоффом, граница префикса, лимиты обхода |
| 9 | HIGH-07 (Redis-кластер) | Реализовать реальный fan-out по узлам |
| 10 | MEDIUM-05 (`cache_policy`) | Честный маркер: `RuntimeWarning` при сборке маршрута + ADR + документация |
| 11 | MEDIUM-03 (presign) | Отдельная capability `storage.presign` + audit-событие |
| 12 | Оформление | Коммитить по волнам на ветке `audit/s3-cache-logging-cycle-171`; по завершении — слияние в `master` |
