# ADR-0383 — Tenant-изоляция raw SQL, санитизация PII в ошибках БД и breaker

* Статус: Accepted (2026-10-29, wave 16, кластер X4 — «TENANT-ИЗОЛЯЦИЯ, PII В ОШИБКАХ, BREAKER»)
* Cycle: 176
* Дата: 2026-10-29
- **Затрагивает**:
  - `src/backend/core/tenancy/sqlalchemy_filter.py`
  - `src/backend/infrastructure/database/session_manager.py`
  - `src/backend/infrastructure/database/listeners.py`
  - `src/backend/infrastructure/database/query_result_cache.py`
  - `src/backend/core/resilience/breaker.py` (единственная правка вне двух
    «моих» каталогов — см. «Вне зоны»)
  - `tests/unit/core/tenancy/{test_tenant_filter_raw_sql,test_tenant_filter_orm_dml,test_tenant_filter_union_cte_d4}.py`
  - `tests/unit/infrastructure/database/{test_db_error_sanitization,test_session_manager_breaker,test_query_result_cache_tenant,test_tenant_filter}.py`
- **Связан с**:
  - ADR-0347 (tenant-изоляция на границе — auto-surface)
  - ADR-0305 (консолидация circuit breaker на purgatory)
  - ADR-0378 (secret masking)
- **Вне зоны (нужны чужие файлы)**:
  - `src/backend/infrastructure/database/database/initializer.py` (кластер X2) —
    `initialize_async_pool` ловит только `OSError`/`TimeoutError`, из-за чего
    SQLAlchemy `OperationalError` (например, отказ старта Postgres при
    `CREATE EXTENSION`) проходит мимо и не даёт корректного сообщения.
    Минимальный фикс — добавить `OperationalError`/`SQLAlchemyError` в
    перехватываемые исключения (дефект 5).

## Контекст

Независимый свип БД (волна 16) нашёл в кластере X4 четыре дефекта:

1. **[high] Raw SQL обходил tenant-изоляцию.** ORM-фильтр живёт в
   `do_orm_execute` и применяется к `is_select/is_update/is_delete`.
   Для `TextClause` SQLAlchemy выставляет **все три флага в `False`**
   (проверено на SQLAlchemy 2.0.52), поэтому `text("SELECT … FROM docs")`
   проходил без фильтра: `select(Doc)` → 1 строка tenant-a, `text(...)` →
   строки tenant-a **и** tenant-b.
2. **[high] PII в ошибках БД наружу.** Текст SQLAlchemy-исключения содержит
   блок `[parameters: ('ivan@example.com',)]`. Он уезжал в `exchange.error`
   (через `DatabaseError`) и в лог (`exc_info=True`).
3. **[high] Breaker открывался на бизнес-ошибках.** `NotFoundError`
   проходил через `self._breaker.guard()`; 10 «не найдено» подряд открывали
   breaker `db:<name>` на 30 с и глушили весь DB-трафик (`OpenedState`).
4. **[medium] `QueryResultCache` не включал `tenant_id` в ключ** — на
   shared-бэкенде (Redis/KeyDB) кросс-тенантный кэш.

## Решение

### 1. Raw SQL — fail-closed (выбран безопасный вариант)

Выбран **второй** вариант из двух предложенных аудитом: raw-запрос без
явного tenant-идентификатора **запрещается** с понятной ошибкой
(`TenantIsolationError`, HTTP 403).

Обоснование: автоматически дописать предикат к произвольному SQL
небезопасно — запрос может содержать CTE, `UNION`, подзапросы, `GROUP BY`/
`HAVING`/`ORDER BY`/`LIMIT`, и текстовая переписка без полноценного
SQL-парсера либо сломает запрос, либо добавит предикат не туда (например,
в подзапрос вместо внешнего). Молча пропустить чужого tenant'а нельзя —
значит, при невозможности доказать безопасность запрос отклоняется.

Механика (`core/tenancy/sqlalchemy_filter.py`):

* guard живёт в том же session-level событии `do_orm_execute` (оно
  срабатывает и на `TextClause`, в отличие от `before_cursor_execute`,
  где bind-параметры уже рендерятся в позиционные `?` и имя параметра
  теряется);
* «tenant-aware таблица» — таблица класса с `tenant_id`: подклассы
  `TenantMixin` (реестр через `__init_subclass__`) + любой mapped-класс с
  атрибутом `tenant_id` (событие `mapper_configured`, тот же критерий, что у
  `_is_tenant_aware`). Таблицы без `tenant_id` (внешние БД, служебные,
  `immutable_audit`) guard не затрагивает — ломать легитимные запросы
  нельзя;
* запрос разрешён, только если в нём есть явный предикат
  `tenant_id = :param` (значение параметра == tenant текущего контекста)
  либо `tenant_id = 'tenant'` (литерал == tenant текущего контекста);
  иначе — `TenantIsolationError` с инструкцией, что добавить;
* без tenant в контексте поведение прежнее (фильтр не применяется).

### 2. PII в ошибках БД — маскирование в точке формирования

* `listeners.sanitize_db_error_text()` вырезает блок `[parameters: …]`
  (скобки/кавычки разбираются посимвольно) → `[parameters: ***]`; текст
  SQL и диагностика драйвера сохраняются.
* `listeners.sanitized_exc_info()` собирает `exc_info` с очищенным текстом
  (traceback сохраняется) — вместо `exc_info=True`/`exc_info=original`.
* `session_manager` sanit'ит и сообщение `DatabaseError` (уходит в
  `exchange.error`), и запись в лог — на всех трёх путях
  (`create_session`, `transaction`, `connection`).
* `IntegrityError` пробрасывается как `IntegrityError` с
  `hide_parameters=True` (канонический механизм SQLAlchemy): текст без
  значений параметров, тип сохранён.

### 3. Breaker не считает бизнес-ошибки отказами

`BreakerSpec(excluded_exceptions=(NotFoundError, IntegrityError))` в
`session_manager`. Поле `excluded_exceptions` существовало, но
`core/resilience/breaker.py` его **не передавал** в purgatory — фикс из
аудита был бы no-op. Поэтому в `Breaker.guard()` добавлена одна строка
`exclude=list(self._spec.excluded_exceptions)`: purgatory при такой ошибке
не инкрементит failure-counter (семантика совпадает с
`SlidingWindowBreaker`). Настоящие отказы (`OperationalError` и прочие)
breaker по-прежнему открывают. `NotFoundError` дополнительно не
маскируется под `DatabaseError` в `create_session()`.

### 4. `QueryResultCache`: `tenant_id` в ключе

Ключ стал `qrc:<profile>:<tenant_id>:<digest>`, digest считается по
`profile:tenant_id:sql:param_hash`. Без tenant в контексте —
`qrc:<profile>:-:<digest>`.

## Альтернативы (отклонённые)

1. **Автоподстановка tenant-предиката в raw SQL.** Отклонено: без
   полноценного SQL-парсера переписка CTE/UNION/подзапросов либо ломает
   запрос, либо фильтрует не ту таблицу; цена ошибки — утечка чужих строк.
2. **`before_cursor_execute` вместо `do_orm_execute`.** Отклонено: на
   уровне cursor'а bind-параметры уже рендерятся в позиционные `?` — имя
   параметра (`tenant_id`) и его значение теряются, проверка «tenant в
   параметрах» становится эвристикой по значениям.
3. **Блокировать весь raw SQL при активном tenant'е.** Отклонено: ломает
   легитимные запросы (внешние БД, `SELECT 1`, advisory-локи, проверка
   цепочки audit-hash), которые к tenant-таблицам не относятся.
4. **Исключить `DatabaseError` из breaker'а.** Отклонено: `DatabaseError` —
   обёртка настоящих отказов БД; исключив её, breaker перестал бы
   срабатывать вовсе.
5. **Маскировать PII в `core/errors.py`/логгере глобально.** Отклонено:
   правка вне зоны; кроме того, причина утечки — формирование ошибки в
   DB-слое, где идёт работа с текстом исключения.

## Последствия

* **Позитивные:** raw SQL больше не отдаёт строки чужого tenant'а;
  `exchange.error` и логи БД не содержат значений bind-параметров;
  «ресурс не найден» и «дубликат ключа» не глушат DB-трафик;
  кэш результатов не смешивает tenant'ов.
* **Негативные / breaking:** raw SQL по tenant-aware таблице обязан
  содержать `tenant_id`-предикат — часть существующих запросов потребует
  правки (в репозитории таких запросов нет; изменены только
  инспекционные запросы в тестах, переведённые на `Connection`);
  `IntegrityError` из `connection()` теперь пробрасывается как
  `IntegrityError` (а не `DatabaseError`) — с сохранённым текстом драйвера
  и без значений параметров.
* **Остаточный риск:** guard действует на уровне `Session`;
  `Connection.execute(text(...))` в обход сессии (привилегированный путь:
  миграции, инспекция БД) не перехватывается — это зафиксировано как
  follow-up (engine-level guard с привязкой к конкретному engine).

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/core/tenancy tests/unit/infrastructure/database -q -p no:randomly
.venv/bin/python -m ruff check src/backend/core/tenancy/sqlalchemy_filter.py \
    src/backend/core/resilience/breaker.py \
    src/backend/infrastructure/database/listeners.py \
    src/backend/infrastructure/database/session_manager.py \
    src/backend/infrastructure/database/query_result_cache.py
.venv/bin/python tools/config_audit.py --scope orphans
.venv/bin/python tools/check_layers.py --strict
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
```

## Связи с другими ADR

* **ADR-0347** — tenant-изоляция на границе: этот ADR закрывает
  escape-hatch (`text(...)`), который обходил auto-surface ORM-фильтра.
* **ADR-0305** — консолидация breaker на purgatory: исключения из
  счётчика отказов теперь действительно применяются (раньше поле
  `excluded_exceptions` было декларацией без эффекта).
* **ADR-0378** — secret masking: санитизация PII в ошибках БД дополняет
  маскирование секретов в логах.
