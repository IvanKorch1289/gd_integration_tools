# ADR-037: PostgreSQL → SQLite Snapshot Job для resilience-fallback

- **Статус:** accepted
- **Дата:** 2026-05-01
- **Фаза:** Wave-W26.8 (Resilience snapshot)
- **Автор:** Claude (по согласованию с заказчиком)

## Контекст

ADR-036 ввёл `ResilienceCoordinator` и fallback-цепочку
`db_main → sqlite_ro`: при OPEN-breaker'е PostgreSQL компонент `db_main`
переключается на read-only SQLite-snapshot. Wiring находится в
`src/infrastructure/resilience/components/database_chain.py`:

```python
async def _sqlite_ro_query(sql, params):
    snapshot_path = Path("var/db/snapshot.sqlite")
    if not snapshot_path.exists():
        snapshot_path.touch()
    # ... mode=ro
```

Проблема: **файл создаётся пустым**. Без incremental-sync процесса
fallback возвращает либо stale-данные (если файл когда-то заполнялся),
либо ничего (после `touch()`). Это нарушает контракт fallback-цепочки
из ADR-036, делает `/readiness` в degraded-режиме недостоверным и не
позволяет рассматривать `db_main → sqlite_ro` как реальный fallback.

В `dev_light.yml` SQLite — primary, поэтому snapshot там не нужен. Но
для prod / staging его отсутствие — блокирующая проблема W26.

## Рассмотренные варианты

- **Вариант А — pgcopydb / pg_dump в cron.** External-инструмент,
  плановый full-dump.

  *Плюсы:* проверенный инструмент, минимум кода в проекте.
  *Минусы:* отдельный процесс на хосте, требует pg-client-binaries в
  Docker-образе, тяжелее, чем нужно для read-only critical таблиц,
  не интегрируется с метриками приложения, нет готового healthcheck'а
  для `HealthAggregator`.

- **Вариант Б — Logical replication slot (PG → SQLite consumer).**
  Streaming CDC через `pgoutput` plugin.

  *Плюсы:* near-realtime, минимальный лаг.
  *Минусы:* требует `wal_level=logical` и superuser на PG, нет
  стандартного PG → SQLite consumer'а (нужно писать своё), сложный
  failover при падении SQLite-консумера, overkill для read-only
  fallback'а с допуском в 10-30 минут лага.

- **Вариант В — Debezium + Kafka.** Полноценный CDC-pipeline.

  *Плюсы:* enterprise-grade, audit-ready.
  *Минусы:* отдельный сервис, Kafka-зависимость для resilience-fallback'а
  (рекурсивная зависимость — Kafka сам имеет fallback в W26),
  несоразмерная сложность для текущей задачи.

- **Вариант Г — APScheduler + SQLAlchemy Core read/write (выбран).**
  Background-job в существующем `scheduler_manager`, full-replace
  per-table через `SELECT * → DELETE → INSERT` в одной транзакции.

  *Плюсы:* нулевые новые зависимости (APScheduler / SQLAlchemy /
  aiosqlite уже в `pyproject`), интеграция с метриками приложения,
  health-check без внешних компонентов, простая семантика
  "replace-all", автоматическая DDL-генерация через
  `metadata.create_all`.
  *Минусы:* лаг до `interval_minutes` (по умолчанию 10 мин); не
  работает для write-fallback'а (только read); blocking-call на время
  репликации (но в threadpool-executor'е APScheduler).

## Решение

Принят **Вариант Г**:

- Новый модуль `src/infrastructure/resilience/snapshot_job.py`
  (~270 LOC):
  - `sync_pg_to_sqlite(pg_engine, sqlite_engine, tables)` — core
    функция: per-table `SELECT * → DELETE → INSERT` в SQLite-
    транзакции; DDL — через `metadata.create_all(checkfirst=True)`.
  - `run_snapshot_now()` — sync-entry-point для startup hook и manual
    trigger; обновляет глобальное состояние и метрики; idempotent.
  - `register_snapshot_job(scheduler)` — регистрирует APScheduler
    `IntervalTrigger(minutes=N)` job, executor=`default` (threadpool).
  - `is_snapshot_fresh(threshold)` / `get_snapshot_age_seconds()` —
    health-check API для `HealthAggregator` и
    `database_chain._check_snapshot_freshness`.
- Метрики Prometheus:
  - `snapshot_age_seconds` (Gauge),
  - `snapshot_rows_total{table}` (Gauge),
  - `snapshot_sync_duration_seconds` (Gauge),
  - `snapshot_sync_errors_total` (Counter),
  - `db_fallback_used_with_stale_snapshot_total` (Counter, в
    `database_chain.py`).
- YAML-секция `snapshot:` в `config_profiles/base.yml` —
  `enabled / interval_minutes / tables / fresh_threshold_seconds /
  target_path / run_on_startup`.
- Pydantic-класс `SnapshotSettings` в
  `src/core/config/services/snapshot.py`, зарегистрирован в корневом
  `Settings`.
- Интеграция в lifespan: `_bootstrap_snapshot_job` выполняет initial
  sync (если `run_on_startup=true`) и регистрирует interval-job в
  существующем `scheduler_manager`.
- `database_chain._sqlite_ro_query` дополнительно вызывает
  `_check_snapshot_freshness()` — при stale-snapshot'е логирует
  warning и инкрементирует counter (но возвращает данные — лучше
  stale, чем 503).
- `dev_light.yml` явно выключает snapshot (`snapshot.enabled=false`),
  поскольку там SQLite — primary.

Критичные read-only таблицы: `orderkinds` (lookup, реплицируется
первым), `users`, `orders`, `certs`, `cert_history`. Список настраивается
через YAML — расширяется без изменений кода.

## Последствия

### Положительные

- Реальный fallback `db_main → sqlite_ro`: данные не пустые, не stale
  более чем на `interval_minutes` (default 10 мин).
- Зависимостей не добавляется: `apscheduler>=3.11`, `sqlalchemy>=2.0`,
  `aiosqlite>=0.20` уже в `pyproject.toml`.
- Метрика `snapshot_age_seconds` пригодна для Grafana-алертов
  (`snapshot_age_seconds > 1800` → degraded fallback).
- DDL автоматически согласована с PG-схемой: при добавлении новой
  колонки в ORM-модели достаточно перезапустить сервис.
- Health-check для snapshot интегрируется с `HealthAggregator` через
  `is_snapshot_fresh` — без новых интерфейсов.

### Отрицательные

- Лаг до `interval_minutes` — fallback возвращает данные на момент
  предыдущего sync. Не подходит для use-case'ов с
  consistency-требованиями (но они и не должны попадать на
  read-only fallback).
- Полная замена per-table — нагрузка на PG растёт линейно от размера
  выбранных таблиц. Для текущего набора (lookup + orders) это
  приемлемо; при росте orders > 100k строк потребуется upsert по PK
  или watermark-инкремент (W27).
- Sync блокирует своё SQLite-соединение на время транзакции — но
  fallback читает в режиме `mode=ro`, поэтому конкуренции с writer'ом
  нет (SQLite WAL не нужен).
- Snapshot не реплицирует `sqlalchemy_continuum`-history-таблицы —
  они не нужны для read-only fallback'а, но при необходимости их
  можно явно добавить в `snapshot.tables`.

### Нейтральные

- DSL apiVersion v3 не требуется — изменения чисто на уровне infra и
  конфигурации.
- Job хранится в `SQLAlchemyJobStore` (`default`) — переживает
  рестарт приложения.

## Связанные ADR

- ADR-036 — ResilienceCoordinator + Per-Service Fallback Chains
  (контекст: `db_main → sqlite_ro` chain).
- ADR-005 — Resilience patterns (purgatory / breaker registry).
- ADR-022 — Connector SPI (HealthAggregator integration).
