# ADR-0365 — Единый канон валидации SQL-идентификаторов

* Статус: Accepted (2026-10-28, cycle 172, владелец Mavis)
* **Cycle**: 172 (Wave 13, гриллинг раунд 2, решение Q6)
* **Связан с**:
  - ADR-0112 (allowlist-идентификаторы как эталон; глобальный `# nosec B608` отклонён)
  - ADR-0359 (канонический SQL-guard)
  - ADR-0360 (CDC-валидация идентификаторов)
  - ADR-0364 (удаление мёртвого кода)
* **Затрагивает**:
  - `src/backend/core/utils/sql_identifiers.py` (канон)
  - `src/backend/infrastructure/clients/external/cdc/_identifiers.py`
  - `src/backend/infrastructure/clients/storage/clickhouse.py`
  - `src/backend/infrastructure/clients/storage/sqlite_search.py`
  - `src/backend/infrastructure/storage/sqlite_doc_store.py`

## Контекст

После Wave 13 в проекте оказалось **четыре независимые реализации** одного и
того же правила «допустимое имя SQL-объекта»:

| Место | Было | Особенность |
|---|---|---|
| `core/utils/sql_identifiers.py` | `^[A-Za-z_][A-Za-z0-9_]*\Z` | канон (создан в Q18) |
| `infrastructure/clients/external/cdc/_identifiers.py` | свой `_IDENT_RE` + ≤3 сегмента | доменная специфика CDC |
| `infrastructure/clients/storage/clickhouse.py` | `_IDENT_RE` c `$` | допускал dotted-имена |
| `infrastructure/clients/storage/sqlite_search.py` | `_INDEX_RE` c `$` | только одиночные имена |
| `infrastructure/storage/sqlite_doc_store.py` | `_NAMESPACE_RE` c `$` | только одиночные имена |

Различия в один символ (`$` против `\Z`) означали разное поведение: `"idx\n"`
проходило старые локальные проверки (regex `$` матчит перед trailing
newline) и отклоняется каноном. Плюс правило «какое имя допустимо» было
размазано по четырём модулям — риск нового расхождения при каждой правке.

ADR-0112 называет allowlist-идентификаторы эталонным паттерном и требует
точечных `# nosec B608` с обоснованием; канонизация правила идентификаторов
прямо соответствует этому требованию.

## Решение

1. **Канон** — `src/backend/core/utils/sql_identifiers.py`:
   `validate_identifier(value, *, context)` (одиночный идентификатор) и
   `validate_path_key(value, *, context)` (JSON-путь с точками).
2. Локальные реализации заменены на **тонкие обёртки** над каноном с
   сохранением:
   - публичных API модулей;
   - наборов допустимых имён;
   - **текстов исключений** (на них завязаны существующие тесты).
3. CDC-специфика сохранена в CDC-модуле: `escape_sql_literal` (экранирование
   строковых литералов LogMiner) и `validate_subscription_identifiers`
   (пакетная проверка подписки). Собственного regex в CDC больше нет —
   `_is_cdc_identifier()` делегирует проверку каждого сегмента канону
   (≤3 сегмента: `name`, `schema.name`, `db.schema.name`).
4. `clickhouse.py`: dotted-имена проверены фактически — единственный
   production-вызов `aggregate()` идёт из `services/ops/analytics.py:35,49`,
   dotted-имён в репозитории нет → локальный `_IDENT_RE` удалён, обёртка
   `_validate_agg_identifier()` переводит ошибку в исходный текст.
5. `sqlite_search.py` и `sqlite_doc_store.py`: локальные regex'ы удалены,
   `_ensure_index()` / `_ensure_namespace()` зовут канон.

### Осознанное изменение поведения

Переход с `$` на `\Z` означает, что имена с trailing newline
(`"idx\n"`, `"ns1\n"`, `"events\n"`) теперь отклоняются. Это ровно тот разрыв,
ради которого канон создавался; закреплено новыми тестами.

## Известный долг (не входит в решение)

- `src/backend/services/io/external_database/validation_mixin.py:25` и ещё
  **6 копий** `_IDENT_RE` в том же пакете (`profile_/dispatch_/build_/core_/
  state_mixin.py`, `__init__.py`) — не сведены: пакет бросает `DatabaseError`
  (не `ValueError`), а канон — `ValueError`; канонизация потребовала бы
  изменения типа исключения, то есть API-изменения.
- `src/backend/infrastructure/database/external_database_facade.py:156` —
  `_PROC_IDENT_RE` с лимитом длины 64 (специфика PostgreSQL), канон такого
  ограничения не выражает.
- `AnalyticsService.count()` (`services/ops/analytics.py:35`) передаёт
  колонку `"*"` в `aggregate()` → не проходит allowlist (и старый regex, и
  канон) — pre-existing баг вне scope.

## Проверка

`pytest tests/unit/dsl tests/unit/core/config tests/unit/infrastructure/database`
— 5966 passed, 30 skipped, 32 xfailed, 25 xpassed;
`tools/check_layers.py --strict` — 41 (baseline);
`tools/check_docstrings.py` — 1 missing (pre-existing).

## Альтернативы (отклонённые)

- **(а) Оставить четыре реализации** — отклонено: расхождение в один символ
  уже дало разное поведение; правило обязано быть одно.
- **(б) Перенести канон в `services/io/external_database`** — отклонено:
  слой `services` недоступен из `infrastructure` без инверсии слоёв
  (ADR-0284 §1.1), а `core` — общий доступный уровень.
- **(в) Свести и `services/io/external_database`** — отложено: требует
  изменения типа исключения (API-изменение) — отдельное решение.

## Связи с другими ADR

- ADR-0112 — эталон allowlist-идентификаторов и запрет глобального
  `# nosec B608`.
- ADR-0359 — канонический SQL-guard, использующий ту же семантику имён.
- ADR-0360 — CDC-валидация (обёртка поверх канона).
