# Tenancy model

`core.tenancy.TenantContext` — frozen dataclass + ContextVar. Все
нижележащие слои (DB, Redis, logs, metrics) используют контекст для
изоляции.

## Текущее состояние (актуально на 2026-10-29)

* `TenantContext` доступен (core-контракт, `src/backend/core/tenancy/`);
* admin endpoints `/admin/tenants` и `/admin/tenants/{id}` — stub-режим;
* Streamlit page 70_Tenants рендерит scaffold UI;
* RLS включён **на 9 tenant-таблицах** (миграция
  `src/backend/infrastructure/database/migrations/versions/2026_10_29_1200-e2f3a4b5c6d7_rls_all_tenant_tables.py`,
  ADR-0386);
* ORM-фильтр и fail-closed raw-SQL guard — ADR-0383 / ADR-0386;
* per-tenant Redis namespace и SLO-метрики — см. «Quotas» и
  `src/backend/core/tenancy/`.

RLS — не план, а работающая защита: на момент cycle 172/173 (волны
16–17) RLS включён на всех tenant-таблицах, кроме намеренно
исключённых (см. ниже).

## Tenant-изоляция: три уровня

### 1. ORM-фильтр (канон)

`src/backend/core/tenancy/sqlalchemy_filter.py`:

* `TenantMixin` — mixin-модели с колонкой `tenant_id`;
* `apply_tenant_filter()` — глобальный SQLAlchemy-listener, добавляет
  tenant-предикат к запросам по tenant-aware моделям;
* tenant-скоуп выставляется в `app.tenant_id` на событии сессии
  `after_begin` — приложение обязано задавать его **до** первой
  транзакции, иначе `current_setting('app.tenant_id', true)` вернёт
  `NULL` и строгие RLS-политики не пропустят ни одной строки.

### 2. Raw-SQL guard (fail-closed)

`guard_raw_sql(...)` в том же модуле (ADR-0383): raw-запрос без явного
`tenant_id`-предиката к tenant-aware таблице **отклоняется**, а не
молча выполняется. `Connection.execute(text(...))` идёт мимо
session-level события ORM-фильтра, поэтому этот путь закрыт отдельно
(ADR-0386): привилегированный `Connection.execute` — не обход
tenant-изоляции.

DSL-процессор «сырой SQL» (`DatabaseQueryProcessor`) перед выполнением
зовёт общий `guard_raw_sql`; DSL-CRUD (`db_crud`) для tenant-aware
таблиц сам добавляет `tenant_id` в `WHERE` (UPDATE/DELETE) либо в
`data` (INSERT/UPSERT), а без tenant-контекста шаг падает fail-closed
(ADR-0393).

### 3. RLS на уровне БД (defense-in-depth)

Миграция `2026_10_29_1200` (ADR-0386) включает RLS +
`FORCE ROW LEVEL SECURITY` и политику
`tenant_id = current_setting('app.tenant_id', true)` на 9 таблицах:

| # | Таблица | Примечание |
|---|---|---|
| 1 | `workflow_instances` | Политика S21 заменена канонической. |
| 2 | `workflow_state` | Политика S21 заменена канонической. |
| 3 | `rule_engine_rulesets` | `tenant_id` nullable — глобальные строки (`tenant_id IS NULL`) видимы. |
| 4 | `orders` | extension-таблица. |
| 5 | `users` | extension-таблица. |
| 6 | `files` | extension-таблица. |
| 7 | `dsl_snapshots` | hot-reload DSL. |
| 8 | `workflow_events` | append-only event log workflow'ов. |
| 9 | `orderkinds` | extension-таблица. |

Намеренно **без** RLS (осознанные исключения из миграции):

* `audit_log_immutable` — append-only аудит пишется из системного
  контура, `tenant_id` nullable;
* `dlq_inbox` — фоновая запись DLQ вне tenant-контекста;
* `scheduler_run_history` — scheduler работает вне tenant-контекста;
* `langmem_episodic` / `langmem_procedural` — изоляция по колонке
  `tenant`, а не `tenant_id`.

Политика RLS — PostgreSQL-only; на других диалектах миграция — no-op.

## Audit

Каждый доступ к данным через БД порождает audit-событие с capability,
алиасом ресурса, action, route и tenant — **без значений данных**
(ADR-0393). Ошибки БД маскируются в точке формирования, чтобы PII не
попадала в текст исключения и в audit (ADR-0383).

## Quotas

`core.tenancy.QuotaTracker` — поверх Redis, fail-open semantic
(если Redis недоступен — quota не блокируется, событие в логи).

См. также:
* Streamlit page **70_Tenants** — admin UI;
* ADR-0383 — tenant-изоляция raw SQL и санитизация ошибок;
* ADR-0386 — tenant-guard для `Connection.execute` и RLS-покрытие;
* ADR-0393 — tenant-изоляция DSL-SQL.
