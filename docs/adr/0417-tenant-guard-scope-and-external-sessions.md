# ADR-0417 — Границы tenant-guard'а: main-контур, внешние БД и fail-closed

* Статус: Accepted (2026-11-02)
* Автор: wave-24, кластер F2
* Затрагивает: `src/backend/core/tenancy/sqlalchemy_filter.py`,
  `src/backend/core/tenancy/tenant_tables.py`,
  `src/backend/infrastructure/database/session_manager.py`,
  `src/backend/infrastructure/database/migrations/versions/2026_10_29_1200-e2f3a4b5c6d7_rls_all_tenant_tables.py`,
  `tests/unit/core/tenancy/test_tenant_guard_adr0417.py`,
  `tests/unit/core/tenancy/test_tenant_filter_raw_sql.py`

## Контекст

Мультироевой аудит (волна 24, кластер F2 «TENANT-изоляция: границы
main/ВНЕШНИХ БД») нашёл три дефекта в
`src/backend/core/tenancy/sqlalchemy_filter.py` — модуле, который держит
tenant-изоляцию на уровне приложения (ORM-фильтр + raw-SQL guard + RLS-скоуп).

**(1) [high] Guard применялся к внешним БД.** Listener стоит на глобальном
классе `Session` (`do_orm_execute`), поэтому он фильтровал raw SQL **всех**
сессий, включая внешние профили. Проба: внешняя сессия к таблице
`workflow_instances` при `bind_tenant("t-1")` → `TenantIsolationError … без
явного tenant_id-предиката`. Ломались `db_query_external`, `jdbc_query` и
`batch_*` — любой внешний запрос к таблице, чьё имя совпадает с
tenant-таблицей приложения. Причина: tenant-изоляция — свойство **main**-контура
(его схема, его RLS-политики), а не универсальное правило для всех СУБД.

**(2) [high] Guard пропускался без tenant-контекста.** В raw-SQL ветке стояло
`if tenant_id: _guard_raw_sql(...)`, иначе — `return`. Проба: `raw text() no
tenant ctx` → `OK rows=[(1,'tenant_a','a'), (2,'tenant_b','b')]` — кросс-tenant
чтение: без tenant'а «текущий tenant» неизвестен, а значит выборка ничем не
ограничена. DSL-путь (`dsl/engine/processors/components/databasequeryprocessor.py`)
уже был fail-closed — расходились два пути.

**(3) [medium] Extension-таблицы не попадали в `tenant_aware_tables()`.**
Таблицы `orders` / `users` / `files` / `orderkinds` имеют RLS (миграция
`2026_10_29_1200-e2f3a4b5c6d7`), но ORM-моделей в ядре у них нет: модели
живут в `extensions/core_entities/*` и грузятся **лениво** (plugin-loader), а
динамическое обнаружение (`Table.after_parent_attach` + metadata) их не видит.
Проба: список = `['dsl_snapshots', 'rule_engine_rulesets',
'scheduler_run_history', 'workflow_events', 'workflow_instances']` — raw-SQL
guard эти четыре таблицы не покрывал; единственная защита — RLS, то есть
только на PostgreSQL.

## Решение

1. **Guard — только для main-контура (ADR-0417 §1).** В `core/tenancy`
   появился реестр внешних движков и две функции:
   `register_external_engine(engine)` (объявить движок внешним) и
   `is_main_scope(session)` (сессия относится к main-контуру?). Идентификация
   идёт по `session.get_bind()` — для `AsyncEngine` это его `sync_engine`,
   поэтому один и тот же движок узнаётся и по `Engine`, и по
   `AsyncEngine`/`sessionmaker`. Listener'ы (`do_orm_execute`, `before_flush`,
   `after_begin`) **пропускают** внешние сессии: ORM-фильтр, raw-SQL guard и
   RLS-скоуп к ним не применяются.
   * Дефолт — **fail-closed**: неизвестный движок считается main'ом
     (изоляция важнее доступности). Поэтому внешний контур обязан быть
     объявлен явно.
   * Production-wiring: `DatabaseSessionManager.__init__` объявляет движок
     внешним для любого профиля, кроме `main`
     (`src/backend/infrastructure/database/session_manager.py`) — это единственная
     точка создания внешних сессий (`db_query_external`, `jdbc_query`,
     `batch_*`, external-database facade).

2. **Raw-SQL guard — всегда fail-closed (ADR-0417 §2).** Ветка `TextClause`
   больше не проверяет `tenant_id` перед вызовом guard'а: `guard_raw_sql`
   вызывается всегда, и без tenant-контекста запрос к tenant-aware таблице
   отклоняется с `TenantIsolationError` («tenant-контекст не привязан»).
   Поведение выровнено с DSL-путём (`databasequeryprocessor`). Контракт
   прежнего теста `test_raw_sql_without_tenant_context_is_allowed` изменён
   осознанно → переименован в `…_is_blocked`.

3. **Единый канонический список tenant-таблиц (ADR-0417 §3).** Новый модуль
   `src/backend/core/tenancy/tenant_tables.py` содержит единственный список
   имён `TENANT_TABLES` (9 таблиц: `dsl_snapshots`, `files`, `orderkinds`,
   `orders`, `rule_engine_rulesets`, `users`, `workflow_events`,
   `workflow_instances`, `workflow_state`). `tenant_aware_tables()` объединяет
   его с динамическим обнаружением. Список имён **не дублируется**: миграция
   RLS (`2026_10_29_1200-…`) импортирует его и строит `RLS_TABLES` из него —
   поэтому scope guard'а и scope RLS не могут разойтись. Источник имён —
   миграции (список tenant_id-таблиц выводится из их AST в
   `tests/unit/infrastructure/database/test_rls_all_tenant_tables.py` и
   сверяется с каноническим списком новым тестом).

## Альтернативы

| Вариант | Вердикт | Почему |
|---|---|---|
| **A.** Оставить guard глобальным, а внешние таблицы исключать по имени | отклонён | Имя таблицы не определяет контур: у внешней БД таблица `workflow_instances` — не tenant-сущность приложения. Список имён рос бы бесконечно и не решает проблему внешних схем |
| **B.** Сравнивать `session.get_bind()` с DSN main-БД из settings | отклонён | Хрупко: реплика (`replica_dsn`) — другой DSN, тестовые движки — третий; сравнение строк DSN ломается на эквивалентных формах записи. Явная регистрация движка — надёжнее и проверяема тестом |
| **C.** Считать неизвестный движок внешним (fail-open) | отклонён | Любая сессия main-БД, созданная мимо `DatabaseSessionManager` (replica, прямой `sessionmaker`), потеряла бы tenant-изоляцию → кросс-tenant чтение. Изоляция важнее доступности |
| **D.** Перенести listener с класса `Session` на конкретный sessionmaker | отклонён | Часть main-сессий создаётся вне `DatabaseSessionManager` (`accessors.get_db_session()`, `SmartSessionManager` — реплика): guard перестал бы их покрывать. Оставлен глобальный listener + отсечение по движку |
| **E.** Дублировать список tenant-таблиц в filter'е и в миграции | отклонён | Расхождение = таблица, не защищённая ни приложением, ни БД. Канонический список один (core), миграция его импортирует |
| **F.** Завести ORM-модели для `orders`/`users`/`files`/`orderkinds` в ядре | отклонён | Модели принадлежат расширениям (`extensions/core_entities/*`); перенос в ядро ломает ownership и границы плагинов. Явный список решает задачу без перемещения кода |

## Последствия

### Позитивные

* Внешний контур работает: `db_query_external`, `jdbc_query`, `batch_*` больше
  не отклоняются по названию таблицы (`TenantIsolationError` на
  `workflow_instances` ушёл).
* Кросс-tenant чтение через raw SQL без tenant-контекста закрыто: запрос
  отклоняется с понятным сообщением, а не возвращает строки чужих tenant'ов.
* `orders` / `users` / `files` / `orderkinds` покрыты guard'ом и на БД без
  RLS (SQLite, MySQL) — защита перестала зависеть от PostgreSQL.
* Scope guard'а и scope RLS связаны одним списком — новая tenant-таблица
  не может «потеряться» в одном из двух контуров.

### Отрицательные / ограничения

* Появился явный API регистрации движка (`register_external_engine`): новый
  внешний контур обязан объявить себя, иначе его сессии попадут под guard
  (fail-closed) и внешние запросы начнут отклоняться. Wiring сделан в
  `DatabaseSessionManager` — единой точке создания внешних сессий.
* Fail-closed без tenant-контекста — это изменение публичного контракта:
  код, который раньше полагался на «guard без tenant'а = no-op», теперь
  получает `TenantIsolationError`. Для внутренних raw-запросов к
  tenant-aware таблицам нужен явный tenant-предикат (в internal-контуре
  таких мест нет — RLS-таблицы пишутся через ORM).
* `TENANT_TABLES` — ручной список: новая tenant-таблица требует правки
  канона (для неё включается RLS миграцией — она импортирует канон).

### Открытая дыра D-4 (owner-задача, вне этого ADR)

**D-4 (CRITICAL): UNION/CTE обходят ORM tenant-фильтр.** Подтверждено на
реальном SQLAlchemy 2.0 + SQLite: под `tenant-a` `union_all` возвращает строки
`tenant-b`. Причина: `_tenant_aware_entities` опирается на
`statement.column_descriptions` / `entity_description` / `stmt.froms`, а у
составных запросов (`CompoundSelect`, CTE) эти атрибуты относятся к ветвям,
а не к результату, поэтому `stmt.where(entity.tenant_id == …)` не добавляется.
Попытка починки через `replacement_traverse` отклонена: обход не заходит в
ветви, а пересборка `CompoundSelect` требует приватного API SQLAlchemy.
Зафиксировано как strict-xfail в
`tests/unit/core/tenancy/test_tenant_filter_union_cte_d4.py` (4 кейса: UNION
одной сущности, UNION разных сущностей, CTE, CTE+UNION) — «молчаливое прошло»
не считается доказательством защиты.

Критерии приёмки (owner-задача, отдельный ADR):

1. Под `tenant-a` `select(A).union_all(select(A))`, `select(A).union_all(select(B))`,
   CTE и CTE+UNION возвращают **только** строки `tenant-a` — на реальном
   SQLAlchemy 2.0 (не на моках), с проверкой против сырого чтения в обход ORM.
2. DML-аналоги (`update`/`delete` с CTE) также ограничены tenant'ом.
3. Все 4 strict-xfail'а в `test_tenant_filter_union_cte_d4.py` переходят в
   XPASS (при `strict=True` это автоматически валит прогон) — маркеры `xfail`
   удаляются.
4. Регрессии не сломаны: `tests/unit/core/tenancy/**` и
   `tests/unit/infrastructure/database/**` — зелёные.
5. Решение не опирается на приватный API SQLAlchemy
   (`_CompoundSelectState` / `Select.froms`); если без приватного API нельзя —
   требуется явная альтернатива (например, guard на уровне `before_compile` с
   разбором AST запроса или запрет составных запросов к tenant-aware таблицам
   через capability-гейт).

## Проверка

```bash
# Кластер F2: guard, external-сессии, канонический список tenant-таблиц
uv run pytest tests/unit/core/tenancy -q
# 137 passed, 4 xfailed (D-4 strict-xfail — см. «Открытая дыра D-4»)

# Регрессии tenant-фильтра и RLS-миграции
uv run pytest tests/unit/infrastructure/database/test_tenant_filter.py \
    tests/unit/infrastructure/database/test_rls_all_tenant_tables.py -q
# 20 passed

# Прочие гейты репозитория
uv run ruff check src/backend/core/tenancy src/backend/infrastructure/database/session_manager.py \
    src/backend/infrastructure/database/migrations/versions/2026_10_29_1200-e2f3a4b5c6d7_rls_all_tenant_tables.py \
    tests/unit/core/tenancy
uv run ruff format --check <те же файлы>
uv run python tools/check_docstrings.py               # 0 missing (2573 файла)
uv run python tools/config_audit.py --scope orphans  # 0
uv run python tools/check_layers.py --strict          # 41 (baseline, новых нет)
uv run python tools/checks/mypy_budget.py             # OK (8 при бюджете 30)
```

Фактическое состояние на момент принятия ADR: `tests/unit/core/tenancy` —
137 passed / 4 xfailed; гейты ruff, config_audit (0), check_layers (41),
mypy_budget (OK), check_docstrings (0) — зелёные.

## Связи

* **ADR-0383** — fail-closed guard для raw SQL (fail-closed этот ADR
  распространяет на случай отсутствия tenant-контекста).
* **ADR-0386** — RLS-скоуп `app.tenant_id` (RLS — defense-in-depth к
  ORM-фильтру; `after_begin` не выставляет scope для внешнего контура).
* **ADR-0393** — tenant-таблицы по metadata, расширенный канон разбора raw
  SQL, RLS-скоуп из flush'а (база для §1–§3 этого ADR).
* **ADR-0347** — tenant-isolation boundary auto-surface.
* **Миграция `2026_10_29_1200-e2f3a4b5c6d7`** — RLS на всех tenant-таблицах;
  после этого ADR берёт список имён из `core/tenancy/tenant_tables.py`.
* **`docs/roadmap/PROD_READINESS_GAPS.md`** — открытые позиции prod-readiness
  (D-4 фиксируется как owner-задача).
