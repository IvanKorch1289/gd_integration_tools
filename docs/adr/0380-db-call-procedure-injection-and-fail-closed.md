# ADR-0380 — SQL-инъекция и fail-open в `db_call_procedure`

* Статус: Accepted (2026-10-29, wave 16, кластер X1 — «SQL-ИНЪЕКЦИЯ И FAIL-OPEN В db_call_procedure»)
* Cycle: 176
* Дата: 2026-10-29
- **Затрагивает**:
  - `src/backend/dsl/engine/processors/db_call_procedure.py`
  - `tests/unit/dsl/engine/processors/test_db_call_procedure.py`
  - `src/backend/core/config/features/sprint5_dsl.py` (feature-flag)
  - `tests/unit/core/config/test_features_sprint5_dsl.py`
  - `.baselines/feature_flags_allow_non_off.txt` (ratchet)
- **Связан с**:
  - ADR-0365 (канон `validate_identifier` — allowlist SQL-идентификаторов)
  - ADR-0359 (канонический SQL-guard `validate_sql`)
  - ADR-0112 (allowlist-идентификаторы как эталон)
  - ADR-0364 (мёртвая конфигурация = ложь в конфиге)
- **Вне зоны (нужны чужие файлы)**:
  - `src/backend/dsl/builders/transport/persistence.py` и
    `src/backend/dsl/builders/base/_protocols/_data.py` — снят hardcoded-дефолт
    `schema="public"` в builder'е (иначе YAML/builder-путь продолжал бы
    игнорировать схему профиля; см. дефект 5 и «Последствия»).

## Контекст

Аудит БД (волна 16, кластер X1) нашёл в DSL-процессоре вызова stored
procedure пять связанных дефектов.

1. **[critical] SQL-инъекция через `schema`/`name` и ключи bind-параметров.**
   `schema` и `name` приходят из YAML-роута, ключи bind-параметров — из
   runtime-body (внешний вход). Все три подставлялись в SQL через f-string
   без какой-либо валидации, а `validate_sql` не вызывался вовсе. Проба:
   `CALL public.recalc(:x) ; DROP TABLE users --)`; PL/SQL-вариант:
   `BEGIN public.recalc; DROP TABLE users; END; --(:id); END;`.
2. **[critical] Fail-open на недоступном feature-flag.** Ошибка чтения
   `feature_flags` логировалась в `debug` и **выполнение продолжалось**
   (проба аудита: «EXECUTED SQL (feature flag unavailable)»).
3. **[medium] Feature-flag по умолчанию был `True`** вопреки докстрингу
   «default-OFF» — вызов stored procedure включался в каждом профиле без
   явного решения.
4. **[medium] `mappings().all()` для `EXEC`/`BEGIN` (mssql/oracle).** У таких
   вызовов result-set отсутствует, cursor закрыт, и `mappings().all()` бросал
   `ResourceClosedError` **до** `commit()` — эффекты процедуры откатывались.
5. **[medium] Схема по умолчанию `public` была неверна для oracle/mssql.**
   В профиле `oracle_1` задана схема `REPORTING`, но дефолт шага её
   игнорировал → вызов уходил в несуществующую `public`.

## Решение

### 1. Allowlist-идентификаторы + общий SQL-guard

* `schema` и `name` проверяются каноном `validate_identifier`
  (`core/utils/sql_identifiers.py`, ADR-0365): `[A-Za-z_][A-Za-z0-9_]*`.
* Ключи bind-параметров (из runtime-body) — тоже allowlist-идентификаторы:
  произвольная строка больше не может стать именем плейсхолдера. Значения
  по-прежнему уходят bind-параметрами SQLAlchemy и в SQL не подставляются.
* Собранный вызов проходит `validate_sql`
  (`dsl/engine/processors/_sql_validation.py`, ADR-0359): multi-statement и
  DDL/privilege-команды запрещены.
* Для Oracle валидируется **тело** вызова (`public.recalc(:id)`), а не
  PL/SQL-обёртка `BEGIN ... END;` — у обёртки есть собственный `;`, из-за
  которого guard её отверг бы; обёртка добавляется уже после валидации тела.
* Нарушение → `exchange.fail(...)`, шаг **не** исполняется (fail-closed).
  Валидация выполняется в runtime, а не в конструкторе: ошибка наблюдаема
  в маршруте (статус `failed`), а не как исключение при сборке роута.

### 2. Fail-closed feature-flag

Ошибка чтения `feature_flags` (ImportError/AttributeError/RuntimeError) →
`logger.error` + `exchange.fail(...)` + `return`. Шаг не исполняется.
Явно выключенный флаг (`False`) сохраняет прежнее поведение «skipped»
(шаг пропускается, маршрут не падает).

### 3. Feature-flag `db_call_procedure_enabled` → default-OFF

`core/config/features/sprint5_dsl.py`: `default=False` (докстринг «default-OFF»
теперь соответствует коду). Запись удалена из ratchet-allowlist'а
`.baselines/feature_flags_allow_non_off.txt` — вернуться к `default=True`
больше нельзя молча.

### 4. Ветка по `result.returns_rows`

Результат материализуется только если `result.returns_rows` истинно (и cursor
не закрыт). Для `EXEC`/`BEGIN` result-set нет → `mappings()` не вызывается
вовсе, `commit()` выполняется, эффекты процедуры фиксируются. Ветка с
result-set материализуется до коммита (cursor ещё открыт), затем
`commit()`.

### 5. Схема — из профиля внешней БД

`schema=None` (по умолчанию) → схема берётся из настроек профиля внешней БД
(`db_schema`, ADR-0365-канон конфигурации: у каждого внешнего профиля схема
обязательна). Явно заданная схема шага приоритетнее. Fallback `public` —
только если профиль недоступен (не зарегистрирован); такой шаг всё равно
не дойдёт до БД (нет session manager'а).

## Альтернативы (отклонённые)

1. **Валидировать идентификаторы в конструкторе процессора.** Отклонено:
   маршрут падал бы на этапе сборки с `ValueError` вместо наблюдаемого
   `exchange.fail` — хуже для диагностики и несовместимо с runtime-контуром
   (`handle_processor_error`).
2. **Экранировать идентификаторы кавычками вместо allowlist.** Отклонено:
   ADR-0112/ADR-0365 — эталон allowlist; экранирование не спасает от
   PL/SQL-инъекции и от идентификаторов-ключей bind-параметров.
3. **Прогонять `validate_sql` по всей PL/SQL-обёртке Oracle.** Отклонено:
   собственный `;` обёртки делает проверку неприменимой; валидируется тело.
4. **Оставить `except` c `logger.debug` (fail-open).** Отклонено: probe
   аудита показал реальное исполнение SQL при недоступном feature-flag.
5. **Оставить `schema="public"` как дефолт и для oracle/mssql.** Отклонено:
   профиль `oracle_1` (схема `REPORTING`) вызывал несуществующую `public`.
6. **Материализовать result-set всегда, но после `commit()`.** Отклонено:
   после коммита cursor закрыт — строки потерялись бы; коммит до
   материализации допустим только в ветке без result-set.

## Последствия

* **Позитивные:** инъекция через `schema`/`name`/bind-ключи невозможна;
  недоступный feature-flag больше не приводит к исполнению SQL; эффекты
  процедуры на mssql/oracle коммитятся; oracle/mssql-профили используют свою
  схему.
* **Негативные / breaking:** `db_call_procedure_enabled` по умолчанию `False`
  → маршруты с этим шагом требуют явного `FEATURE_DB_CALL_PROCEDURE_ENABLED=true`;
  default `schema` в `RouteBuilder.db_call_procedure()` — `None` вместо
  `"public"` (для профилей без `db_schema` — fallback `public`, поведение
  прежнее); в ветке без result-set `payload` = `None` (раньше — пустой список
  либо `ResourceClosedError`); bind-ключи с дефисом (например HTTP-заголовок
  `content-type` при `params_from="headers"`) отвергаются — такой ключ не
  может быть bind-параметром, раньше такой шаг строил невалидный SQL.
* **Вне зоны:** дефолт `schema="public"` в builder'е
  (`dsl/builders/transport/persistence.py` + протокол `_protocols/_data.py`)
  снят минимальной правкой — без неё YAML-роут продолжил бы подставлять
  `public` и игнорировать схему профиля.

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/test_db_call_procedure.py -q
.venv/bin/python -m pytest tests/unit/core/config/test_features_sprint5_dsl.py -q
.venv/bin/python -m ruff check <файлы кластера>
.venv/bin/python tools/config_audit.py --scope orphans       # 0
.venv/bin/python tools/check_layers.py --strict               # 41 (без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
```

## Связи с другими ADR

* **ADR-0365** — канон `validate_identifier`: идентификаторы `schema`/`name` и
  ключи bind-параметров проверяются именно им.
* **ADR-0359** — канонический SQL-guard `validate_sql` (multi-statement и
  DDL/privilege запрещены) применён к телу вызова процедуры.
* **ADR-0112** — allowlist-идентификаторы как эталон (точечные проверки
  вместо глобального `# nosec B608`).
* **ADR-0364** — мёртвая конфигурация = ложь в конфиге: докстринг
  «default-OFF» и фактический default флага приведены к одному значению.
