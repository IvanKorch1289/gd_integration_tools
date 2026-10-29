# ADR-0393 — DB-capability-гейт, tenant-изоляция DSL-SQL и авторизация RPA

* Статус: Accepted (2026-10-29, волна 18 повторного аудита)
* Автор: coder-агент, кластер G4
* Связи: ADR-0366 (runtime-резолвер capability-гейта), ADR-0383 (raw-SQL guard),
  ADR-0386 (RLS-coverage), ADR-0368 (таймауты RPA), ADR-0369 (достижимость
  шагов из YAML), ADR-0392 (audit-доставка), ADR-0078/ADR-044 (модель capability)

---

## Контекст

Волна 18 повторного аудита вех нашла 14 дефектов в кластере
«БД-capability, tenant-гейт и RPA-авторизация»:

1. Отказ capability-гейта маскировался под успех: `BaseProcessor.auth_check`
   делал `set_error` + `stop()`, статус exchange оставался `processing`,
   а `ExecutionEngine._finalize` вызывал `exchange.complete()`, который
   **обнулял** `error`. Клиент получал «успех», SLO-счётчик — `is_error=False`.
2. Ни один БД-процессор не объявлял `required_capability`: любой DSL-роут
   читал и писал любую БД.
3. Список tenant-aware таблиц зависел от `configure_mappers()`: до
   конфигурации mapper'ов (и для моделей с собственным `DeclarativeBase`,
   например `rule_engine_rulesets`) запрос к tenant-таблице **не**
   блокировался.
4. DSL-CRUD ходил через Core `Connection` — мимо ORM-фильтра и raw-SQL guard'а:
   `.db_delete("workflow_instances", {...})` не был tenant-scoped.
5. RLS-скоуп ставился только из ContextVar, а фоновые пути (pg-runner) его
   не биндят → на PostgreSQL с `FORCE RLS` — 0 строк / отказ `INSERT`.
6. Raw-SQL guard не видел `COPY … TO STDOUT`, `TRUNCATE`, `FROM ONLY`.
7. Отсутствовал лимит выборки (`fetchall()` без ограничения).
8. Доступ к данным не порождал ни одного audit-события.
9. В prod/staging capability-гейт оставался в legacy-пути: RPA-шаги (44
   процессора) отклонялись все и без внятной причины — случайно, а не по
   политике.
10. `fill_form` / `run_scenario` (legacy `processors/web.py`) шли вообще без
    capability-проверки — обход гейта.
11. `desktop_rpa` / `desktop_pyautogui` документировали YAML-использование, но
    были недостижимы из YAML (нарушен канон ADR-0369).
12. `max_sessions` в пуле desktop-RPA не enforced, eviction закрывал клиент
    под активным пользователем.
13. OCR в DSL-шаге остался без таймаута (ADR-0368 починил только сервисный
    OCR-процессор).
14. `tests/unit/core/tenancy/test_tenant_filter_orm_dml.py` падал с
    `AttributeError` (`sqlalchemy_continuum`) в общем сеансе с
    `tests/unit/infrastructure/database` — order-dependent регрессия.

## Решение

### Capability-гейт (пункты 1, 2, 9, 10)

* `BaseProcessor.auth_check` при отказе вызывает `exchange.fail(...)`
  (статус `failed`) вместо `set_error` + `stop()`. Отказ авторизации больше
  не выглядит как успешный маршрут; `_finalize` не вызывает `complete()`,
  SLO получает `is_error=True`.
* Пять БД-процессоров (`db_query_external`, `db_crud`, `jdbc_query`,
  `infra_db`, `DatabaseQueryProcessor`) объявляют capability:
  * `db.read` — для читающих запросов, `db.write` — для DML и любых
    неопознанных команд (fail-closed);
  * **scope** = алиас ресурса: имя таблицы (внутренняя БД) либо имя профиля
    внешней БД. Это ровно та семантика, что уже используется в
    `ExternalDatabaseFacade` и в `plugin.toml` (`db.read` + scope=`orders`);
  * вызов `auth_check` — до любого обращения к БД.
* `fill_form` / `run_scenario` обёрнуты в `CapabilityGuardedProcessor`
  (`rpa.browser.fill` / `rpa.browser.navigate`) — legacy-процессор сам
  capability не проверял.
* **Политика capability-гейта в prod/staging** (пункт 9): выбран вариант
  «включить флаг + объявить capability явно», а не «оставить выключенным»:
  * `dsl_capability_gate_enabled: true` — runtime-резолвер (ADR-0366),
    отказ с machine-readable причиной;
  * `dsl_capability_core_baseline_enabled: false` — least privilege: доступ
    определяется только декларациями роутов/плагинов.
  * Следствие, зафиксированное осознанно: capability `rpa.*` не публична и не
    принадлежит ни одному плагину → RPA-шаги в prod/staging отклоняются
    fail-closed, пока роут не объявит их через плагина-владельца. Это
    **явная** политика (ADR + проверка профиля), а не побочный эффект
    legacy-пути.
  * Объявить `rpa.*` прямо в `route.toml` нельзя: subset-инвариант
    ``route.capabilities ⊆ plugins ∪ public`` отклоняет такой роут
    (``CapabilitySupersetError``) — роут просто не загрузился бы. Поэтому
    RPA-каpability требует плагина-владельца (ADR-0078/ADR-044).
  * Для БД capability схема рабочая: ``[[route.capabilities]] name="db.read"
    scope="orders"`` + ``requires_plugins`` плагина-владельца ресурса
    (``core_entities_orders`` объявляет ``db.read`` со scope ``orders``) —
    subset-инвариант проходит, роут загружается, capability выдаётся.
  * Проверка профиля (`core/config/validator/profile_merge.py`) поднимает
    CRITICAL, если в prod/staging гейт выключен, и WARNING, если включён
    core-baseline.

### Tenant-изоляция (пункты 3, 4, 5, 6)

* Tenant-aware таблицы определяются по **колонке `tenant_id` в metadata**
  (все известные `MetaData`: ядро, расширения, отдельный `RuleEngineBase`) и
  по событию `Table.after_parent_attach` — больше не зависит от
  `configure_mappers()`.
* Канон разбора raw SQL расширен: `TRUNCATE`, `COPY`, `FROM ONLY <table>`.
* DSL-CRUD (`db_crud`) для tenant-aware таблиц **сам** добавляет
  `tenant_id` в `WHERE` (UPDATE/DELETE) или в `data` (INSERT/UPSERT); без
  tenant-контекста шаг падает fail-closed с понятной ошибкой.
  `DatabaseQueryProcessor` (Core-путь) перед выполнением зовёт общий
  `guard_raw_sql` — обращение к tenant-aware таблице без явного
  `tenant_id`-предиката отклоняется.
* RLS-скоуп: добавлен публичный хелпер `set_tenant_scope(connection, tenant_id)`
  и fallback в `before_flush` — если tenant-контекст не привязан (фоновые
  пути), scope берётся из tenant'а сохраняемых объектов. Это закрывает
  `INSERT` в tenant-таблицу на PostgreSQL с `FORCE RLS` без правки
  фонового кода.

### Ограничения выборки и аудит (пункты 7, 8)

* `MAX_RESULT_ROWS = 1000` — общий лимит для всех БД-процессоров; при
  обрезке пишется warning, данные не теряются молча.
* Каждый доступ к данным порождает audit-событие (`db.read` / `db.write`) с
  capability, алиасом ресурса, action, route и tenant — **без значений
  данных**.

### RPA (пункты 11, 12, 13)

* `desktop_rpa` / `desktop_pyautogui` получили публичные методы билдера →
  достижимы из YAML (канон ADR-0369).
* `max_sessions` в пуле desktop-RPA enforced: при достижении лимита
  вытесняется самая давно использованная **idle**-сессия; активные сессии
  не выбрасываются никогда, при исчерпании — `PoolCapacityError`.
  Ведётся счётчик активных пользователей на `app_name`.
* DSL-шаг `ocr` получил предел ожидания (двойной: процесс-timeout внутри
  `pytesseract` + внешний `asyncio.wait_for`) с понятной ошибкой.

### Регрессия тестов (пункт 14)

* `apply_tenant_filter()` конфигурирует mapper'ы доменных моделей **до**
  early-return. Глобальный listener SQLAlchemy-Continuum
  (`Mapper.after_configured`) падал, когда доменные модели были импортированы,
  но не сконфигурированы, а конфигурировался mapper другого registry.

## Альтернативы

* **Оставить `dsl_capability_gate_enabled` выключенным в prod/staging.**
  Отклонено: legacy-путь отказывает по любой capability без внятной причины —
  отказ неотличим от «сломанного шага», а БД-шаги без `required_capability`
  вообще не проверялись.
* **Сделать `db.read` / `db.write` публичными в vocabulary.**
  Отклонено: публичность снимает только declaration-time проверку манифеста,
  но разрешила бы роуту объявить доступ к данным без плагина-владельца.
  Вместо этого scope = алиас ресурса, а объявление остаётся в руках
  плагина-владельца (`plugin.toml` → `[[capabilities]]`).
  **Позже отменено (ADR-0397):** `db.read`/`db.write` сделаны публичными
  (`public=True`, `scope_required=True`, `ExactAliasMatcher`) — иначе автор
  роута не мог выразить доступ к БД в принципе (subset-проверка отвергала
  декларацию роута, а scope обязан был совпасть с алиасом профиля). Runtime-
  контроль, сверка scope с профилями БД и `prod`-baseline=off сохранены.
* **Запретить DSL-CRUD по tenant-aware таблицам целиком.**
  Отклонено: tenant-скоуп можно построить конструктивно (инъекция
  `tenant_id` в WHERE/DATA) — это сохраняет функциональность и не ослабляет
  изоляцию.
* **BYPASSRLS-роль для служебных соединений pg-runner'а.**
  Рассмотрено и оставлено как рекомендация (owner-задача, вне зоны кластера):
  кодом закрыт общий случай (scope из tenant-контекста и из flush'а), но
  для служжебной БД без tenant-контекста правильным остаётся
  `BYPASSRLS`-роль.
* **Переносить `fill_form` / `run_scenario` на Playwright.**
  Отложено: multi-field форма в `rpa_browser` не поддержана (Sprint 180+);
  сейчас закрыт обход гейта через `CapabilityGuardedProcessor`.

## Последствия

* **Позитивные**: отказ capability-гейта виден клиенту и в SLO; БД-доступ
  роута требует явной декларации; DSL-CRUD tenant-scoped; tenant-guard
  не зависит от порядка конфигурации mapper'ов; аудит доступа к данным
  появился; лимит выборки ограничивает потребление памяти.
* **Издержки**: БД-шаги требуют декларации `db.read`/`db.write` в `route.toml`
  (либо в `plugin.toml` плагина-владельца) — это работа для владельцев
  роутов; RPA-шаги в prod/staging остаются заблокированными до появления
  плагина-владельца RPA-capability.
* **Совместимость**: capability `db.read`/`db.write` использует
  `ExactAliasMatcher` — одна capability несёт один scope на роут; запросы,
  затрагивающие несколько таблиц, fail-closed (их следует разбивать на шаги).

## Проверка

* `tests/unit/dsl/engine/capability/test_capability_gate_route.py` —
  engine-тест «denied capability → route failed», тесты БД-capability
  (allow/deny по декларации роута), тест «RPA-шаг в prod-профиле:
  allow/deny согласно политике», тесты схемы декларации capability в
  `route.toml` (ADR-0078/ADR-044).
* `tests/unit/core/tenancy/test_tenant_guard_adr0393.py` — tenant-таблицы из
  metadata (включая `rule_engine_rulesets`), расширенный канон raw SQL
  (`COPY`/`TRUNCATE`/`FROM ONLY`), tenant-скоуп DSL-CRUD, RLS-скоуп из flush'а.
* `tests/unit/core/config/test_capability_policy_profiles.py` — политика
  capability-гейта в профилях prod/staging.
* `tests/unit/dsl/engine/processors/test_db_limits_and_audit_adr0393.py` —
  лимит выборки и audit-событие доступа к данным.
* `tests/unit/dsl/engine/processors/rpa/test_adr0393_rpa_guards.py` —
  capability для `fill_form`/`run_scenario`, достижимость `desktop_rpa` /
  `desktop_pyautogui` из YAML, таймаут OCR.
* `tests/unit/services/rpa/test_desktop_session_pool_limits.py` — лимит
  `max_sessions` и учёт активных пользователей.
* `tools/config_audit.py --scope orphans` → 0; `tools/check_layers.py --strict`
  → без новых нарушений (baseline 41); `tools/check_docstrings.py src
  --max-allowed 0` → без новых замечаний.

## Связи

ADR-0366, ADR-0383, ADR-0386, ADR-0368, ADR-0369, ADR-0392, ADR-0078/ADR-044.
