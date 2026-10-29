# ADR-0386 — Tenant-guard для `Connection.execute` и RLS на всех tenant-таблицах

* Статус: Accepted (2026-10-29, wave 17, кластер T1 — «TENANT-GUARD ДЛЯ CONNECTION.execute + RLS НА ВСЕХ TENANT-ТАБЛИЦАХ»)
* Дата: 2026-10-29
- **Затрагивает**:
  - `src/backend/core/tenancy/sqlalchemy_filter.py`
  - `src/backend/infrastructure/database/tenant_filter.py` (shim → canonical)
  - `src/backend/infrastructure/database/migrations/versions/2026_10_29_1200-e2f3a4b5c6d7_rls_all_tenant_tables.py` (новая миграция)
  - `tests/unit/core/tenancy/test_tenant_rls_session_scope.py`
  - `tests/unit/core/tenancy/test_connection_execute_gate.py`
  - `tests/unit/infrastructure/database/test_rls_all_tenant_tables.py`
- **Связан с**:
  - ADR-0383 (fail-closed guard для raw SQL на уровне ORM-сессии)
  - ADR-0347 (tenant-изоляция на границе), ADR-0345 (ownership-семантика tenant_id)
  - ADR-0382 / ADR-0380 (валидация SQL в DSL-процессорах)
- **Вне зоны (нужны чужие файлы)**:
  - `src/backend/infrastructure/database/rls_listener.py` — ставит `app.tenant_id`
    под feature-flag'ом `rls_postgres_enforce`; после этого ADR каноническая
    установка живёт в ORM-фильтре (без флага). При включённом флаге SET
    выполняется дважды (идемпотентно) — унификация вынесена за пределы
    волны 17.
  - `src/backend/infrastructure/messaging/dlq/inbox_writer.py`,
    `src/backend/services/scheduler/*`,
    `src/backend/infrastructure/resilience/snapshot_job.py` — фоновые и
    привилегированные пути вне tenant-контекста; после появления
    tenant-скоупа (или перехода на роль с BYPASSRLS) их можно включить в
    RLS (см. «Последствия»).
  - `src/backend/dsl/engine/processors/components/databasequeryprocessor.py` —
    DSL-процессор «сырой SQL» намеренно обходит tenant-guard; разбор
    (на уровне профиля БД / capability) — вне зоны wave 17.

## Контекст

Свип wave 17 нашёл два связанных дефекта tenant-изоляции.

1. **[high] `Connection.execute(text(...))` — привилегированный путь мимо
   guard'а.** Tenant-guard живёт в session-level событии `do_orm_execute`
   (`core/tenancy/sqlalchemy_filter.py`). `Connection.execute(text(...))`
   идёт на Core-уровень, это событие его не видит — ORM-фильтр и
   fail-closed raw-SQL guard (ADR-0383) не применяются. Реальные вызовы в
   `src/`: `infrastructure/cdc/poll_backend.py:207`,
   `infrastructure/clients/external/cdc/strategies.py:304,327,624,640`,
   `infrastructure/resilience/components/database_chain.py:124`,
   `infrastructure/database/pool_warmup.py:267`,
   `plugins/composition/setup_infra/pools.py:51`. Это инфраструктурные
   пути (CDC — отдельный профиль/подписка, warmup — `SELECT 1`, chain —
   внутренний retry-обход), не бизнес-запросы, но контракт «`Connection` —
   привилегированный путь» нигде не был зафиксирован и не проверялся.
   Проверка бизнес-слоя (`dsl/`, `services/`) показала три вызова:
   `dsl/engine/processors/components/databasequeryprocessor.py:89`
   (произвольный SQL с валидацией), `dsl/engine/processors/ml_inference.py:369`
   (transactional outbox — таблица `outbox_messages` без `tenant_id`) и
   `dsl/engine/processors/storage_ext.py:195` (time-series writer — таблица
   без `tenant_id`).
2. **[high] RLS — только на трёх таблицах.** Миграция
   `2026_05_22_1000-f2a3b4c5d6e7_s21_rls_workflow_instance.py` (+ S21 W8)
   включила RLS для `workflow_instances`, `workflow_state` и
   `rule_engine_rulesets`, тогда как колонка `tenant_id` к этому моменту
   была у одиннадцати таблиц (`orders`, `users`, `files`, `dsl_snapshots`,
   `workflow_events`, `orderkinds` — миграции S89/S91/S92/S101/S171;
   `scheduler_run_history` — ADR-0346; `dlq_inbox` — FW1;
   `audit_log_immutable` — append-only аудит). Частичное покрытие даёт
   ложное чувство защиты: RLS как defense-in-depth работает только там,
   где политика реально есть.

Дополнительно: RLS-политики читают `current_setting('app.tenant_id', true)`,
а значение выставлялось только feature-flag'ом `rls_postgres_enforce`
(`infrastructure/database/rls_listener.py`). То есть при выключенном флаге
включённая RLS отсекала бы все tenant-строки — приложение обязано задавать
`app.tenant_id` всегда, а не «по флагу».

## Решение

### 1. `Connection` — привилегированный путь, зафиксированный контрактом

* `Connection.execute(text(...))` разрешён **только инфраструктуре**.
  Бизнес-слой (`src/backend/dsl/**`, `src/backend/services/**`) обязан
  использовать `Session` — ORM-путь фильтруется, session-level raw SQL
  проходит fail-closed guard'ом ADR-0383.
* Осознанно привилегированные callsites (перечень в этом ADR):
  * CDC — `infrastructure/cdc/poll_backend.py:207`,
    `infrastructure/clients/external/cdc/strategies.py:304,327,624,640`:
    собственный профиль БД / подписка на лог транзакций, tenant-скоуп не
    применяется;
  * `infrastructure/database/pool_warmup.py:267` и
    `plugins/composition/setup_infra/pools.py:51` — прогрев пула, `SELECT 1`;
  * `infrastructure/resilience/components/database_chain.py:124` — внутренний
    retry-обход (chain переподключается к БД мимо сессии).
* Контракт зафиксирован в docstring
  `core/tenancy/sqlalchemy_filter.py` и проверяется гейтом
  `tests/unit/core/tenancy/test_connection_execute_gate.py`: AST-скан
  `dsl/**` + `services/**` ищет `*.execute(text(...))` у получателя, не
  являющегося сессией. Найденные вызовы обязаны быть в allowlist-базе
  гейта с обоснованием; новый неallowlisted-вызов роняет тест.

### 2. RLS на всех tenant-таблицах (новая миграция)

`2026_10_29_1200-e2f3a4b5c6d7_rls_all_tenant_tables` включает RLS +
`FORCE ROW LEVEL SECURITY` + политику для всех tenant-таблиц:
`workflow_instances`, `workflow_state`, `rule_engine_rulesets`, `orders`,
`users`, `files`, `dsl_snapshots`, `workflow_events`, `orderkinds`.

* Политика: `tenant_id = current_setting('app.tenant_id', true)`; для
  nullable `tenant_id` (`rule_engine_rulesets`) — `tenant_id IS NULL OR ...`
  (глобальные строки остаются видимыми, как в политике S21). `USING` и
  `WITH CHECK` совпадают, поэтому глобальная строка проходит и на запись.
* PostgreSQL-only: на других диалектах — no-op с комментарием.
* Идемпотентно: `DO $$ ... IF EXISTS (information_schema) ... $$` —
  отсутствующие в установке extension-таблицы пропускаются; legacy-политики
  S21 (`tenant_isolation_wfi` и др.) удаляются, чтобы на таблице не
  осталось двух политик.
* Осознанно **вне** RLS (см. `EXCLUDED_TABLES` миграции):
  `audit_log_immutable` (append-only аудит, запись из системного контура),
  `dlq_inbox` (фоновая запись DLQ вне tenant-контекста),
  `scheduler_run_history` (scheduler работает вне tenant-контекста,
  `tenant_id` опционален). Для последних двух — follow-up: связать
  tenant-скоуп в writer'е/scheduler'е, затем включить RLS.

### 3. `app.tenant_id` ставится там же, где ORM-фильтр

В `core/tenancy/sqlalchemy_filter.py` добавлено session-событие
`after_begin` → `_set_tenant_scope_on_begin`: при активном tenant-контексте
выполняется `SELECT set_config('app.tenant_id', :tenant_id, true)`
(bind-параметр — SQL-инъекция невозможна; `true` — transaction-local,
значение не наследуется следующей транзакцией). PostgreSQL-only; ошибка SET
логируется warning'ом и не роняет запрос. Так RLS работает независимо от
feature-флага `rls_postgres_enforce`.

### 4. RLS — defense-in-depth, приложение обязано задавать `app.tenant_id`

ORM-фильтр — первый рубеж, RLS — второй. Если `app.tenant_id` не задан,
`current_setting('app.tenant_id', true)` возвращает `NULL`: strict-политики
не пропустят ни одной строки (fail-closed), а global-политики
(`tenant_id IS NULL OR ...`) пропустят глобальные строки. Поэтому
**приложение обязано задавать `app.tenant_id` в каждой транзакции** —
иначе tenant-скоуп не обеспечен (либо пустой результат, либо видимость
глобальных строк).

## Альтернативы

1. **Расширить guard на Core-уровень (`ConnectionEvents.before_execute`).**
   Отклонено: безопасная автоподстановка `tenant_id` в произвольный SQL
   невозможна (CTE/UNION/subquery — как в ADR-0383), а fail-closed на
   Core-уровне заблокировал бы легитимные инфраструктурные вызовы.
   Выбрана явная привилегированность + проверяемый гейт.
2. **Фасад `GuardedConnection` вместо прямого `Connection`.** Отклонено:
   один implementation — лишняя абстракция (YAGNI); инфраструктурные
   вызовы и так единичны и перечислены.
3. **Оставить RLS на трёх таблицах S21.** Отклонено: частичное покрытие —
   ложная защита; defense-in-depth либо есть, либо нет.
4. **Включить RLS также для `dlq_inbox` и `scheduler_run_history`.**
   Отклонено: оба пишутся фоновым кодом вне tenant-контекста — `WITH
   CHECK` отклонил бы tenant-tagged записи, а чтение скрыло бы per-tenant
   строки (риск двойного исполнения тика scheduler'а). Вместо этого —
   явное исключение с follow-up.
5. **`SET LOCAL app.tenant_id = '<literal>'.** Отклонено: literal —
   SQL-инъекция; `set_config` с bind-параметром безопасен и dialect-agnostic
   (в отличие от `exec_driver_sql` с `%s`, который несовместим с asyncpg).
6. **Выставлять `app.tenant_id` только под feature-флагом (как сейчас в
   `rls_listener`).** Отклонено: после включения RLS на всех таблицах
   фича-флаг стал бы «рубильником» tenant-изоляции.

## Последствия

* **Позитивные:** привилегированность `Connection` объявлена и проверяется
  гейтом (новые обходы в бизнес-слое роняют CI); RLS покрывает все
  tenant-таблицы, а не три из одиннадцати; `app.tenant_id` ставится
  независимо от feature-флага; состав списка tenant-таблиц проверяется
  тестом, выводящим список из миграций — новая tenant-таблица не может
  остаться без RLS «молча».
* **Негативные / breaking:** на PostgreSQL запрос к tenant-таблице вне
  tenant-контекста возвращает 0 строк (fail-closed) — это ожидаемо, но
  фоновые процессы обязаны работать вне tenant-скоупа только с
  неtenant-ными таблицами; legacy-политики S21 заменены каноническими
  (`tenant_isolation_<table>`) — при откате миграции они восстанавливаются;
  на каждую транзакцию в PostgreSQL добавляется один round-trip (`SET`).
* **Привилегированные читатели:** snapshot-job (PG → SQLite, реплицирует
  `orderkinds`/`users`/`orders`) читает таблицы через Core-`Connection` вне
  tenant-контекста — с включённой RLS он получит 0 строк вместо данных.
  По контракту S21 такие операции (миграции, backup/snapshot) выполняются
  ролью с `BYPASSRLS` (`app_migrator`) либо внутри tenant-скоупа. Правка
  `infrastructure/resilience/snapshot_job.py` и его конфигурации — вне зоны
  wave 17 (зафиксировано как follow-up).
* **Дублирование:** при включённом `rls_postgres_enforce` значение
  выставляется дважды — старым `rls_listener` и новым session-event
  (идемпотентно, но лишний round-trip). Унификация — вне зоны wave 17.
* **Не выполнено (вне зоны):** разбор DSL-процессора «сырой SQL»
  (`databasequeryprocessor`), tenant-скоуп в DLQ-writer'е и scheduler'е,
  унификация с `rls_listener`.

## Проверка

```bash
.venv/bin/python -m pytest \
    tests/unit/core/tenancy/test_tenant_rls_session_scope.py \
    tests/unit/core/tenancy/test_connection_execute_gate.py \
    tests/unit/infrastructure/database/test_rls_all_tenant_tables.py -q
.venv/bin/python -m pytest tests/unit/core/tenancy tests/unit/infrastructure/database -q
.venv/bin/ruff check src/backend/core/tenancy/sqlalchemy_filter.py \
    src/backend/infrastructure/database/tenant_filter.py \
    src/backend/infrastructure/database/migrations/versions/2026_10_29_1200-e2f3a4b5c6d7_rls_all_tenant_tables.py
.venv/bin/python tools/config_audit.py --scope orphans      # 0
.venv/bin/python tools/check_layers.py --strict             # 41 (без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
```

## Связи с другими ADR

* **ADR-0383** — базовый fail-closed guard для raw SQL: настоящий ADR
  достраивает его до Core-уровня (контракт привилегированности + гейт) и
  до уровня БД (RLS).
* **ADR-0347** — tenant-изоляция на границе: `app.tenant_id` ставится из
  того же tenant-контекста, что и ORM-фильтр.
* **ADR-0345** — ownership-семантика `tenant_id` в `scheduler_run_history`:
  таблица исключена из RLS до появления tenant-скоупа в scheduler'е.
* **ADR-0382 / ADR-0380** — валидация SQL в DSL: привилегированные вызовы
  в DSL допустимы только там, где SQL валидируется и таблица не является
  tenant-таблицей.
