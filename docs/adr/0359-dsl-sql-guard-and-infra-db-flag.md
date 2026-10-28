# ADR-0359 — Канонический SQL-guard для DSL и fail-closed flag для `infra_db_query` (cycle 172)

* Статус: Accepted (2026-10-27, cycle 172)
* Cycle: 172
* Связан с:
  - [ADR-0112](0112-security-audit-status.md) — allowlist/escape-паттерн для SQL
  - [ADR-0109a](0109a-script-runner-dsl.md) — fail-closed для RCE-класса DSL-шага
  - [ADR-0361](0361-capability-enforcement-required-capability-semantics.md) — capability-барьер для SQL-процессоров (отдельная задача)
* Затрагивает:
  - `src/backend/dsl/engine/processors/_sql_validation.py`
  - `src/backend/dsl/engine/processors/infra_db.py`
  - `src/backend/dsl/engine/processors/db_query_external.py`
  - `src/backend/dsl/engine/processors/duckdb_query.py`
  - `src/backend/dsl/engine/processors/infra_clickhouse.py`
  - `src/backend/dsl/engine/processors/components/databasequeryprocessor.py`
  - `src/backend/dsl/engine/processors/jdbc_query.py`
  - `src/backend/core/config/features/dsl.py`

## Контекст

### `infra_db_query`: произвольный SQL без runtime capability и нерабочий runtime

До Wave 13 DSL-шаг `infra_db_query` выполнял произвольный SQL к
внутренней БД. Runtime capability-барьера у него не было: запись
`capabilities=("db.read",)` в реестре процессора была метаданными, но
не заменяла `required_capability`/`auth_check`.

Шаг был также нерабочим в SQLAlchemy 2.x:

- в БД передавалась «сырая» строка вместо `sqlalchemy.text(...)`, из-за
  чего runtime получал `ObjectNotExecutableError`;
- вызывался несуществующий у session manager метод `session()` вместо
  `create_session()`.

Эти дефекты и требования к исправлению зафиксированы в
`src/backend/dsl/engine/processors/infra_db.py:10-27`.

### Guard был неоднородным

Один и тот же запрет DDL/privilege-команд и multi-statement был
реализован копиями `_validate_sql` в `jdbc_query`,
`components/databasequeryprocessor` и `infra_db`. При этом
`db_query_external`, `duckdb_query` и `infra_clickhouse` вообще не
проходили этот guard.

## Решение

### 1. Единый helper

Создан канонический модуль
`src/backend/dsl/engine/processors/_sql_validation.py` с API
`FORBIDDEN_SQL` и `validate_sql()` (строки 1-48).

`validate_sql()`:

- запрещает multi-statement (`;` внутри запроса);
- запрещает команды `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `GRANT`,
  `REVOKE`;
- сравнивает первое слово запроса с allowlist запрещённых команд.

Запрещённый набор и правила проверки находятся в
`src/backend/dsl/engine/processors/_sql_validation.py:26-48`.

Три бывшие копии теперь используют общий helper:
`src/backend/dsl/engine/processors/jdbc_query.py:64-93`,
`src/backend/dsl/engine/processors/components/databasequeryprocessor.py:48-58`,
`src/backend/dsl/engine/processors/infra_db.py:137-141`.

### 2. Guard в процессорах с произвольным SQL

| Процессор | Проверка до обращения к БД |
|---|---|
| `infra_db_query` | `src/backend/dsl/engine/processors/infra_db.py:125-151` |
| `db_query_external` | `src/backend/dsl/engine/processors/db_query_external.py:108-129` |
| `duckdb_query` | `src/backend/dsl/engine/processors/duckdb_query.py:89-105` |
| `infra_clickhouse_query` | `src/backend/dsl/engine/processors/infra_clickhouse.py:45-58` |

Процессоры с фиксированным SQL не требуют этого guard'а: они не дают
caller'у задать произвольное выражение. При нарушении guard процессор
вызывает `exchange.fail(...)` и выходит **до** открытия сессии или
выполнения запроса.

### 3. `infra_db_query` — feature-flag, default OFF

Добавлен `feature_flags.infra_db_query_enabled` с `default=False`
(`src/backend/core/config/features/dsl.py:180-194`). Flag зарегистрирован
в `tools/checks/feature_flag_registry.toml:61`.

Если flag выключен или не может быть прочитан, процессор fail-closed:
логирует ошибку, помечает exchange как failed и не выполняет ни одного
SQL-вызова
(`src/backend/dsl/engine/processors/infra_db.py:92-107`,
`src/backend/dsl/engine/processors/infra_db.py:125-135`). Это тот же
fail-closed принцип, что применён к RCE-классу `script_runner`
(`src/backend/dsl/engine/processors/script_runner.py:1-22`).

### 4. Рабочее исполнение внутреннего SQL

При включённом flag и успешной валидации `infra_db_query`:

- получает internal session manager через DI;
- открывает сессию через `create_session()`;
- выполняет `session.execute(text(sql), params)`;
- для `SELECT` возвращает `list[dict]`, для DML коммитит и возвращает
  `rowcount`.

Реализация: `src/backend/dsl/engine/processors/infra_db.py:143-157`.
Параметры значений передаются bind-параметрами, а не конкатенацией.

### 5. Capability-барьер отложен

`required_capability` намеренно не добавлен: текущий runtime
authorization-путь deny-all, поэтому такое требование сделало бы шаг
недоступным для всех. Это явно зафиксировано в
`src/backend/dsl/engine/processors/infra_db.py:29-34` и
`src/backend/dsl/engine/processors/db_query_external.py:108-115`.
Capability-решение вынесено в [ADR-0361](0361-capability-enforcement-required-capability-semantics.md).

## Известные ограничения guard'а

Текущий guard проверяет только первое слово
(`src/backend/dsl/engine/processors/_sql_validation.py:43-48`). Поэтому
он не ловит:

- запрещённую команду с предшествующим комментарием, например
  `/*x*/DROP TABLE users`;
- вложенную запись в CTE, например
  `WITH x AS (DELETE FROM users RETURNING *) SELECT * FROM x`.

Это осознанный потолок текущего решения. Ближайший апгрейд — SQL
parse-уровень или read-only роль БД.

Для DuckDB guard также не ограничивает файловые операции
`read_csv`, `COPY TO` и `ATTACH`; риск явно отмечен в
`src/backend/dsl/engine/processors/duckdb_query.py:17-22`.

### Расширение guard'а (гриллинг раунд 2, Q8) — файловые команды и функции

**Согласовано владельцем.** `FORBIDDEN_SQL` дополнена командами
`ATTACH`, `DETACH`, `COPY`, `INSTALL`, `LOAD`, `EXPORT`, `IMPORT` — они дают
доступ к файловой системе (PostgreSQL: `COPY ... FROM '/etc/passwd'`;
DuckDB: `ATTACH`/`COPY TO`) либо тянут удалённые модули.

Дополнительно запрещены **файловые функции** (отдельный публичный набор
`FORBIDDEN_FUNCTIONS`): `read_csv`, `read_csv_auto`, `read_parquet`,
`read_json`, `read_json_auto`, `glob`.

Поиск запрещённых слов идёт **по всему SQL**, а не только по первому слову:
перед сканированием вырезаются строковые литералы (`'…'`, `"…"`, `` `…` ``,
`$tag$…$tag$`, `$$…$$`) и комментарии (`--…`, `/*…*/`), поэтому значение
`'copy'` в условии не считается командой. Ошибки сохраняют прежние тексты
(`SQL command 'DROP' is not allowed`, `Multi-statement SQL is not allowed`),
для функций — новая формулировка `SQL function 'read_csv' is not allowed`.

**Остаточный предел** (тот же класс, что и раньше): вложенные CTE
(`WITH x AS (DELETE …)`) и команды в комментариях не ловятся; неявное чтение
файла в DuckDB через `FROM 'data.csv'` (без функции) — тоже; динамические имена
функций не разбираются. Апгрейд — SQL parse-уровень или read-only роль БД.

## Альтернативы

### Вариант A: оставить локальные копии `_validate_sql` (отклонён)

**Почему отклонён:** копии расходились по набору правил и не
покрывали `db_query_external`, `duckdb_query` и `infra_clickhouse`.
Единый helper убирает дрейф и делает guard одинаковым для всех
SQL-процессоров.

### Вариант B: сразу включить `infra_db_query` (отклонён)

**Почему отклонён:** произвольный SQL к внутренней БД имеет тот же
класс риска, что и произвольное выполнение кода. Default-OFF и
fail-closed дают явный операционный переключатель вместо неявного
включения опасной возможности.

### Вариант C: добавить `required_capability` только к `infra_db_query` (отклонён сейчас)

**Почему отклонён сейчас:** capability-путь сейчас deny-all; такой
барьер сделал бы шаг полностью недоступным и не проверил бы SQL-семантику.
Решение о capability вынесено в [ADR-0361](0361-capability-enforcement-required-capability-semantics.md).

### Вариант D: сразу использовать полноценный SQL parser (отклонён для Cycle 172)

**Почему отклонён:** parser-уровень требует поддержки нескольких
диалектов и заметно расширяет scope. Минимальный общий guard закрывает
известные DDL/privilege/multi-statement случаи, а его предел явно
документирован.

## Последствия

### Позитивные

- `infra_db_query` выключен по умолчанию и гарантированно не ходит в БД
  при OFF.
- Внутренний SQL теперь действительно исполняется через поддерживаемый
  API session manager и SQLAlchemy `text()`.
- Multi-statement и DDL/privilege-команды отклоняются единообразно и
  до похода в БД.
- Guard и bind-параметры не зависят от capability-пути.

### Негативные и ограничения

- Guard остаётся лексическим, а не синтаксическим.
- DuckDB-путь сохраняет доступ к файловой системе.
- Capability-барьера у SQL-процессоров пока нет; это отдельное
  незакрытое решение [ADR-0361](0361-capability-enforcement-required-capability-semantics.md).
- Включение `infra_db_query` требует явного runtime-решения оператора.

## Проверка после реализации

```bash
.venv/bin/python -m pytest \
  tests/unit/dsl/engine/processors/test_infra_db_query.py \
  tests/unit/dsl/test_db_query_external.py \
  tests/unit/dsl/test_duckdb_query_smoke.py \
  tests/unit/dsl/engine/processors/test_jdbc_query.py -q
```

## Связи с другими ADR

- [ADR-0112](0112-security-audit-status.md) — allowlist + escape как
  defence-in-depth для SQL.
- [ADR-0109a](0109a-script-runner-dsl.md) — precedent fail-closed для
  DSL-шага с RCE-классом риска.
- [ADR-0361](0361-capability-enforcement-required-capability-semantics.md) — capability-барьер для SQL-процессоров.
