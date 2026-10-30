# ADR-0400 — Snapshot под RLS, интроспекция GraphQL, честный hot-reload и гейт профилей

* Статус: Accepted (2026-10-30, волна 20, кластер W3)
* Автор: coder-агент, кластер W3 (БД, конфиг, BLS-контроль)
* Связи: ADR-0372 (источники конфигурации и hot-reload), ADR-0379 (честность
  hot-reload и env-приоритет), ADR-0365 (единый канон SQL-идентификаторов),
  ADR-0366 (runtime-резолвер capability-гейта), ADR-0386/ADR-0393 (RLS и
  capability-политика в prod/staging), ADR-0112 (allowlist-идентификаторы),
  ADR-0397 (эргономика DSL — контекст capability-словаря)

---

## Контекст

Волна 20 закрыла остаточные дефекты кластера «БД, конфиг, гейт профилей»:

1. **Snapshot читает tenant-таблицы мимо контекста.**
   `infrastructure/resilience/snapshot_job.py::_replicate_table` выполнял
   `pg_conn.execute(select(table))` без tenant-скоупа. Таблицы `users`,
   `orders`, `orderkinds` защищены `FORCE ROW LEVEL SECURITY` с политикой
   `tenant_id = current_setting('app.tenant_id', true)`: без выставленного
   `app.tenant_id` выборка возвращает **0 строк** — снапшот пуст, ошибки нет,
   fallback `db_main` деградирует тихо. В `prod.yml` job выключен
   (`snapshot.enabled: false`), поэтому дефект был латентным.
2. **`graphql.enable_introspection` не подключён.**
   `entrypoints/graphql/graphql_guards.py::_introspection_allowed` смотрел
   только на `settings.app.environment`. Декларативный ключ
   `graphql.enable_introspection` (base/prod/staging.yml) не читался — конфиг
   был «не подключён», а профильный валидатор его значение не проверял.
3. **Hot-reload не предупреждает про пулы БД.**
   Отчёт `POST /admin/config/reload` не содержал строки о том, что параметры
   `database.*` / `external_databases.*` применяются только после рестарта:
   оператор считал новые значения пула уже действующими.
4. **`load_env_file()` не вызывается из CLI.**
   Долг ADR-0372: `.env` (в нём — только секреты) формально подхватывался
   входом в цепочку источников, но CLI-старт не объявлял это явно.
5. **Env-приоритет был регистрозависим** (ADR-0379) — помечен `xfail`.
6. **`required_capability` в `agent_dsl/*` был декларацией без эффекта.**
   13 классов объявляли capability, но `BaseAIProcessor.process()` её не
   проверял (ADR-0366 G12.2).
7. **4-я реализация SQL-валидации идентификаторов**
   (`services/io/external_database/dispatch_mixin.py`) — локальные regex
   дублировали правило, канон ADR-0365 требовал один источник истины.

---

## Решение

1. **Snapshot под RLS** (`infrastructure/resilience/snapshot_job.py`):
   перед выборкой соединение получает явный tenant-скоуп
   `SELECT set_config('app.tenant_id', :tenant_id, true)` (transaction-local,
   значение не «залипает» в пуле). Tenant берётся из tenant-контекста
   процесса; при его отсутствии — системный tenant `_system` **с WARNING**
   в лог. Прочитанное правило — тот же канон, что в
   `core/tenancy/sqlalchemy_filter.py`.
2. **Интроспекция GraphQL** (`entrypoints/graphql/graphql_guards.py`):
   интроспекция разрешена только при выполнении **обоих** условий —
   `graphql.enable_introspection == true` **и**
   `app.environment == "development"`. Конфиг недоступен → fail-closed
   (запрет).
3. **Профильный гейт** (`core/config/validator/profile_merge.py`): в
   prod/staging `graphql.enable_introspection: true` — CRITICAL-нарушение
   (`graphql.introspection_enabled_in_prod`).
4. **Честный hot-reload** (`core/config/hot_reload.py`): отчёт reload
   содержит `restart_required: ["database.*", "external_databases.*"]` и
   сопровождается WARNING-логом — пулы БД создаются на старте, hot-reload
   их не пересоздаёт.
5. **CLI загружает `.env` явно**: `manage.py` и `src/backend/main.py` вызывают
   `load_env_file()` при старте (в `main.py` — до импорта `settings`);
   вызов идемпотентен и совместим с приоритетом источников ADR-0372.
6. **Env-приоритет** (`core/config/config_loader.py`): сравнение окружения и
   `.env` регистронезависимое (`_dotenv_only_keys`), `xfail` снят — фикс
   закрыт ADR-0376; в волне 20 добавлен регрессионный тест.
7. **Capability-гейт AI-процессоров** (`dsl/engine/processors/agent_dsl/_base.py`):
   `process()` вызывает канонический `BaseProcessor.auth_check` до `_run`;
   отказ → exchange в `failed` (fail-closed, ADR-0393), действие не
   выполняется. Обходной `_check_capability` удалён.
8. **Канон SQL-идентификаторов**: `core/utils/sql_identifiers.py` получил
   `validate_qualified_identifier` (`name` / `schema.name` / `db.schema.name`,
   до 3 сегментов, каждый — по правилу `validate_identifier`);
   `dispatch_mixin.py` использует канон, локальные `_IDENT_RE` /
   `_BIND_NAME_RE` удалены. Поведение пакета сохранено: недопустимое имя →
   `DatabaseError` с прежним текстом.

---

## Альтернативы (отклонённые)

1. **Служебная роль с `BYPASSRLS` для snapshot'а** — отклонено как
   единственное решение: такой роли/DSN в конфигурации нет, а её выдача —
   эксплуатационное решение владельца БД. Tenant-скоуп + явное предупреждение
   закрывают «тихую потерю» уже сейчас.
2. **Игнорировать `graphql.enable_introspection` в dev** — отклонено: ключ
   объявлен в конфиге, значит должен влиять на поведение; иначе конфиг — ложь.
3. **Молчаливый hot-reload без предупреждения о пулах** — отклонено: это
   ровно тот класс «честности отчёта», который ADR-0379 закрыл для `failed`.
4. **Вызов `load_env_file()` только в `manage.py`** — отклонено: ASGI-точка
   входа (`src/backend/main.py`) запускается и без CLI (uvicorn/granian).
5. **Оставить `BaseAIProcessor._check_capability`** — отклонено: обходной
   путь не учитывает feature-флаг `dsl_capability_gate_enabled` и не
   переводит exchange в `failed` (ADR-0393).
6. **Свести на канон весь пакет `services/io/external_database`** — отложено:
   `validation_mixin.py`, `profile_mixin.py`, `build_mixin.py`, `core_mixin.py`,
   `state.py`, `__init__.py` — вне зоны кластера (см. «Последствия»).

---

## Последствия

* **Позитивные:** snapshot под RLS не пустеет молча; конфиг-ключ интроспекции
  влияет на рантайм и защищён профильным гейтом; отчёт reload честен про
  рестарт; `.env` читается явно на старте; capability AI-процессоров
  действительно применяется (fail-closed); правило SQL-идентификаторов
  определено в одном месте.
* **Ограничения / вне зоны (требует владельца):**
  * под RLS снимок покрывает **один** tenant — для межtenant-снимка нужна
    служебная роль с `BYPASSRLS` (ADR-0393, «BYPASSRLS-роль для служебных
    соединений»);
  * остальные копии `_IDENT_RE` в `services/io/external_database`
    (`validation_mixin.py`, `profile_mixin.py`, `build_mixin.py`,
    `core_mixin.py`, `state.py`, `__init__.py`) не сведены — вне зоны
    кластера (ADR-0365, «Известный долг»);
  * корневой `Settings` (`core/config/settings.py`) не отдаёт секцию
    `graphql` — `settings.graphql.enable_introspection` требует одной
    строки в корневом агрегаторе (вне зоны кластера; сейчас используется
    модельный синглтон `core.config.services.graphql.graphql_settings`).

---

## Проверка

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/resilience/test_snapshot_job.py \
  tests/unit/entrypoints/graphql/test_graphql_guards_introspection.py \
  tests/unit/core/config/test_hot_reload.py \
  tests/unit/core/config/test_profile_graphql_introspection_gate.py \
  tests/unit/core/config/test_config_sources_priority.py \
  tests/unit/cli/test_env_loading_at_startup.py \
  tests/unit/dsl/engine/processors/agent_dsl/test_base_auth_check.py \
  tests/unit/services/io/external_database/test_dispatch_identifier_canon.py \
  -q -p no:randomly
.venv/bin/python -m ruff check <файлы кластера>
.venv/bin/python tools/config_audit.py --scope orphans   # 0
.venv/bin/python tools/check_layers.py --strict         # 41 (baseline, без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0  # 0
```

---

## Связи с другими ADR

* ADR-0365 — единый канон валидации SQL-идентификаторов.
* ADR-0366 / ADR-0393 — runtime-резолвер capability-гейта и fail-closed.
* ADR-0372 / ADR-0379 — источники конфигурации, hot-reload, env-приоритет.
* ADR-0386 — RLS-coverage и tenant-скоуп соединений.
* ADR-0112 — allowlist-идентификаторы как эталон.
