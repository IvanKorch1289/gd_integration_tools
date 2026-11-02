# ADR-0418 — Лимиты выборки, retry на сериализацию, savepoint'ы и гварды batch-шагов (волна 24, кластер F3)

* Статус: Accepted (2026-11-02, волна 24, кластер F3 — аудит лимитов и надёжности БД)
* Cycle: 183 (волна 24)
* Связан с:
  - ADR-0393 (capability-гейт, tenant-скоуп и лимит выборки у DSL-шагов БД — этот ADR доводит лимит до БД и добавляет гварды batch-шагов),
  - ADR-0383 / ADR-0386 (fail-closed raw-SQL guard, RLS-скоуп),
  - ADR-0382 (тип результата по факту, а не по префиксу SQL; диалектные правила quoting),
  - ADR-0381 (driver-specific `connect_args`: asyncpg / psycopg — расширено на MySQL, MSSQL, Oracle),
  - ADR-0365 (канон валидации SQL-идентификаторов),
  - ADR-0366 (runtime-резолвер capability),
  - ADR-0305 (консолидация circuit breaker'ов), ADR-0399 (единый retry поверх tenacity)
* Затрагивает:
  - `src/backend/dsl/engine/processors/_sql_validation.py` (общий helper выборки),
  - `src/backend/dsl/engine/processors/components/databasequeryprocessor.py`,
  - `src/backend/dsl/engine/processors/jdbc_query.py`,
  - `src/backend/dsl/engine/processors/db_query_external.py`,
  - `src/backend/dsl/engine/processors/infra_db.py`,
  - `src/backend/dsl/engine/processors/batch.py`,
  - `src/backend/infrastructure/database/session_manager.py`,
  - `src/backend/infrastructure/database/database/initializer.py`,
  - `tests/unit/dsl/engine/processors/test_adr0418_*.py`,
  - `tests/unit/infrastructure/database/test_adr0418_*.py`

---

## Контекст

Мультироевой аудит (волна 24, кластер F3) нашёл четыре дефекта в слое
доступа к БД.

**(1) Лимит выборки применялся ПОСЛЕ вытягивания результата [high].**
`MAX_RESULT_ROWS = 1000` объявлен ещё в ADR-0393, но ни один шаг его не
применял «на базе»:

```python
rows = [dict(row._mapping) for row in result.fetchall()]   # весь результат в память
rows, truncated = limit_rows(rows, limit=self._max_rows)   # обрезка после
```

Проба: `rows fetched from DB by fetchall(): 5000` → `kept after
limit_rows: 1000`. Один `SELECT * FROM big_table` в DSL-роуте вытягивал
в память процесса весь результат — DoS по памяти (и «съедание» воркера).
Затронуты были все четыре SQL-шага: `databasequeryprocessor.py:163`,
`jdbc_query.py:179`, `db_query_external.py:255`, `infra_db.py:198`.

**(2) Нет retry на сериализацию и нет savepoint'ов [medium].**
`_RETRYABLE_CONNECT_ERRORS` в `session_manager.py` содержал только
`OperationalError` / `InterfaceError` и срабатывал исключительно на
этапе `connect`. PostgreSQL-конфликты сериализации (SQLSTATE `40001`) и
дедлоки (`40P01`) — типичный сценарий двух конкурирующих транзакций —
не повторялись вовсе: операция падала с первой попытки. `begin_nested`
— 0 совпадений по репозиторию: тело транзакции шло без SAVEPOINT,
поэтому ошибка тела откатывала **всю** транзакцию.

**(3) `connect_timeout` / `command_timeout` мертвы для MySQL и MSSQL
[medium].** `DatabaseInitializer._get_connect_args` обрабатывал только
PostgreSQL и Oracle (и у Oracle — только connect-таймаут). Проба:
`mysql async={}`, `oracle async={'tcp_connect_timeout': 10}` —
statement-timeout'а нет ни там, ни там.

**(4) `batch_insert` / `batch_update` / `batch_delete` — без защитного
контура [medium].** В отличие от `db_crud` / `db_query` у batch-шагов
не было:
* `required_capability` (шаг писал в любую внешнюю БД);
* квотирования идентификаторов (`f"INSERT INTO {self._table} ..."`);
* tenant-скоупа;
* лимита размера батча;
* валидного профиля по умолчанию — `profile="default"` не существует, и
  каждый такой шаг падал с `DatabaseError`.

---

## Решение

### 1. Лимит выборки — на базе, а не после

Общий helper `fetch_limited_rows(result, *, limit)` в
`_sql_validation.py` забирает из курсора `limit + 1` строк
(`fetchmany`), а не весь результат (`fetchall`):

* **«лишняя» строка — маркер усечения.** Если вернулось `limit + 1`
  строк, значит в выборке есть ещё данные: результат помечается
  усечённым (`db_truncated = True` в `Exchange.properties`), а сама
  `limit`-я строка в payload **не** попадает. Ошибкой выборка не
  считается — это штатное поведение «первые N строк»;
* payload не меняет форму (по-прежнему `list[dict]`), поэтому
  потребители шагов не ломаются; маркер — отдельное свойство;
* все четыре шага переведены на helper: `databasequeryprocessor.py`,
  `jdbc_query.py`, `db_query_external.py`, `infra_db.py`.

**Предел и путь апгрейда (ponytail).** `AsyncSession.execute()` и
`AsyncConnection.execute()` в SQLAlchemy 2.0 возвращают **буферизованный**
`CursorResult`: у asyncpg драйвер вытягивает строки в буфер на своей
стороне. Поэтому ограничение гарантирует, что в память процесса
попадёт не более `limit + 1` строк, но не гарантирует, что БД не
передаст их драйверу. Настоящий «лимит на стороне БД» требует
`LIMIT` в SQL либо server-side курсора (`session.stream()` /
`execution_options(stream_results=True)`) — последний поддержан не всеми
диалектами (aiosqlite — нет) и ломает переносимость, поэтому в этой
волне не применяется.

### 2. Retry на сериализацию — только BEGIN-этап; тело — под SAVEPOINT

* `pg_sqlstate(exc)` / `is_retryable_transaction_error(exc)` — распознавание
  SQLSTATE из `exc.orig` (asyncpg: `sqlstate`, psycopg: `sqlstate`);
  повторяемые коды — `40001` (serialization_failure) и `40P01`
  (deadlock_detected);
* `DatabaseSessionManager.transaction()` открывает транзакцию и
  SAVEPOINT на её тело. **Повтор делается только на этом этапе**: тело
  транзакции ещё не выполнялось, частичных записей нет — повтор
  безопасен. Backoff — экспоненциальный, через единый
  `core.resilience.retry.retry_async` (tenacity). Тело транзакции
  **не** переигрывается (оно не идемпотентно);
* ошибка тела откатывает **savepoint** (`ROLLBACK TO SAVEPOINT`), а не
  всю транзакцию: внешняя транзакция остаётся открытой, и вызывающий
  может её продолжить;
* `retry_async` умеет повторять только по типу исключения, поэтому
  ошибка с распознанным pgcode пере-оборачивается во внутренний маркер
  `RetryableTransactionError`, а исходная ошибка БД возвращается
  вызывающему после исчерпания попыток.

### 3. Таймауты подключения и запроса — по драйверам

| СУБД (драйвер) | connect-timeout | statement-timeout |
|---|---|---|
| PostgreSQL (asyncpg) | `timeout` | `command_timeout` (было) |
| PostgreSQL (psycopg) | `connect_timeout` | `options='-c statement_timeout=…'` (было) |
| MySQL (aiomysql / pymysql) | `connect_timeout` | `init_command='SET SESSION max_execution_time=…'` |
| MSSQL (aioodbc / pyodbc) | `timeout` (ODBC `SQL_ATTR_LOGIN_TIMEOUT`) | — (см. предел) |
| Oracle (oracledb) | `tcp_connect_timeout` | `call_timeout` |

* **Oracle:** `call_timeout` oracledb **не принимает** в `connect()`
  (`TypeError: connect_async() got an unexpected keyword argument
  'call_timeout'`) — это свойство уже установленного соединения.
  Поэтому значение возвращается в `_get_connect_args()` (единый источник
  опций), но в `connect_args` движка не попадает: `_engine_kwargs()`
  отделяет такие ключи (`_POST_CONNECT_SETTINGS`), а
  `_apply_post_connect_settings()` выставляет их на соединении через
  `connect`-event;
* **Пределы (ponytail).** MySQL: `max_execution_time` действует только на
  read-only запросы (для DML нужен `max_statement_time`, MySQL 8.0.26+).
  MSSQL: лимит времени выполнения запроса (`SQL_ATTR_QUERY_TIMEOUT`)
  задаётся per-cursor и через `connect_args` не передаётся.

### 4. Гварды batch-шагов

* **Capability-гейт:** `required_capability = "db.write"` + `auth_check`
  (тот же канон, что у `db_crud` / `db_query`);
* **Квотирование идентификаторов:** таблица, колонки и ключ оборачиваются
  в кавычки по правилам диалекта целевой СУБД (канонический квотер
  `db_crud._quote_identifier`, ADR-0382). Диалект берётся из
  `bundle.settings.type`;
* **Tenant-скоуп:** для **основной** БД скоуп определяется автоматически
  по реестру tenant-aware таблиц (как в `db_crud`) и обязателен: без
  tenant-контекста — fail-closed (`TenantIsolationError`), значение
  чужого tenant'а в данных — тоже отказ. Для **внешней** БД схема
  неизвестна, поэтому столбец tenant'а задаётся явно
  (`tenant_column="tenant_id"`);
* **Лимит батча:** `max_batch` (по умолчанию `MAX_BATCH_ROWS = 1000`);
  превышение — понятная ошибка «разбейте операцию на несколько шагов»;
* **Валидный профиль по умолчанию:** `profile="default"` теперь означает
  **основную БД приложения** (`AUTO_PROFILE`) — единственную БД, которая
  существует всегда. Раньше дефолт указывал на несуществующий профиль
  внешней БД, и каждый такой шаг падал с `DatabaseError`. Явно заданный
  профиль → внешняя БД из реестра (несуществующий профиль даёт понятную
  ошибку реестра).

---

## Альтернативы

* **Ошибка вместо маркера усечения.** Отклонено: «первые N строк» —
  штатный режим пагинации; ошибка ломала бы обычные выборки без
  `ORDER BY`, а маркер даёт вызывающему ту же информацию без ложной
  тревоги;
* **`LIMIT` в SQL.** Отклонено: шаг принимает произвольный SQL
  (включая `WITH … SELECT` и DML с `RETURNING`), автоматическая
  вставка `LIMIT` ломает семантику запроса и не переносима между
  диалектами;
* **`stream()` (server-side cursor).** Отклонено в этой волне: не все
  диалекты поддерживают server-side курсоры (aiosqlite — нет), поэтому
  переносимость DSL-шагов падает. Зафиксировано как путь апгрейда;
* **Свой retry-цикл в `session_manager.py`.** Отклонено: проект
  консолидирует retry поверх tenacity (`core.resilience.retry`); новая
  реализация размножила бы две семантики backoff;
* **Retry тела транзакции.** Отклонено: тело не идемпотентно — повтор
  после частичной записи продублировал бы данные. Повтор ограничен
  BEGIN-этапом;
* **Полный откат транзакции вместо savepoint'а.** Отклонено: теряется
  работа, сделанная до savepoint'а внутри той же транзакции;
* **Batch → отдельный профиль по умолчанию из конфигурации.** Отклонено:
  выбор профиля зависит от окружения; «default» → основная БД
  детерминирован и всегда валиден.

---

## Последствия

* **Позитивные:** лимит выборки ограничивает память процесса уже на
  уровне материализации; сериализационные конфликты переживаются
  повтором вместо отказа операции; ошибка тела транзакции не сбрасывает
  внешнюю транзакцию; batch-шаги получили capability-гейт, tenant-скоуп,
  квотирование и лимит размера; дефолтный профиль batch-шага работоспособен;
* **Изменения контракта шагов:** появляется свойство `db_truncated`
  (`True`) — сигнал усечения выборки; batch-шаги при отсутствии
  tenant-контекста на tenant-aware таблице основной БД теперь
  fail-closed; `profile="default"` у batch-шагов означает основную БД
  (для внешних БД профиль указывается явно);
* **Ограничения:** statement-timeout для MSSQL (ODBC
  `SQL_ATTR_QUERY_TIMEOUT`) не выставляется — требует per-cursor
  настройки; `max_execution_time` в MySQL не покрывает DML;
  драйверная буферизация результата (asyncpg) остаётся — лимит
  ограничивает память процесса, но не трафик БД→драйвер;
* **Совместимость:** SQL-текст batch-шагов теперь содержит кавычки
  идентификаторов (`"orders"` вместо `orders`) — это корректно для всех
  поддерживаемых диалектов и снимает проблему зарезервированных слов.

---

## Проверка

* `tests/unit/dsl/engine/processors/test_adr0418_db_result_limits.py` —
  лимит применяется к курсору (`fetchmany(limit + 1)`), `fetchall()` не
  вызывается, маркер усечения выставляется (7 тестов);
* `tests/unit/infrastructure/database/test_adr0418_transaction_retry_savepoint.py` —
  распознавание pgcode, повтор BEGIN-этапа на `40001`, откат savepoint
  без отката всей транзакции (11 тестов);
* `tests/unit/infrastructure/database/test_adr0418_connect_timeouts.py` —
  `connect_args` для MySQL / MSSQL / Oracle, post-connect выставление
  `call_timeout` (11 тестов);
* `tests/unit/dsl/engine/processors/test_adr0418_batch_guards.py` —
  capability-гейт, квотирование, tenant-скоуп, лимит батча, профиль по
  умолчанию (18 тестов);
* гейты: `ruff check` (0), `tools/config_audit.py --scope orphans` (0),
  `tools/check_layers.py --strict` (41 — без изменений),
  `tools/checks/mypy_budget.py` (OK), `tools/check_docstrings.py` (0).

---

## Связи

* ADR-0393 — capability-гейт, tenant-скоуп и лимит выборки у DSL-шагов БД;
* ADR-0382 — тип результата по факту и диалектные правила quoting;
* ADR-0381 — driver-specific `connect_args`;
* ADR-0365 — канон валидации SQL-идентификаторов;
* ADR-0366 — runtime-резолвер capability-гейта;
* `docs/roadmap/PROD_READINESS_GAPS.md` — prod-readiness (ревизии волны 24).
