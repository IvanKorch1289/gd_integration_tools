# ADR-0381 — Драйверы и DSN: совместимость пар (тип СУБД, драйвер), driver-specific connect_args, fail-fast для недостижимых типов

* Статус: Accepted (2026-10-29, wave 16, кластер X2 «Драйверы и DSN»)
* Cycle: 176
* Дата: 2026-10-29
- **Затрагивает**: `src/backend/core/config/database.py`,
  `src/backend/core/config/db_drivers.py`,
  `src/backend/core/enums/database.py`,
  `src/backend/infrastructure/database/database/initializer.py`,
  `ops/compose/Dockerfile`, `config_profiles/base.yml`, `.env.example`,
  `tools/check_dsn_drivers_allowlist.txt`,
  `tests/unit/core/config/test_dsn_*`,
  `tests/unit/infrastructure/database/test_connect_args_by_driver.py`
- **Связан с**: ADR-0363 (psycopg3 как sync-дефолт, fail-fast на
  необъявленный драйвер), ADR-0378 (маскирование секретов в дампах),
  ADR-0335 (unsafe-defaults), ADR-0377 (валидация профилей)

## Контекст

Независимый аудит БД (волна 16, кластер X2) зафиксировал восемь связанных
дефектов контура «драйвер → DSN → engine»:

1. **psycopg3-async сломан.** `DatabaseInitializer._get_connect_args` выбирал
   набор опций по `is_async`, а не по имени драйвера: async-движок всегда
   получал опции asyncpg (`command_timeout`, `timeout`). С psycopg3 (дефолт
   по ADR-0363) это давало
   `psycopg.ProgrammingError: invalid connection option "command_timeout"`.
2. **Несовместимые пары (тип, драйвер) не проверялись.** `base.yml` задаёт
   `async_driver: asyncpg` / `sync_driver: psycopg` глобально; при смене
   `type` на `mssql`/`mysql` DSN собирался как `mssql+asyncpg://` →
   `NoSuchModuleError` уже в рантайме.
3. **DB2 недостижим.** Диалект `sqlalchemy.dialects.db2` удалён в SQLAlchemy
   2.0, драйвер `ibm_db_sa` не объявлен ни в одном extra — тип обещал
   поддержку, которой нет.
4. **ClickHouse DSN невалиден.** `_build_dsn` отдавал `clickhouse://` — для
   SQLAlchemy такого диалекта нет; клиент живёт отдельно
   (`infrastructure/clients/storage/clickhouse.py`).
5. **SQLite игнорировал настройки пула** без объяснения.
6. **Ретраи подключения были мёртвыми:** `database.max_retries: 0` в
   `base.yml` и ни один профиль не переопределял значение.
7. **В образе compose не было psycopg:** `ops/compose/Dockerfile` ставил
   только `--extra dev-light`, а psycopg живёт в extra `sources-cdc`.
8. **`replica_dsn` — plain `str` с паролем** (ADR-0378 закрыла маскирование
   только для DSN'ов primary-БД).

## Решение

### (а) Матрица совместимости пар и fail-fast

`core/config/db_drivers.py` (stdlib-only, его импортирует CI-гейт):

* `DB_TYPE_DRIVER_PAIRS` — тип СУБД → допустимые драйверы для `async`/`sync`
  (postgresql: asyncpg/psycopg + psycopg; oracle: oracledb; mssql: aioodbc +
  pyodbc; mysql: aiomysql + pymysql);
* `UNSUPPORTED_SQLALCHEMY_DB_TYPES` — DB2 и ClickHouse с объяснением, куда
  идти вместо DSN;
* `ensure_db_type_supported()` / `ensure_driver_pair_supported()` —
  `DatabaseDriverError` с перечислением допустимых драйверов.

Порядок проверок в `_build_dsn`: тип → наличие/объявленность драйвера →
совместимость пары. Несовместимость проверяется последней, чтобы для
необъявленного драйвера сообщало «не объявлен в extra», а не «несовместим».

### (б) `connect_args` — по имени драйвера

`_get_connect_args` определяет драйвер (`async_driver`/`sync_driver`) и
выбирает набор опций: `asyncpg` → `command_timeout`/`timeout`;
`psycopg` (v3, libpq) → `connect_timeout` + `options='-c statement_timeout=...'`.
Опции SSL-контекста не изменились (применимы к обоим драйверам).

### (в) DB2 и ClickHouse — fail-fast, не удаление из enum

`DatabaseTypeChoices.db2`/`clickhouse` остаются в enum: на них ссылается
внешний контур (`infrastructure/database/external_database_facade.py`,
`dsl/engine/processors/db_call_procedure.py` — вне зоны кластера). В DSN-контуре
оба типа отвергаются с объяснением (ADR-0381). Ветки `db2+...` и
`clickhouse://` из `_build_dsn` удалены как мёртвые; allowlist
`tools/check_dsn_drivers_allowlist.txt` очищен (запись `ibm_db_sa`).

### (г) SQLite: пул не настраивается — осознанно

`pool_size`/`max_overflow`/`pool_timeout` к SQLite не применяются: у
`:memory:` SQLAlchemy использует `StaticPool`, который эти параметры не
принимает (`TypeError`), а записи в файловую SQLite блокируются на уровне
файла. Поведение зафиксировано docstring'ом `_engine_kwargs` и тестом.

### (д) Ретраи подключения

`config_profiles/base.yml`: `database.max_retries: 0` → `3`
(`session_manager.py`: `max_attempts = max_retries + 1`, повтор только при
`OperationalError`/`InterfaceError` на установке соединения).

### (е) Образ compose

`ops/compose/Dockerfile`: `--extra dev-light` → `--extra dev-light
--extra sources-cdc` (psycopg3). Extra `db_drivers` не добавляется: ODBC-
драйверы требуют системных библиотек, которых в образе нет.

### (ж) `replica_dsn` — секрет

`replica_dsn: SecretStr | None` + `@field_serializer` с маскированием
пароля в `model_dump()`/`model_dump_json()` (по образцу ADR-0378). Рабочее
значение (`get_secret_value()`) использует инициализатор при создании
replica-engine. `DB_REPLICA_DSN` добавлен в `.env.example`.

## Альтернативы

* **Удалить `db2`/`clickhouse` из enum** — отклонено: два файла вне зоны
  кластера ссылаются на эти значения (`external_database_facade.py:300`,
  `db_call_procedure.py:153`), их правка потянула бы изменения за периметром
  кластера. Fail-fast в DSN-контуре даёт тот же эффект для пользователя.
* **Применять pool-параметры к файловой SQLite** — отклонено: пул SQLite
  увеличивает число конкурентных писателей и время ожидания блокировки
  файла; дефект допускал вариант «задокументировать».
* **Оставить `max_retries: 0` и задокументировать** — отклонено: настройка
  уже читается `session_manager.py`, отключение повторов при падении БД —
  тихий отказ, который дешевле устранить дефолтом.
* **Маскировать `replica_dsn` только в `repr`** — отклонено: `repr=False` не
  влияет на `model_dump()` (ровно тот дефект, что закрыл ADR-0378).

## Последствия

* Старт приложения с `type: mssql`/`mysql` без явных драйверов теперь
  падает **на старте** с понятным сообщением вместо `NoSuchModuleError` в
  рантайме; sync-движок при этом деградирует до `None` (graceful-degradation
  не изменился).
* psycopg3 как async-драйвер PostgreSQL работает: опции таймаутов
  libpq-стиля.
* БД недоступна на старте → до 3 повторов установки соединения.
* `model_dump()` настроек БД больше не содержит пароль реплики.

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/core/config/test_dsn_driver_pairs.py \
    tests/unit/core/config/test_dsn_driver_availability.py \
    tests/unit/core/config/test_dsn_mssql_mysql_db2.py \
    tests/unit/core/config/test_dsn_replica_secret.py \
    tests/unit/infrastructure/database/test_connect_args_by_driver.py -q
.venv/bin/python tools/config_audit.py --scope orphans      # rc=0
.venv/bin/python tools/check_layers.py --strict             # 41 (без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
.venv/bin/python tools/check_dsn_drivers.py --ci --scope declarations  # rc=0
```

## Связи

* ADR-0363 — psycopg3 как sync-дефолт и fail-fast на необъявленный драйвер.
* ADR-0378 — маскирование секретов в дампах (`replica_dsn` — тот же приём).
* ADR-0377 — валидация профилей (значения драйверов в overlay-профилях).
