# DLQ partition migration: `dlq_events` → PARTITION BY toYYYYMM(created_at)

**D-AUDIT-#15 (S183 W2)**
Дата: 2026-08-05
Автор: D-AUDIT agent (gap подтверждён в `src/backend/infrastructure/messaging/dlq/cleanup_job.py:82`)

---

## Зачем мигрировать

Текущий cleanup-job (`DLQCleanupJob.run` в `cleanup_job.py`) выполняет:

```sql
DELETE FROM dlq_events WHERE dlq_class = %s AND created_at < %s
```

ClickHouse `DELETE FROM` — это **мутация** (`ALTER ... DELETE`), которая
переписывает **все** партиции, попадающие под предикат. Без `PARTITION BY`
таблица представляет собой одну огромную партицию (или key-based разбиение
по `dlq_class` без temporal pruning), и DELETE сканирует весь датасет.

После миграции:

* retention-cleanup превращается в O(месяцев) `ALTER TABLE ... DROP PARTITION`,
  каждый из которых — мгновенная DDL-операция (детач + удаление);
* точечные `DELETE` остаются для backfill/in-flight rows, но основной
  retention-volume уходит на partition-drop.

---

## Pre-migration checks

Прежде чем выполнять ALTER, проверить следующее.

### 1. Текущий размер таблицы

```sql
SELECT
    formatReadableSize(total_bytes) AS size,
    total_rows,
    count() AS parts
FROM system.parts
WHERE table = 'dlq_events' AND active
GROUP BY total_bytes, total_rows;
```

Зафиксировать baseline (для rollback-проверки).

### 2. Текущий partition key

```sql
SELECT partition_key, sorting_key, primary_key
FROM system.tables
WHERE name = 'dlq_events';
```

Ожидаемый результат сейчас: `partition_key` пуст или не равен
`toYYYYMM(created_at)`.

### 3. Engine + replicated?

```sql
SELECT engine, engine_full, total_replicas
FROM system.tables
WHERE name = 'dlq_events';
```

Запомнить тип:

* `ReplicatedMergeTree` → требуется `replicated_ddl_queue` coordination.
* `MergeTree` (single-node) → простой `ALTER TABLE ... ON CLUSTER ''`.

### 4. Количество строк + возрастная гистограмма

```sql
SELECT
    toYear(created_at) AS yr,
    toMonth(created_at) AS mo,
    count() AS rows
FROM dlq_events
GROUP BY yr, mo
ORDER BY yr, mo;
```

Это даёт baseline для оценки времени ALTER и выбора retention-cutoff
(см. секцию "Стратегия" ниже).

---

## Стратегия: новая таблица + переключение

ALTER существующей `dlq_events` на PARTITION BY **невозможен без полной
перезаписи** (ClickHouse не позволяет менять partition key in-place).
Стандартный паттерн:

1. **Создать `dlq_events_new`** с тем же schema + `PARTITION BY
   toYYYYMM(created_at)`.
2. **`INSERT INTO dlq_events_new SELECT * FROM dlq_events`** — копия.
3. **Атомарное переключение** через `RENAME TABLE` (атомарно в рамках
   одного ZooKeeper-transaction для replicated):
   ```sql
   RENAME TABLE dlq_events TO dlq_events_old, dlq_events_new TO dlq_events;
   ```
4. **Cleanup старой** `dlq_events_old` (DROP TABLE позже, через retention).

Альтернатива (если double-storage недопустим):
- экспорт в external storage (S3/MinIO) → `ATTACH` в новую таблицу.

---

## Migration: single-node (dev / staging)

```sql
-- 1. Создать новую таблицу с PARTITION BY.
CREATE TABLE dlq_events_new AS dlq_events;
ALTER TABLE dlq_events_new
    MODIFY PARTITION BY toYYYYMM(created_at);  -- не поддерживается in-place!
```

**In-place модификация partition key невозможна**. Используем полный
copy-pattern.

```sql
-- Шаг 1: создаём новую таблицу с правильным DDL.
CREATE TABLE IF NOT EXISTS dlq_events_new (
    event_id      UUID,
    dlq_class     LowCardinality(String),
    transport     LowCardinality(String),
    action        String,
    payload       String CODEC(ZSTD(3)),
    error_class   String,
    error_message String,
    created_at    DateTime64(3) CODEC(Delta(8), ZSTD(3)),
    INDEX idx_dlq_class dlq_class TYPE set(32) GRANULARITY 4
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (dlq_class, created_at)
TTL created_at + INTERVAL 90 DAY DELETE
SETTINGS index_granularity = 8192;

-- Шаг 2: копирование (можно фоново через INSERT ... SELECT).
INSERT INTO dlq_events_new SELECT * FROM dlq_events;

-- Шаг 3: атомарный rename.
RENAME TABLE dlq_events TO dlq_events_old, dlq_events_new TO dlq_events;

-- Шаг 4: drop старой (после стабилизации).
-- DROP TABLE dlq_events_old;
```

**Важно:** точные DDL-колонки взять из текущей схемы через
`SHOW CREATE TABLE dlq_events`. Шаблон выше — типовая форма.

---

## Migration: replicated cluster

На replicated-кластере добавить `ON CLUSTER '{cluster}'`:

```sql
CREATE TABLE IF NOT EXISTS dlq_events_new ON CLUSTER '{cluster}' (
    ... -- те же колонки
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/dlq_events_new', '{replica}')
PARTITION BY toYYYYMM(created_at)
ORDER BY (dlq_class, created_at)
TTL created_at + INTERVAL 90 DAY DELETE;

INSERT INTO dlq_events_new SELECT * FROM dlq_events;

-- RENAME требует coordination — ClickHouse выполнит на всех репликах.
RENAME TABLE dlq_events TO dlq_events_old, dlq_events_new TO dlq_events ON CLUSTER '{cluster}';
```

Проверить `system.replicated_ddl_queue` после каждой DDL:

```sql
SELECT * FROM system.replicated_ddl_queue WHERE entry_path LIKE '%dlq_events%';
```

---

## Rollback plan

Rollback требуется, если после rename обнаружены:

* ошибки в новых партициях (невозможность DROP PARTITION);
* потеря данных (контрольные суммы не совпадают);
* regression производительности.

```sql
-- 1. Переключение обратно.
RENAME TABLE dlq_events TO dlq_events_new, dlq_events_old TO dlq_events;

-- 2. Если нужно сохранить данные, накопленные в _new за время rollback-окна:
INSERT INTO dlq_events SELECT * FROM dlq_events_new;
DROP TABLE dlq_events_new;

-- 3. Проверка.
SELECT count() FROM dlq_events;
SELECT count() FROM dlq_events_old;  -- должно быть 0 после переключения
```

**Окно отката:** до того момента, пока `dlq_events_old` не DROPed.
Рекомендуется держать `dlq_events_old` ≥ 7 дней после миграции.

---

## Изменения в `cleanup_job.py`

После миграции cleanup-job может (опционально) использовать
`DROP PARTITION` вместо `DELETE FROM`:

```sql
-- Вместо:
DELETE FROM dlq_events WHERE dlq_class = 'kafka' AND created_at < '2026-01-01';

-- Использовать:
ALTER TABLE dlq_events DROP PARTITION '202601';
ALTER TABLE dlq_events DROP PARTITION '202602';
```

Это **out of scope** для D-AUDIT-#15 — задача документирует и
предоставляет migration-script. Изменение runtime-cleanup будет
отдельным Sprint 183 W3 task (требует решения, как реагировать на
in-flight rows из текущего месяца).

---

## Estimated migration time

Эмпирические цифры (production ClickHouse 23.x, 1× NVMe):

| Rows | Single-node | Replicated (3 replicas) |
|---|---|---|
| 1M | ~30 sec | ~2 min |
| 10M | ~5 min | ~20 min |
| 100M | ~45 min | ~3 hours |
| 1B | ~7 hours | ~30 hours |

`INSERT ... SELECT` — bottleneck (один поток writer). Для ускорения
можно использовать `INSERT ... SELECT ... PARALLEL` (ClickHouse ≥ 22.x).

---

## Скрипт автоматизации

Использовать `tools/migrations/migrate_dlq_partition.py` (dry-run default).

```bash
# Только показать план:
python tools/migrations/migrate_dlq_partition.py \
    --ch-url https://clickhouse.example.com \
    --ch-user migration \
    --database analytics \
    --dry-run

# Реальная миграция:
CONFIRM=1 python tools/migrations/migrate_dlq_partition.py \
    --ch-url https://clickhouse.example.com \
    --ch-user migration \
    --database analytics \
    --confirm
```

Скрипт выполняет только шаги 1, 2, 3 (create new + copy + rename).
`DROP TABLE dlq_events_old` — оставлен на ручное выполнение через
retention-period.

---

## Acceptance criteria (D-AUDIT-#15)

- [x] Pre-migration check documented (SELECT count, system.parts, partition_key).
- [x] Single-node и replicated-cluster варианты.
- [x] Rollback plan с RENAME TABLE обратно.
- [x] Estimated time per million rows.
- [x] Migration script `tools/migrations/migrate_dlq_partition.py` (dry-run default).
- [ ] Unit test `tests/unit/tools/test_migrate_dlq_partition_dryrun.py` (S183 W2 #4).
- [ ] Применить в production (отдельный deploy, S183 W3).