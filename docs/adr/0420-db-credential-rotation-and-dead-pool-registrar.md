# ADR-0420 — Ротация кредов БД без рестарта и подключение регистратора пулов

* Статус: Accepted (2026-11-02, волна 24, кластер F5 — «ротация кредов БД и мёртвый регистратор пулов»)
* Cycle: 183 (волна 24)
* Связан с:
  - ADR-0372 (приоритет источников конфигурации и рабочий hot-reload: `settings.reload()` переносит значения **in-place**),
  - ADR-0379 (честный hot-reload: отчёт о перезагрузке не скрывает ошибки),
  - ADR-0100 (прецедент: мёртвый код удаляется либо получает реального потребителя),
  - ADR-0387 (деградация пула при старте; graceful-degradation вместо падения),
  - ADR-0383 (санитизация ошибок БД — секреты не утекают в лог)
* Затрагивает:
  - `src/backend/infrastructure/database/database/accessors.py` (accessor'ы main-БД и внешних БД),
  - `src/backend/infrastructure/database/pool_monitor.py` (регистратор пула main-БД),
  - `tests/unit/infrastructure/database/test_db_credential_rotation.py` (новый),
  - `tests/unit/infrastructure/database/test_pool_monitor.py` (починка false-green теста)

---

## Контекст

Волна 24 мультироевого аудита зафиксировала два дефекта контура БД.

**Дефект 1 (medium) — ротация кредов требовала рестарта процесса.**
`get_db_initializer()` и `get_external_db_registry()` — `lru_cache`-синглтоны
(`src/backend/infrastructure/database/database/accessors.py`). Движок
SQLAlchemy создаётся **один раз** и навсегда получает DSN, собранный из
настроек на момент создания. Механизм hot-reload (ADR-0372/0379) при этом
работает: `settings.reload()` пересобирает вложенные модели и переносит
значения **in-place**, то есть `settings.database.password` после reload'а
уже новый. Но синглтон БД про этот reload ничего не знает: движок продолжает
подключаться по **старому** DSN. Итог — смена пароля в Vault/`.env`
подхватывалась только после рестарта процесса, а отозванный пароль продолжал
работать в пуле.

Дополнительно: даже если engine пересоздать, кэши
`get_main_session_manager()` / `get_smart_session_manager()` /
`get_external_session_manager()` (`infrastructure/database/session_manager.py`,
`database/accessors.py`) хранят `async_sessionmaker`, привязанный к **старому**
engine'у, — без их сброса сессии продолжали бы открываться в закрытом пуле.

**Дефект 2 (low) — `_register_db_pool_in_unified_monitor`**
(`infrastructure/database/pool_monitor.py`) — мёртвый код: функция была
приватной и **не имела ни одного вызова** (0 вызовов по всему `src/`). При этом
регистрация пула main-БД в мониторах на старте уже работает по
канонической цепочке `setup_infra/pools.py::_register_pools_in_unified_manager`
→ `UnifiedPoolManager.register("db_main", …)` →
`UnifiedPoolManager.start_monitors()` → `PoolHealthMonitor.register_pool(...)`.
То есть «спик»-функция дублировала уже существующий путь и была не нужна.

## Решение

### 1. Ротация кредов: отпечаток + dispose + пересоздание

* **Отпечаток кредов.** Рядом с каждым DB-объектом хранится
  `_CredentialState(fingerprint, instance)`, где `fingerprint` — SHA-256 от
  набора кредов (тип/хост/порт/имя БД/логин/пароль/драйверы/DSN реплики).
  Секрет в открытом виде не сохраняется — только хэш, поэтому отпечаток
  безопасно держать в памяти и сравнивать. Для реестра внешних БД отпечаток
  считается по всем профилям (`_external_profiles_fingerprint`).
* **Детект.** `get_db_initializer()` / `get_external_db_registry()` при каждом
  обращении сверяют отпечаток с текущими настройками
  (`_detect_main_rotation` / `_detect_external_rotation`). Расхождение ⇒
  «креды изменились». Без смены кредов **ничего не трогаем** — тот же
  engine, тот же пул, тот же объект (проверено тестом
  `test_no_rotation_without_dsn_change`).
* **Dispose.** Старый объект закрывается: `DatabaseInitializer.close()`
  (sync + async engine) либо `ExternalDatabaseRegistry.close_all()`.
  Закрытие **async**, а accessor синхронный, поэтому:
  * в async-контексте dispose планируется задачей на текущем event loop
    (`_schedule_dispose`) — ошибка закрытия логируется, но не роняет
    ротацию;
  * в sync-контексте без event loop пишется warning «async-пул не закрыт,
    соединения освободятся при рестарте» (деградация, а не падение);
  * `apply_db_credential_rotation()` — async-вариант, который **дожидается**
    закрытия (`await`), — используется наблюдателем конфигурации.
* **Пересоздание.** Кэш билдера сбрасывается, новый `DatabaseInitializer` /
  `ExternalDatabaseRegistry` создаётся с актуальным DSN. Одновременно
  сбрасываются кэши session-менеджеров (`_invalidate_session_caches`),
  иначе они держали бы `async_sessionmaker` закрытого engine'а.
* **Совместимость API.** `get_db_initializer.cache_clear()` /
  `get_external_db_registry.cache_clear()` сохранены (используются в тестах и
  в `core/di/providers`): публичные функции-обёртки больше не являются
  `lru_cache`-объектами, поэтому `cache_clear` монтируется вручную и
  сбрасывает также снимок кредов.

### 2. Подключение к hot-reload (ADR-0372/0379)

Связка с наблюдателем конфигурации сделана **двумя путями**:

* **Pull-путь (всегда работает).** `settings.reload()` (ADR-0372/0379)
  обновляет `settings.database` in-place → следующий вызов accessor'а видит
  новый отпечаток → dispose + пересоздание. Никакой дополнительной wiring'и
  для этого не требуется.
* **Push-путь ( явный async-hook).** `apply_db_credential_rotation()` —
  публичная async-функция (возвращает `True`, если креды изменились), и
  `register_db_credential_rotation_callback(reloader)` — регистрация
  callback'а в `ConfigHotReloader` (`core/config/hot_reload.py`).
  Composition-root вызывает её рядом с `register_settings_reload_callback`.

### 3. Судьба `_register_db_pool_in_unified_monitor` — **подключена**

Функция не удалена, а **переведена в публичную и получила реального
потребителя**: `register_db_pool_in_unified_monitor(initializer=None)`
(`infrastructure/database/pool_monitor.py`). Причина — не «спасти мёртвый
код», а новая потребность, которой раньше не было: после ротации кредов
engine пересоздаётся, а значит **меняется объект пула**. Мониторы
(`UnifiedPoolManager`, `PoolHealthMonitor`) держали бы ссылку на пул
**старого** engine'а и пинговали бы его по **отозванным** кредам — то есть
ротация создала бы новый дефект. Пере-регистрация (идемпотентная, запись
`db_main` перезаписывается) вызывается из пути ротации.

Стартовая регистрация не менялась: она по-прежнему идёт по канонической
цепочке `setup_infra/pools.py` → `UnifiedPoolManager` → `PoolHealthMonitor`.

### 4. Починка false-green теста

`tests/unit/infrastructure/database/test_pool_monitor.py::test_collect_stats_no_initializer`
патчил **не тот** модуль (`pool_monitor.db_initializer`), тогда как
`collect_stats()` импортирует `db_initializer` из **пакета**
`src.backend.infrastructure.database.database`. Тест проходил только потому,
что в кэше accessor'а оказывался `MagicMock`, оставшийся от другого теста
(order-dependent false-green). Тест теперь патчит правильную цель и проверяет
ветку «инициализатора нет» честно (ADR-0379: честный статус вместо
зелёного).

## Альтернативы (отклонённые)

1. **Удалить `_register_db_pool_in_unified_monitor` (прецедент ADR-0100).**
   Отклонено: после появления ротации мониторам **нужен** регистратор пула
   main-БД — объект пула меняется вместе с engine'ом. Удаление оставило бы
   мониторы пингующими disposed-пул по старым кредам (дефект, созданный
   фиксом). Стартовый сценарий дублировать не нужно — он уже покрыт
   `setup_infra/pools.py`.
2. **Ротация только по callback'у hot-reload (без pull-пути).** Отклонено:
   accessor'ы БД используются и вне async-контекста наблюдателя конфигурации
   (CLI, фоновые задачи, тесты). Pull-путь гарантирует, что смена DSN
   подхватывается **всегда**, а не только при срабатывании watcher'а.
3. **Полностью асинхронные accessor'ы (`await get_db_initializer()`).**
   Отклонено: ломает публичный контракт десятков вызывающих (core-DSL,
   `core/di/providers`, `infrastructure/dsl`) — изменение выходит за зону
   кластера и несоразмерно дефекту.
4. **Отпечаток из готового DSN (`settings.database.async_connection_url`).**
   Отклонено: построение DSN дёргает `ensure_driver_available`
   (`importlib.util.find_spec`) на каждом обращении к accessor'у — лишний
   I/O в горячем пути. Отпечаток считается по сырым полям настроек.
5. **Хранить DSN в открытом виде для сравнения.** Отклонено: пароль в
   открытом виде в памяти процесса — лишнее расширение поверхности утечки;
   SHA-256 сравнивается так же, но секрет не дублируется.
6. **Сбрасывать кэши session-менеджеров через прямой импорт
   `session_manager` в `accessors`.** Отклонено: прямой импорт создаёт цикл
   `accessors → session_manager → database → accessors`, из-за которого mypy
   перестаёт разрешать атрибуты пакета-``__init__`` (они типизируются как
   ``Any?``). Используется `importlib.import_module` — тот же приём, что и в
   `core/di/providers/infrastructure_locator.py`.

## Последствия

* **Позитивные:** смена DSN (Vault/`.env` → `settings.reload()`) подхватывается
  без рестарта; отозванный пароль перестаёт использоваться пулом; кэши
  session-менеджеров не удерживают закрытый engine; мониторы пулов после
  ротации работают с новым пулом и новыми кредами; мёртвый регистратор
  получил реального потребителя и покрыт тестом.
* **Негативные:** при смене DSN in-flight-сессии старого engine'а
  завершаются на старых соединениях (смена кредов — операция с побочным
  эффектом; альтернатива «ждать всех in-flight» не реализована);
  пере-регистрация пула в мониторах выполняется синхронно (регистрация
  объектов, без I/O); при отсутствии event loop async-пул остаётся открытым
  до рестарта (warning в лог, деградация, а не падение).
* **Вне зоны (нужен владелец):**
  - `src/backend/plugins/composition/setup_infra/lifecycle.py` — вызов
    `register_db_credential_rotation_callback(reloader)` рядом с
    `register_settings_reload_callback(reloader)` (**одна строка**). Без неё
    push-путь не задействован; pull-путь (детект по accessor'ам) работает и
    сейчас. Файл принадлежит composition-root'у и в зону кластера F5 не
    входил.
  - `src/backend/infrastructure/clients/pool_health.py` — docstring модуля
    упоминает «Spike-регистрацию через ``infrastructure.database.pool_monitor``»
    как «демонстрацию паттерна»; после ADR-0420 регистратор рабочий, а не
    спик — текст устарел.
  - `docs/adr/INDEX.md` — индекс ADR обновляется генератором
    (`tools/build_adr_index.py`); в этой задаче не редактировался.
  - `RESTART_REQUIRED_SECTIONS` в `core/config/hot_reload.py` — список
    секций, требующих рестарта, включает ``database.*`` /
    ``external_databases.*``; после ADR-0420 **DSN** применяется без рестарта,
    а параметры пула (`pool_size`, `max_overflow`, `pool_recycle`) — по-прежнему
    только после рестарта. Список стоит уточнить (ADR-0400).

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/database -q -p no:randomly
.venv/bin/python -m ruff check \
    src/backend/infrastructure/database/database/accessors.py \
    src/backend/infrastructure/database/pool_monitor.py \
    tests/unit/infrastructure/database/test_db_credential_rotation.py \
    tests/unit/infrastructure/database/test_pool_monitor.py
.venv/bin/python tools/check_layers.py --strict        # 41 (новых нет)
.venv/bin/python tools/config_audit.py --scope orphans  # 0
.venv/bin/python tools/checks/mypy_budget.py            # OK (8 ошибок, budget 30)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0  # 0 missing
```

Red→green (фактический прогон):

* **RED** (на исходном коде): `test_db_credential_rotation.py` →
  `6 failed, 2 passed`. Падали: `test_engine_recreated_on_dsn_change`
  (accessor отдавал **тот же** engine после смены DSN),
  `test_apply_db_credential_rotation_awaits_dispose` /
  `test_apply_db_credential_rotation_noop_without_change`
  (`AttributeError: ... has no attribute 'apply_db_credential_rotation'`),
  `test_external_registry_recreated_on_credential_change`,
  `test_db_pool_registrar_called_after_rotation` и
  `test_db_pool_registrar_registers_pool_in_unified_monitor`
  (регистратора не существовало).
* **GREEN** (после правки): `tests/unit/infrastructure/database` →
  `214 passed, 7 skipped` (стабильно при случайном порядке — 3 прогона).

## Связи с другими ADR

* **ADR-0372 / ADR-0379** — hot-reload обновляет настройки in-place; именно
  этот механизм делает смену DSN наблюдаемой для accessor'ов.
* **ADR-0100** — прецедент «мёртвый код: удалить или дать потребителя»;
  здесь выбран второй вариант (потребитель — ротация кредов).
* **ADR-0387** — graceful-degradation: ошибка закрытия пула не роняет
  ротацию, отсутствие event loop даёт warning, а не исключение.
* **ADR-0383** — секреты не попадают в лог: отпечаток хранится как хэш,
  DSN не логируется.
* **ADR-0284** — новых межслойных импортов нет: все изменения лежат в
  слое `infrastructure` (`accessors.py` → `core.config.hot_reload` только в
  `TYPE_CHECKING`-блоке).
