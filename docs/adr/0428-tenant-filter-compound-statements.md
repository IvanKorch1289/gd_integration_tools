# ADR-0428 — Tenant-фильтр для составных запросов: UNION/CTE (D-4, G13)

* Статус: Accepted (2026-11-03, волна 26)
* Cycle: 186 (волна 26)
* Связан с:
  - ADR-0417 (tenant-guard: только main-движок, fail-closed без tenant),
  - ADR-0403 (SLA/DLQ-политика workflow — контекст workflow-tenant'а),
  - ADR-0284 (новых межслойных нарушений не добавляем)
* Затрагивает:
  - `src/backend/core/tenancy/sqlalchemy_filter.py` (`_filter_statement` —
    новый патч-слой; `do_orm_execute` переведён на него),
  - `tests/unit/core/tenancy/test_tenant_filter_union_cte_d4.py`
    (4 strict-xfail → обычные тесты),
  - `tests/unit/core/security/test_reaudit_n1_n3_n4.py`
    (фиксация «известного пробела» N-2 → проверка закрытой дыры)

---

## Контекст

ORM-фильтр tenant'а добавляет предикат `entity.tenant_id == <tenant>` к
statement'у верхнего уровня. У **составных** конструкций сущности живут не
там:

* `CompoundSelect` (UNION / UNION ALL / INTERSECT / EXCEPT) — сущности в
  **ветвях**;
* `CTE` — определение CTE является отдельным select'ом, внешний запрос видит
  только его колонки.

В обоих случаях `_tenant_aware_entities(stmt)` возвращал `[]` → предикат не
добавлялся → **кросс-tenant чтение** (D-4, подтверждено на реальном
SQLAlchemy 2.0 + SQLite: под `tenant-a` `union_all` возвращал строки
`tenant-b`).

Ранее делались две попытки, обе отклонены:

* `replacement_traverse` без callback — обход не заходит в ветви;
* пересборка `CompoundSelect` через приватный API — нестабильно.

Причина отказа прежней попытки с `replacement_traverse` — неверная сигнатура:
функция требует **callback** (`replace`), а не словарь замен.

---

## Решение

Патч-слой `_filter_statement(stmt, tenant_id)` в
`src/backend/core/tenancy/sqlalchemy_filter.py`:

1. **CompoundSelect** → tenant-предикат добавляется в **каждую ветвь**
   (рекурсивно), ветви подменяются через
   `sqlalchemy.sql.visitors.replacement_traverse(stmt, {}, callback)` —
   публичный документированный API (`replace_selectable` deprecated с 1.4 и
   не используется). Пересборка `CompoundSelect` не требуется: подмена
   сохраняет keyword (`UNION`/`UNION ALL`/…), `ORDER BY` и `LIMIT` самого
   составного запроса.
2. **CTE** → фильтруется **определение** CTE (`cte.element`), создаётся
   новый CTE с тем же именем и подменяется в внешнем запросе (ссылки на
   колонки остаются валидными).
3. **Обычный Select / DML** — прежнее поведение без изменений.

Всё построено на публичном API SQLAlchemy 2.0; приватные атрибуты
(`_order_by_clauses`, `_limit_clause`) не используются.

Проверено на реальном SQLAlchemy **2.0.55** + SQLite (in-memory):
`tests/unit/core/tenancy/test_tenant_filter_union_cte_d4.py` — 4 кейса
(UNION одной сущности, UNION разных сущностей, CTE, CTE+UNION) переведены из
strict-xfail в обычные тесты и проходят.

---

## Последствия

* **G13 закрыт:** кросс-tenant чтение через UNION/CTE устранено на уровне
  ORM-фильтра (остаётся RLS-слой на стороне БД как второй эшелон).
* Изменение затрагивает **все** ORM-запросы: `do_orm_execute` теперь
  вызывает `_filter_statement` вместо цикла по сущностям. Для обычных
  select'ов поведение идентично (регрессия проверена прогоном
  `tests/unit/core/` + `tests/unit/infrastructure/database/` — 7783 passed).
* Ограничение: составной запрос, собранный **в обход ORM** (raw SQL через
  `text()`), по-прежнему регулируется guard'ом ADR-0383/ADR-0417
  (fail-closed без явного tenant-предиката).
