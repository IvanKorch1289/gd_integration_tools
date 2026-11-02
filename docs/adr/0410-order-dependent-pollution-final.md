# ADR-0410 — Финальное закрытие order-dependent падений (волна 22, кластер B6)

* Статус: Accepted (2026-11-02)
* Автор: wave-22, кластер B6
* Затрагивает: `tests/unit/conftest.py`, `tests/unit/dsl/round_trip/test_core_processors.py`,
  `tests/unit/dsl/blueprints/test_python_blueprints_focused.py`,
  `tests/unit/entrypoints/api/v1/endpoints/test_p0_fixes_cycle_241.py`,
  `tests/unit/test_order_dependent_pollution_gate.py`

## Контекст

ADR-0404 закрыл массовую волну order-dependent падений (86 → единицы), но
оставил **7 падений**, каждое из которых проходило в изоляции и падало в
полном прогоне `pytest tests/unit`. Волна 22, кластер B6 — финальная зачистка.

Разбор дал **три независимых механизма загрязнения process-global состояния**,
а не семь разных причин:

| # | Механизм | Симптом |
|---|---|---|
| 1 | **Уровень корневого stdlib-логгера** — process-global, менялся импортом тест-модуля | 3 падения: `test_webhook_stop_router_error_swallowed`, `test_toggle_flag_exception_returns_false`, `test_schedule_cron_replace_existing_missing_schedule` |
| 2 | **Глобальный `ActionHandlerRegistry`** (реестр action'ов) | 3 падения: `test_registry_is_not_empty`, `test_multi_processor_pipeline_round_trip`, `test_dispatch_action_with_payload_factory_skipped_in_spec` |
| 3 | **Порядок импорта модулей** (`sys.modules`) | 1 падение: `test_p0_2_action_not_in_registry_returns_404` |
| 4 | **Legacy-регистрации bootstrap'а** в том же реестре (обнаружено при перепроверке) | `test_transports_is_non_empty_tuple_of_strings` — «транспорты пуст» у чужой декларации |

### Механизм 1 — уровень корневого логгера

`tests/unit/test_manage_grpc_serve.py` (и ещё 3 модуля) делают
`from manage import app` **на уровне модуля**. Импорт CLI-приложения тянет
`init_application_logging()`, который выставляет корневому stdlib-логгеру
уровень из активного профиля (в dev — `DEBUG`). Импорт происходит на этапе
collection, когда ни одна фикстура ещё не работает, — уровень оставался
`DEBUG` на весь прогон.

При `DEBUG` каждый production-вызов
`logging.getLogger(...).debug(msg, extra={"name": ...})` реально создаёт
`LogRecord`, а stdlib logging отклоняет ключ `name` (он уже есть в
`LogRecord`): `KeyError: "Attempt to overwrite 'name' in LogRecord"`.
Исключение прилетает **изнутри error-handler'а**, который логирует исходную
ошибку, — поэтому падал не «неверный» тест, а сам оборонительный код.

### Механизм 2 — глобальный реестр action'ов

`ActionHandlerRegistry` — синглтон с тремя хранилищами: `_handlers`,
`_metadata`, `_middleware`.

* `tests/unit/dsl/blueprints/test_python_blueprints_focused.py` вызывал
  `action_handler_registry.clear()` (сносит **все три** хранилища), но
  возвращал только `_handlers`. `_metadata` терялись для всего процесса →
  `test_registry_is_not_empty` видел «0 action'ов».
* `Pipeline.build()` и YAML-загрузчик валидируют имена `dispatch_action` по
  **живому** реестру. Пока реестр пуст — валидация пропускается; как только
  его наполняет соседний модуль, `rt.handler` становится «неизвестным» и
  round-trip-тесты падают с `Unknown action(s) in pipeline 'rt.multi'`.

### Механизм 3 — порядок импорта

`legacy_aliases._dispatch_with` читает реестр как
`from src.backend.core.api.extensions import action_handler_registry` —
**внутри функции**, т.е. берёт атрибут модуля-фасада. Тест подменял
`src.backend.dsl.commands.action_registry.action_handler_registry`, что
работало только пока `src.backend.core.api.extensions` ещё не был импортирован
(тогда импорт внутри функции подхватывал подмену). Соседний тест-модуль
`tests/unit/core/api/test_extensions_facade.py` импортирует фасад на уровне
модуля → подмена переставала действовать → запрос уходил в **живой** реестр →
`500` вместо `404`.

### Механизм 4 — legacy-регистрации bootstrap'а

Импорт приложения (`import src.backend.main`, `import manage`) поднимает
bootstrap, который регистрирует ~190 legacy-action'ов через
`ActionHandlerRegistry.register()`. Такая регистрация создаёт **минимальные**
метаданные: `ActionMetadata(action=..., input_model=None)` → `transports=()`,
`description=None`, `side_effect="none"`.

До волны 22 это было не видно: метаданные стирались фикстурой blueprint-тестов
(см. механизм 2), и контракт-тест проходил вакуумно. После того как
загрязнение устранено, контракт-тест увидел в глобальном реестре 104 чужие
legacy-объявления и упал на «`admin.get_cache_value`: transports пуст».

Декларативные метаданные API v1 (проверяемый контракт) при этом валидны:
`action_spec_to_metadata()` всегда выставляет непустой `transports`
(дефолт `("http",)`). То есть инвариант «у каждого action'а непустой
`transports`» верен ровно для декларативных регистраций.

## Решение

1. **Уровень корневого логгера — session-baseline** (`tests/unit/conftest.py`).
   `pytest_configure` фиксирует единственный легитимный уровень сессии сразу
   после инициализации logging-backend (до collection);
   `pytest_collection_finish` возвращает этот уровень после collection
   (откатывает загрязнение от импорта `manage`); autouse-фикстура
   `_restore_root_logger` восстанавливает **baseline**, а не «значение на
   входе теста» (оно уже может быть загрязнено соседним модулем).
   Assert'ы не ослаблены, skip/xfail не вводились.
2. **Реестр action'ов изолирован явно.**
   * `test_python_blueprints_focused.py`: snapshot/restore расширен на
     `_handlers`, `_metadata` **и** `_middleware` (ADR-0404-паттерн).
   * `test_core_processors.py`: новая autouse-фикстура `_registered_actions`
     регистрирует нужные action'ы на время теста и возвращает реестр к
     исходному состоянию. Продуктовая DX-1-валидация имён action'ов при
     этом **остаётся включённой** — тест не отключает проверку, а делает
     зависимость от глобального состояния явной.
3. **Подмена реестра — по месту чтения.** Тест подменяет
   `src.backend.core.api.extensions.action_handler_registry` — тот атрибут,
   который действительно читает `legacy_aliases`. Молчаливая подмена
   «похожего» имени запрещена.
4. **Legacy-регистрации bootstrap'а изолированы.** В
   `tests/unit/conftest.py` добавлен контекстный менеджер
   `isolated_action_registry()`: он снимает ТОЛЬКО те записи глобального
   реестра, которые добавил bootstrap и у которых минимальные метаданные
   (пустой `transports`), и оставляет декларативные метаданные API v1.
   Применён в модулях, импортирующих приложение: `tests/unit/test_main.py`,
   `tests/unit/test_main_mcp_mount.py`,
   `tests/unit/test_main_workflow_fallback.py`,
   `tests/unit/test_manage_grpc_serve.py`,
   `tests/unit/test_manage_validate_profile.py`,
   `tests/unit/core/config/test_validate_profile_merged.py`,
   `tests/unit/cli/test_env_loading_at_startup.py`.
5. **Снят skip, маскировавший order-dependent падения.**
   `test_p0_fixes_cycle_241.py`: 4 теста, помеченные
   `@pytest.mark.skip(reason="S44 W41: pre-existing flaky test (test
   isolation issue)")`, сняты с skip — после фикса причины они проходят и в
   изоляции, и в batch-контексте. Skip был худшей формой маскировки:
   банк правил ADR-0404 order-dependent падения **не покрывает**.
6. **Гейт расширен** (`tests/unit/test_order_dependent_pollution_gate.py`):
   * 6 новых пар «поллитер → жертва» (импорт `manage` → три log-жертвы;
     `clear()` реестра → контракт метаданных; наполненный реестр → round-trip;
     ранний импорт фасада → legacy-alias);
   * новый статический скан `src/**`: вызовы `extra={...}` с
     **зарезервированным** ключом `LogRecord` (`name`, `filename`, …) —
     ровно тот класс дефектов, который дал 3 падения волны 22. Известные
     места зафиксированы в `KNOWN_RESERVED_EXTRA_SITES` (14 файлов);
     **новое** место → падение гейта, починенное место → запись обязана
     исчезнуть (реестр может только уменьшаться).

## Альтернативы

* **Починить production-код** (`extra={"name": ...}` → `extra={"entity_name":
  ...}`) — отклонено **в этой волне**: правка production-кода вне зоны
  кластера B6 и требует согласования владельца. Дефект реальный (см.
  «Последствия»), зафиксирован гейтом и передан владельцу.
* **Понизить/зафиксировать уровень логгера в каждом из 3 тестов** —
  отклонено: оставляет order-dependence (результат всё ещё зависит от
  чужого импорта) и прячет дефект за точечной настройкой вместо устранения
  причины.
* **`pytest.skip` / `xfail` для 7 падений** — отклонено по правилу банка
  (ADR-0404): order-dependent падения банком **не покрываются**.
* **Ослабить assert'ы** (например, `>= 50` → `>= 0`) — отклонено: тест
  перестаёт проверять контракт.

## Последствия

* Полный прогон `pytest tests/unit` не даёт order-dependent падений
  (7 → 0). Число падений снижается с 7 до 0; pre-existing падения,
  не связанные с загрязнением, в отчёте волны указаны отдельно.
* **Открытый production-дефект (требует владельца).** 14 мест в `src/**`
  вызывают stdlib-логгер с `extra=` и зарезервированным ключом
  (`name`/`filename`). При уровне `DEBUG` (dev-профиль, `settings.logging.level`)
  такой вызов бросает `KeyError` из error-handler'а. Это реальный баг
  production-кода: он не связан с тестами и воспроизводится в dev-профиле
  без всякого pytest. Перечень — `KNOWN_RESERVED_EXTRA_SITES` гейта; фикс —
  переименование ключа (`name` → `entity_name`/`schedule_name`/…). Правка
  не выполнена в этой волне (вне зоны).
* Уровень корневого логгера в тестовой сессии теперь фиксирован
  (уровень, выставленный logging-backend'ом, `INFO`). Тесты, которым нужен
  `DEBUG`, обязаны выставить его сами — это явное требование вместо
  неявной зависимости от порядка импорта.
* Гейт стал дороже: 12 пар «поллитер → жертва» (каждая — отдельный
  процесс pytest) + скан `src/**`. Полный прогон гейта — ~85 с.

## Проверка

```bash
.venv/bin/python -m pytest tests/unit -q -p no:randomly        # 0 падений
.venv/bin/python -m pytest tests/unit/test_order_dependent_pollution_gate.py -q
ruff check tests/unit
```

Гейт падает, если: (а) банк xfail вырос, (б) запись банка указывает на
несуществующий тест, (в) появился файл с маркером
`ADR-0404-ORDER-DEPENDENT`, не зарегистрированный в реестре жертв,
(г) появился новый файл с модульной подменой глобального состояния,
(д) известная пара «поллитер → жертва» снова даёт падения,
(е) в `src/**` появилось новое место с зарезервированным ключом в `extra=`
или запись реестра устарела.

## Связи

* ADR-0404 — диагностика и гейт order-dependent падений (правило банка).
* ADR-0304 — синтаксис `except` (в репозитории используется PEP 758).
* ADR-0372 — `Settings.reload()` перечитывает конфиг **in-place**.
* ADR-0392 — окружение логирования по умолчанию — из профиля.
* `docs/roadmap/PROD_READINESS_GAPS.md` — owner-задачи по optional-зависимостям
  и Temporal-окружению.
