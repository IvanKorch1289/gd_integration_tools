# ADR-0382 — Потеря данных и диалекты в DSL-БД

* Статус: Accepted (2026-10-29, wave 16, кластер X3 — «ПОТЕРЯ ДАННЫХ И ДИАЛЕКТЫ В DSL-БД»)
* Cycle: 176
* Дата: 2026-10-29
- **Затрагивает**:
  - `src/backend/dsl/engine/processors/_sql_validation.py` (общие хелперы SQL)
  - `src/backend/dsl/engine/processors/db_query_external.py`
  - `src/backend/dsl/engine/processors/db_crud.py`
  - `src/backend/dsl/engine/processors/batch.py`
  - `src/backend/dsl/engine/processors/components/databasequeryprocessor.py`
  - `src/backend/dsl/engine/processors/infra_db.py`
  - `src/backend/dsl/engine/processors/jdbc_query.py`
  - `src/backend/dsl/builders/transport/persistence.py`
  - `tests/unit/dsl/engine/processors/test_db_dialect_correctness.py` (новый)
  - `tests/unit/dsl/engine/processors/{test_db_crud,test_batch,test_jdbc_query,test_infra_db_query}.py`
- **Связан с**:
  - ADR-0365 (канон валидации SQL-идентификаторов)
  - ADR-0112 (allowlist-идентификаторы, bind-параметры)
  - ADR-0359 (канонический SQL-guard)
  - ADR-0380 / ADR-0381 (соседние волны по DB-DSL)
- **Вне зоны (нужны чужие файлы)**:
  - `src/backend/dsl/builders/base/_protocols/_data.py` (владеет X1) —
    Protocol-контракт `_RouteDbProtocol` ещё объявляет
    `db_query_external(commit: bool = False)`, `execute_dml(dialect: str =
    "postgresql")` и `db_upsert(...)` без `dialect`. Реализация совместима
    (bool ⊂ bool | None, опциональный kwarg), mypy проходит — но дефолты и
    сигнатуру Protocol стоит синхронизировать с mixin.

## Контекст

Аудит БД (волна 16) нашёл в DSL-БД кластер из десяти дефектов — от тихой
потери данных до SQL, который физически не может выполниться на целевой СУБД:

1. **[critical] `db_query_external` молча откатывал DML.** `commit=False` по
   умолчанию, а `create_session()` коммита не делает (сессия закрывается →
   транзакция откатывается). Проба: `INSERT ... RETURNING id` вернул
   `[{id: 1}]`, в таблице — 0 строк. Ответ «успешный», данных нет.
2. **[high] DML без `RETURNING` падал.** `_materialize_result` дёргал
   `mappings().all()` у result'а без строк → `ResourceClosedError` → до
   `commit()` не доходило.
3. **[high] `batch_insert` терял данные.** Колонки брались только из 1-го
   item'а: лишние ключи остальных молча игнорировались (проба: `b=None`).
4. **[high] `batch_delete` — Postgres-only.** `= ANY(:ids)` на sqlite даёт
   `no such function: ANY`, хотя комментарий обещал fallback `IN`.
5. **[high] `dialect` отвязан от целевой БД.** `DbCrudProcessor` всегда идёт
   в main-БД, а аргумент `dialect` менял только текст SQL:
   `execute_dml(dialect="mysql")` против PostgreSQL-main = ошибка в рантайме.
6. **[high] Oracle/MSSQL UPSERT сломан.** `MERGE INTO "t" AS t` (Oracle не
   допускает `AS` у алиаса) + `USING (SELECT :c AS "c")` без `FROM DUAL`
   (ORA-00933); MSSQL требует `;` в конце `MERGE`.
7. **[high] MySQL: двойные кавычки в идентификаторах.** Без `ANSI_QUOTES`
   `"orders"` → 1064 на всех `db_insert/update/delete/upsert`.
8. **[high] SELECT-детект по префиксу.** `WITH ... SELECT` считался DML →
   `{"rowcount": -1}`, строки терялись (`databasequeryprocessor.py:89`,
   `infra_db.py:152`, `jdbc_query.py:127`).
9. **[medium] `db_upsert` из YAML всегда postgresql** — параметра `dialect`
   у метода не было.
10. **[low] Дубли `_IDENT_RE`** в `db_crud.py` / `batch.py` вместо канона
    `core/utils/sql_identifiers.py` (ADR-0365).

## Решение

### 1–2. Фиксация транзакции (`db_query_external`)

`commit` теперь `bool | None`: `None` (default) — auto (DML коммитится, чтение
— нет), `True`/`False` — явный opt-in/opt-out. Решение «нужен ли commit»
принимается по **фактическому типу результата** (`result.returns_rows`), а не
по префиксу SQL: `INSERT ... RETURNING` возвращает строки, но остаётся DML.

Порядок выполнения: `execute` → определение типа результата → `commit` →
материализация. Ветка без строк больше не трогает курсор (`mappings()` у
result'а без строк бросает `ResourceClosedError`) и отдаёт
`{"rowcount": <int>}`.

### 3. `batch_insert`: union колонок

Колонки — union по всем item'ам (порядок первого появления); каждый item
приводится к общему набору колонок, отсутствующие значения → `NULL`.
executemany получает одинаковый набор параметров → лишние ключи больше не
теряются.

### 4. `batch_delete`: переносимый `IN`

`= ANY(:ids)` заменён на expanding bindparam
(`bindparam("ids", expanding=True)`) → `IN (:id_1, :id_2, ...)` для всех
диалектов.

### 5. Диалект — свойство целевой БД

`DbCrudProcessor.dialect` по умолчанию `None` → диалект берётся из
**фактической целевой БД** (сначала `engine.dialect.name` main-ДБ, затем
`settings.database.type`). Явно заданный диалект проверяется на
соответствие целевой БД: расхождение → `ValueError` (fail-closed) вместо
SQL чужой СУБД. Целевая БД вне `SUPPORTED_DIALECTS` (db2/clickhouse) —
тоже fail-closed с понятным сообщением.

### 6–7. Диалектные quoting и MERGE

Идентификаторы quoting-ятся по правилам диалекта через
`sqlalchemy.dialects` (`identifier_preparer.quote_identifier`):
PostgreSQL/SQLite/Oracle — `"name"`, MySQL — `` `name` ``, MSSQL — `[name]`.
MERGE стал диалектным: Oracle — `MERGE INTO "t" t USING (SELECT ... FROM
DUAL) src` (без `AS` у алиаса), MSSQL — `MERGE INTO [t] AS t USING (...) AS
src ...;` (с завершающей `;`).

### 8. SELECT-детект по типу результата

`databasequeryprocessor`, `infra_db`, `jdbc_query` (и `db_query_external`)
различают чтение и DML по `result.returns_rows`; если атрибута нет
(заглушка/не-SQLAlchemy result) — fallback на классификацию SQL
(`sql_statement_kind`). Общая логика вынесена в
`_sql_validation.sql_statement_kind` / `needs_commit` /
`result_returns_rows` — одна реализация вместо копий в четырёх файлах.

### 9. `db_upsert`/`execute_dml` — параметр `dialect`

`PersistenceMixin.db_upsert(..., dialect=None)` и
`execute_dml(..., dialect=None)`; YAML-шаг может задать диалект явно.

### 10. Канон идентификаторов

`db_crud.py` и `batch.py` используют
`core.utils.sql_identifiers.validate_identifier`; локальные `_IDENT_RE` /
`_TABLE_NAME_RE` удалены. Тексты исключений сохранены («Invalid SQL
identifier» / «Invalid identifier» / «Invalid table name») — на них завязаны
существующие тесты (ADR-0365, п. 2).

### Побочно: наблюдаемость пропусков в `batch_update`

Item'ы без key-поля (или без update-колонок) `batch_update` и раньше
молча пропускались. Поведение не менялось, но теперь о пропуске пишется
WARNING (`dsl.batch`) — тихая потеря данных больше не выглядит как «0
затронутых строк».

## Альтернативы (отклонённые)

1. **Оставить `commit=False` по умолчанию.** Отклонено: `create_session()`
   не коммитит — поведение по умолчанию означало бы «DML всегда теряется».
2. **Коммитить в `create_session()`.** Отклонено: изменение семантики
   инфраструктурного фасада затронуло бы всех потребителей (ADR-0284 §1.1 —
   слой нельзя менять из DSL без отдельного ADR).
3. **Материализовать результат до commit.** Отклонено: commit закрывает
   курсор — чтение строк после commit возможно только для
   заранее буферизованного result'а; commit до материализации гарантирует,
   что исключение при разборе результата не съест фиксацию данных.
4. **Оставить префиксный детект SELECT.** Отклонено: `WITH ... SELECT` и
   `INSERT ... RETURNING` ломают его в обе стороны (потеря строк / потеря DML).
5. **Ручные кавычки по ветке на диалект.** Отклонено: расхождение с
   SQLAlchemy (экранирование, reserved words); канон — диалектный
   `IdentifierPreparer`.
6. **Оставить `dialect` свободной строкой.** Отклонено: ровно это и
   породило дефект (5) — «диалект чужой СУБД» выглядел как рабочий DSL.
7. **Разрешить `dialect` для внешнего профиля.** Отклонено (в этой волне):
   `DbCrudProcessor` исполняется через `DatabaseQueryProcessor` (main-БД);
   маршрутизация на внешний профиль — отдельная задача (ADR-0383+).

## Последствия

* **Позитивные:** DML больше не теряется молча; `WITH ... SELECT` возвращает
  строки; `batch_insert` не теряет ключи; `batch_delete` работает вне
  PostgreSQL; MySQL/MSSQL/Oracle получают валидный SQL; неверный диалект
  даёт понятную ошибку вместо ошибки в СУБД.
* **Негативные / breaking:** `db_query_external.commit` по умолчанию теперь
  `True` для DML (нужен явный `commit=False` для opt-out); `db_upsert`/
  `execute_dml` без диалекта следуют за целевой БД (в dev_light — sqlite);
  явный `dialect`, не совпадающий с целевой БД, валит шаг; тексты UPSERT
  для Oracle/MSSQL изменились (диалектно-корректные).
* **Ограничение:** классификация SQL лексическая (ADR-0365/ADR-0359) —
  data-modifying CTE определяется по типу результата, а не по разбору.

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/test_db_dialect_correctness.py \
    tests/unit/dsl/engine/processors/test_db_crud.py \
    tests/unit/dsl/engine/processors/test_batch.py \
    tests/unit/dsl/engine/processors/test_jdbc_query.py \
    tests/unit/dsl/engine/processors/test_infra_db_query.py \
    tests/unit/dsl/test_db_query_external.py -q
.venv/bin/python -m pytest tests/unit/dsl -q          # 5302 passed
.venv/bin/python -m ruff check <файлы кластера>
.venv/bin/python tools/config_audit.py --scope orphans  # 0
.venv/bin/python tools/check_layers.py --strict        # 41 (baseline, без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0  # 1 pre-existing
```

## Связи с другими ADR

* ADR-0365 — канон `core/utils/sql_identifiers.py`: локальные regex'ы
  `db_crud`/`batch` заменены на обёртки над каноном с сохранением текстов
  исключений.
* ADR-0112 / ADR-0359 — allowlist-идентификаторы и bind-параметры: диалектный
  quoting не меняет модель безопасности (значения — только bind-параметры).
* ADR-0380 — соседний кластер по DB-DSL: fail-closed и allowlist-имена в
  `db_call_procedure`; здесь — та же логика для CRUD-процессоров.
