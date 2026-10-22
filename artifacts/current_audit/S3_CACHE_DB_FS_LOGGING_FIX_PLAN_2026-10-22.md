# Fix Plan — S3 / Cache / Database / Filesystem / Logging

**Date**: 2026-10-22
**Cycle**: 172
**Companion**: `S3_CACHE_DB_FS_LOGGING_AUDIT_2026-10-22.md`
**Status**: approved (grilling, 3 rounds, 12 decisions)

Каждая волна — один коммит, независимо откатываемая и независимо проверяемая.
Порядок выбран так, чтобы каждая волна открывала возможность доказать
следующую: сначала снимаем блокеры доказательной базы (S3), потом чиним
мёртвые подсистемы (БД, ФС), потом точечные улучшения (кэш, presign), потом
документацию.

---

## Wave 1 — S3: снять блокер доказательной базы

> **Без этой волны ни одно S3-исправление цикла 171 не имеет исполненной
> доказательной базы** — тест-сьют пропускается на 100%.

| # | Действие | Файлы |
|---|---|---|
| 1.1 | Объявить `aiobotocore` прямой зависимостью; удалить `aioboto3` из mypy-ignore | `pyproject.toml` |
| 1.2 | `_import_aioboto3()` → `_import_aiobotocore()`; `Session()` → `get_session()`; `session.client(...)` → `session.create_client(...)` | `infrastructure/storage/s3.py` |
| 1.3 | Долгоживущий клиент: `_S3Session` переиспользует один клиент; `aclose()` + вызов из shutdown | `infrastructure/storage/s3.py`, `plugins/composition/lifecycle/startup.py` |
| 1.4 | Снять skip-шим; тест против `ThreadedMotoServer` | `tests/unit/storage/test_s3_object_storage.py` |
| 1.5 | Перевести остальные модули на `aiobotocore` | `dsl/builders/eip/sources.py`, `core/privacy/delete_data_subject/_s3.py`, `core/orchestration/airflow_sensors.py`, `infrastructure/storage/factory.py` |
| 1.6 | Замер рукопожатий: до/после | `artifacts/current_audit/` |

**Приёмка**: `pytest tests/unit/storage/` — 0 skipped; S3-бэкенд работает против
`ThreadedMotoServer`; handshake-замер показывает переиспользование соединения.

---

## Wave 2 — БД: воскресить мёртвую DSL-поверхность (CRITICAL)

| # | Действие | Файлы |
|---|---|---|
| 2.1 | Реализовать `get_db_manager` (реальный accessor к `DatabaseSessionManager`) | `infrastructure/database/database/accessors.py` |
| 2.2 | Прокинуть bind-параметры в `DatabaseQueryProcessor` | `dsl/engine/processors/db_crud.py`, `.../components/databasequeryprocessor.py` |
| 2.3 | Починить `get_db_session` в failover-цепочках | `resilience/components/{database,audit,mongo}_chain.py` |
| 2.4 | Применить `ssl_mode` (TLS без `ca_bundle`, через `ssl.create_default_context`) | `infrastructure/database/database/initializer.py` |
| 2.5 | Сделать `infra_db_query` достижимым из YAML | `dsl/builders/transport/persistence.py` |
| 2.6 | Поддержать `body=` в `crud_create` (как в `CLAUDE.md`) | `dsl/builders/entity.py` |
| 2.7 | SQLite-backed реальные тесты DB-DSL | `tests/unit/infrastructure/database/`, `tests/unit/dsl/` |

**Приёмка**: DSL-маршрут с `db_query`/`crud_create` реально исполняется на
`aiosqlite`; failover-цепочка импортируется; прод-конфиг даёт TLS.

---

## Wave 3 — БД: HIGH (отказоустойчивость, пулы, конфиг)

| # | Действие |
|---|---|
| 3.1 | `connection()` — guard circuit breaker'а `db:main` |
| 3.2 | `pool_pre_ping` читается из настроек (мёртвая настройка) |
| 3.3 | URL-энкодинг DSN основной БД (`quote_plus`) |
| 3.4 | `db_call_procedure`: диалект выводится из типа профиля |
| 3.5 | `max_retries` — реализовать retry на DB-пути |
| 3.6 | `PoolMonitor._async_engine` → `async_engine`; починить замаскированный тест |
| 3.7 | `get_external_session_manager` — кэшировать |
| 3.8 | Warmup пулов внешних БД; `replica_dsn` в `prod.yml` |
| 3.9 | `base_extensions` — либо починить контракт, либо удалить мёртвый код |

---

## Wave 4 — БД: контракты и God-object

| # | Действие |
|---|---|
| 4.1 | `RepositoryProtocol` — дополнить реально используемыми методами |
| 4.2 | `ExternalSessionManagerProtocol` — дополнить `transaction`/`connection`/`get_session` |
| 4.3 | `SQLAlchemyRepository` (491 LOC / 11 методов) → композиция миксинов, **публичное имя сохранено** |
| 4.4 | Убрать `# type: ignore[override]` через согласование сигнатур |

---

## Wave 5 — ФС: capability-модель

| # | Действие |
|---|---|
| 5.1 | Зарегистрировать `fs.watch` в vocabulary |
| 5.2 | Зарегистрировать `rpa.file.watch`, `rpa.directory.scan`, `rpa.file.list` |
| 5.3 | Назначить `required_capability` ядерному `FileWatchProcessor` и RPA-процессорам |
| 5.4 | Починить маскирующий тест `test_directory_scan.py:28` |

---

## Wave 6 — ФС: безопасность путей и отказоустойчивость

| # | Действие |
|---|---|
| 6.1 | Allowlist → конфиг-система (`dsl.allowed_paths` + `config_profiles/*.yml`); env остаётся override |
| 6.2 | `validate_path` — ко всем сканерам и вочерёдникам |
| 6.3 | Рестарт вочерёдников с экспоненциальным бэкоффом |
| 6.4 | `Observer.join()` → `asyncio.to_thread` |
| 6.5 | `except Exception: pass` → конкретные исключения |
| 6.6 | `LocalFSStorage` — граница префикса по разделителю |
| 6.7 | `max_depth` + cap до обхода в `file_watch`; лимит ключей в `list_keys` |
| 6.8 | `from_filewatcher` как YAML-шаг — не тихий no-op |

---

## Wave 7 — Кэш

| # | Действие |
|---|---|
| 7.1 | `delete_by_tag` — fan-out по узлам RedisCluster |
| 7.2 | `policy.cache_policy()` — `RuntimeWarning` при сборке маршрута + ADR + документация |
| 7.3 | Квота S3: атомарный check+record; корректный 7-дневный rollover |

---

## Wave 8 — S3: разграничение presign

| # | Действие |
|---|---|
| 8.1 | Capability `storage.presign` в vocabulary |
| 8.2 | `facade.presigned_url` — требовать `storage.presign`, audit-событие |

---

## Wave 9 — Документация

| # | Действие |
|---|---|
| 9.1 | `docs/infra/database.md` — настройки БД, отказоустойчивость, операции |
| 9.2 | `docs/infra/filesystem-scanning.md` — allowlist, capability, отказоустойчивость |
| 9.3 | `docs/rpa/RPA_GUIDE.md` — capability-таблица и `rpa:`-профиль приведены в соответствие |
| 9.4 | Runbooks: `POOL_WARMUP_DISABLED`, `db_replica_enabled` |
| 9.5 | `CLAUDE.md` — `crud_create(body=)` приводится в соответствие |
| 9.6 | `docs/dsl/CRUD_DSL_AUDIT.md` — `db_crud`, `db_call_procedure(params=...)` |
| 9.7 | Исправить ложное утверждение в аудите цикла 171 (DOC-01) |
| 9.8 | `docs/analysis/storage-coverage-status.md` — честный статус S3-тестов |

---

## Стратегия верификации

| Волна | Доказательство |
|---|---|
| 1 | `pytest tests/unit/storage/` → 0 skipped; handshake-замер |
| 2 | DB-DSL на `aiosqlite` end-to-end; `ImportError`/`AttributeError` больше не воспроизводятся |
| 3 | breaker срабатывает на CRUD-пути; `pool_pre_ping`/`ssl_mode` в `prod.yml` влияют на engine kwargs |
| 4 | `mypy` без новых `ignore`; `check_layers.py --strict` без новых нарушений |
| 5 | YAML-шаг `watch_files` без capability → `CapabilityDeniedError`; с capability → проходит |
| 6 | Сканер вне allowlist → отказ; вочерёдник переживает исключение и перезапускается |
| 7 | Cluster-эмуляция: `delete_by_tag` удаляет на нескольких узлах |
| 8 | `presigned_url` без `storage.presign` → `CapabilityDeniedError` |
| 9 | Сверка документов с кодом |

**Гейты после каждой волны**: `make lint`, `make typecheck`,
`uv run python tools/check_layers.py --strict` — без новых нарушений относительно
текущего baseline.

---

## Явно отложено (с обоснованием)

- **SSE-KMS / per-tenant bucket** — глубокий IAM-дизайн; SSE-AES256 и префиксная
  изоляция уже закрыты.
- **Oracle / MSSQL / MySQL / DB2 во внешнем контуре** — требуют драйверов и
  живых стендов; в текущем цикле — только явный `NotImplementedError` вместо
  обещаний в enum (HIGH-15).
- **`mutants/tests/unit/storage/*`** — дубликаты канонического набора.
