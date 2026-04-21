# ADR-016: Data Lake (Iceberg/Delta) + CDC multi-source

* Статус: accepted
* Дата: 2026-04-21
* Фазы: I2

## Контекст

Банковские analytical workload-ы требуют:

- Column-store с ACID-транзакциями (Iceberg / Delta).
- CDC из оперативных БД (MySQL/Postgres/Oracle/MongoDB) в lake.
- Оркестрация долгих workflow (Temporal).
- Bulk-обработка (Apache Beam через Dataflow/Flink runner).
- GraphQL subscriptions для live-подписок на изменения.

## Решение

1. Публичный scaffold в `src/infrastructure/datalake/` — точка
   подключения конкретных драйверов через opt-in extras
   `gdi[datalake]`.
2. CDC — расширение существующего `src/infrastructure/clients/external/cdc.py`
   (уже есть Postgres) на Mongo/Oracle/MySQL — по мере подключения
   источников.
3. Temporal.io вынесен в отдельный opt-in `gdi[temporal]` —
   подключается при потребности в долгих workflow.
4. Apache Beam — через `gdi[beam]`, рекомендуемые runner: Dataflow
   (GCP) или Flink (on-prem).

## Альтернативы

- **Только pandas/polars в БД**: не масштабируется до банковских
  объёмов.
- **Spark**: отвергнуто для core — тяжёлый deploy; остаётся опция
  для заказчика.

## Последствия

- Развёртывание data lake — deploy-time решение заказчика.
- Приложение экспортирует в lake через outbox-события (ADR-011).
