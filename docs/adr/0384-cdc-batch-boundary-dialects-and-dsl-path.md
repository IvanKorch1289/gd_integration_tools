# ADR-0384 — CDC: граница батча, диалекты и рабочий DSL-путь

* Статус: Accepted (2026-10-29, wave 16, кластер X5 — «CDC: ПОТЕРЯ СТРОК, ДИАЛЕКТЫ, DSL-ПУТЬ»)
* Cycle: 176
* Дата: 2026-10-29
- **Затрагивает**:
  - `src/backend/infrastructure/clients/external/cdc/_cursor.py` (новый)
  - `src/backend/infrastructure/clients/external/cdc/{events,strategies,kafka_strategy,client,_identifiers}.py`
  - `src/backend/infrastructure/cdc/{poll_backend,listen_notify_backend,cdc_client_adapter}.py`
  - `src/backend/dsl/engine/processors/cdc_capture.py`
  - `src/backend/dsl/builders/sources_mixin/cdc_sources_mixin.py`
  - `src/backend/entrypoints/cdc/cdc_routes.py`
  - `tests/unit/infrastructure/clients/external/cdc/**`, `tests/unit/infrastructure/cdc/**`,
    `tests/unit/dsl/builders/test_cdc_capture_builder.py`,
    `tests/unit/dsl/engine/processors/test_cdc_capture.py`,
    `tests/unit/entrypoints/cdc/test_cdc_routes.py`
- **Связан с**:
  - ADR-0360 (allowlist-валидация SQL-идентификаторов в CDC)
  - ADR-0112 (allowlist/escape как defence-in-depth)
  - ADR-0284 (межслойные зависимости)
  - ADR-0379 (честность состояний вместо «зелёных» статусов)

## Контекст

Аудит БД (волна 16) нашёл в CDC-кластере 8 дефектов: потеря строк на границе
батча, падение polling'а на PG `timestamp without time zone`, неработоспособный
DSL-путь, стабы в registry-бэкендах, игнор конфига Kafka, невалидный `LIMIT`
для Oracle/MSSQL/DB2, отсутствие лимитов подписки и подмена Kafka-timestamp'а
на `now()`.

## Решение

1. **Курсор `(timestamp, PK)`** (`_cursor.py`): условие выборки —
   `ts >= :last_ts AND (ts > :last_ts OR pk > :last_pk)`, порядок `ORDER BY ts, pk`.
   PK берётся из подписки либо определяется по первой выборке (`id` → `<table>_id`
   → `*_id`). Если PK определить не удалось — ts-only режим с `>=`,
   детерминированной сортировкой и дедупликацией по SHA-256 отпечатку строки
   (bounded-окно 10k). Курсор в Redis — строка `"<ts>|<pk>"` фиксированной
   ширины: лексикографический порядок = хронологический (legacy ISO-курсоры
   поддержаны).
2. **UTC-нормализация**: значения timestamp из БД приводятся к UTC-aware
   (`core.utils.datetime_utils.ensure_utc`) **до** сравнения; в SQL уходит
   naive-UTC представление (значение «как в колонке»). PG
   `timestamp without time zone` больше не даёт `TypeError`.
3. **Диалекты**: диалект определяется по `engine.dialect.name`, иначе по
   профилю `external_databases`; `LIMIT` → `FETCH FIRST ... ROWS ONLY`
   (Oracle/DB2) или `TOP (...)` (MSSQL). LogMiner — только Oracle (fail-fast с
   понятным сообщением) и с явным `DBMS_LOGMNR.START_LOGMNR` / `END_LOGMNR`.
4. **DSL-путь**: добавлен публичный builder-метод `.cdc_capture(...)`
   (YAML-whitelist принимает только публичные методы `RouteBuilder`),
   `from_cdc_capture` читает записанный `_source_config` и добавляет
   процессор, `CDCCaptureProcessor` подписывается с callback'ом и отдаёт
   события в `result_property`.
5. **Kafka**: bootstrap — из `queue.host/port`, `group_id` — с суффиксом
   подписки (партиции не делятся), poison-offset уходит в DLQ и только потом
   коммитится, consumer закрывается гарантированно (в т.ч. при исключении в
   `subscribe()`), timestamp события сохраняется исходным.
6. **Лимиты**: `CDCClient.subscribe` валидирует стратегию, непустые `tables`,
   `batch_size` (1..10 000), `interval` (0..3600) и число подписок (≤100);
   REST-слой требует непустые `tables` и допускает выбор `strategy`.

## Альтернативы (отклонённые)

1. **Оставить `max(ts)`-курсор и надеяться на уникальные timestamp'ы.** Отклонено:
   timestamp не уникальны по определению — дефект воспроизводится на
   одинаковых значениях (`LOST rows`).
2. **Только дедупликация по payload-хэшу без составного курсора.** Отклонено:
   без PK невозможно paging'ить внутри одинаковых timestamp'ов — часть строк
   всё равно теряется; хэш-дедуп используется только как fallback.
3. **Реализовать LogMiner для всех СУБД.** Отклонено: LogMiner — механизм
   Oracle; для остальных fail-fast с понятным сообщением честнее имитации.
4. **Оставить `is_backend_available("poll") == True` при стабе.** Отклонено:
   poll-backend теперь умеет сам собрать engine по профилю, а listen/notify
   реализован на `asyncpg.add_listener` — availability соответствует факту.

## Последствия

* **Позитивные:** потери строк на границе батча нет; polling работает на
  `timestamp without time zone`; YAML/DSL-путь CDC работоспособен; Kafka
  уважает конфиг брокера, не делит партиции и не теряет poison-offset;
  ограничение выборки валидно для Oracle/MSSQL/DB2.
* **Негативные:** курсор в Redis изменил формат (legacy ISO-курсоры читаются,
  но новые — составные); для таблиц без PK-подобной колонки polling работает
  в ts-only режиме (ограничение документировано и логируется WARNING'ом);
  `CDCSubscribeRequest` стал строже (непустые `tables`, валидная `strategy`).
* **Вне зоны:** `src/backend/core/cdc/registry.py` (`is_backend_available`,
  `get_cdc_source`) — файл не принадлежит кластеру; `ARCHITECTURE.md` —
  статус scaffold'ов в нём устарел.

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/test_cdc_capture.py \
    tests/unit/dsl/engine/processors/test_cdc_transform.py \
    tests/unit/infrastructure/clients/external/cdc tests/unit/infrastructure/cdc \
    -q -p no:randomly
.venv/bin/python -m ruff check <файлы кластера>
.venv/bin/python tools/config_audit.py --scope orphans
.venv/bin/python tools/check_layers.py --strict
```

## Связи с другими ADR

* **ADR-0360** — allowlist-валидация идентификаторов расширена на
  `primary_key`; диалектные LIMIT-клаузы строятся только из проверенных
  идентификаторов.
* **ADR-0379** — принцип «честный статус вместо зелёного»: registry-бэкенды
  либо реализованы, либо сообщают `not_implemented`.
