# ADR-0395 — Модель workflow-деклараций, регистрация Temporal Worker'а и детерминизм

* Статус: Accepted (2026-10-29, волна 19, кластер B)
* Автор: coder-агент, кластер B
* Связи: ADR-045 (Wave D.1 workflow-backend), ADR-0394 (pg-runner state),
  ADR-0396 (компенсации), ADR-035 (feature-флаги)

---

## Контекст

Волна 19 нашла в кластере «Temporal и YAML-декларации» 6 дефектов:

1. **Имена activity из YAML не резолвятся.** `ActivityBridge` проксирует
   вызов в `action_handler_registry.dispatch`; в реестре 124 action'а и
   **0** совпадений с именами шагов. Проба: `KeyError 'consolidate_results'`
   на `src/backend/dsl/workflow/templates/kyc_aml_check.workflow.yaml`.
   Расширения при этом используют идиому route-DSL `call_function('module:fn')`,
   которой в workflow-DSL не было.
2. **YAML-декларации клались в реестр как `WorkflowDeclaration`, а не
   `WorkflowDescriptor`** (`workflow_setup.py`). Admin-trigger читал
   `descriptor.input_schema` → `AttributeError`; MCP-экспорт читал
   `descriptor.tags` → `AttributeError`, проглоченный `try/except` (тихая
   потеря MCP-tool'а).
3. **Worker Temporal регистрировал только 2 activity** (LangGraph
   checkpoint): `bridge._cache` без `collect_activities` → любой
   `workflow.execute_activity` из YAML-декларации падал с
   `ActivityNotRegisteredError`. Дополнительно worker не поднимался
   (feature-flag `workflow_use_temporal` default-OFF) без понятного
   предупреждения.
4. **Перекомпиляция с тем же именем оставляла старый класс**: `emitter.py`
   глотал `ValueError` от `workflow_registry.register` (только DEBUG), а
   post-check `compile_workflows` проверял лишь наличие имени.
5. **Недетерминизм в gateway-компиляторах**: `asyncio.gather` /
   `asyncio.wait` / `create_task`; Temporal-sandbox рестритктует
   `asyncio.wait` (`temporalio/worker/workflow_sandbox/_restrictions.py`),
   а guard `tools/s86_workflow_sandbox_guard.py` об этих API молчал
   («0 violations»).
6. **Переключение движков теряло гарантии и типы**: `factory.py` ловил
   только `RuntimeError` (падение коннекта к кластеру не давало fallback),
   downgrade был тихим; `canonical_json_bytes` (`default=str`) +
   `orjson.loads` теряли `datetime`/`UUID`/`Decimal` — семантика шага
   зависела от движка.

## Решение

### 1. Build-time резолв имён activity + `call_function` в workflow-спеке

* В спеке добавлен шаг `call_function` (`CallFunctionDeclaration`,
  `spec/activity_declarations.py`) с `ref: "module.path:function_name"`,
  `args`, `timeout_s`, `output_key`.
* Нормализация на уровне `WorkflowDeclaration` (`spec/workflow.py`,
  validator `mode="before"`): activity-шаг с именем вида `module:fn`
  автоматически становится `call_function`-шагом. Обратная совместимость
  сохранена — существующие YAML расширений (`type: activity` + `name:
  module:fn`) работают без правок.
* `ActivityBridge` умеет три механизма: зарегистрированное action-имя,
  `call_function`-ссылка (`bridge_call_function`) и внутренние activity
  (`_agent_invoke`, LangGraph checkpoint).
* `resolve_activity_target()` резолвит имя **на build-time** и бросает
  `UnknownActivityError` со списком неизвестных имён и подсказкой
  («зарегистрируйте action либо используйте step `call_function`»).
  `collect_activities(declarations, validate=True)` использует этот резолв.

### 2. В реестр кладётся `WorkflowDescriptor`

* `workflow_setup._register_descriptor()` строит `WorkflowDescriptor`
  (`name`, `description`, `input_schema`, `output_schema`, `max_attempts`,
  `tags`) из декларации и регистрирует его в descriptor-реестре.
  `input_schema=None` — в YAML-спеке схемы входа нет, а `None` по
  контракту означает «любой dict» (admin-trigger валидирует только
  непустую схему).
* В `WorkflowDeclaration` добавлено поле `tags` — MCP-описание tool'а
  получает осмысленные теги, а не пустой кортеж.
* Повторная регистрация заменяет descriptor (hot-reload), а не падает.

### 3. Worker получает все activity

* `setup_infra.lifecycle._build_temporal_activities()` собирает activity
  **всех** шагов скомпилированных деклараций через
  `ActivityBridge.collect_activities()` (плюс checkpoint-обёртки) и
  декорирует их `@activity.defn`.
* Декларации загружаются и компилируются **до** поднятия worker'а
  (`ensure_workflow_declarations_loaded()`): фаза infrastructure идёт
  раньше фазы services, где инициализируется workflow runtime, — без
  этого worker не знал ни workflow-классов, ни activity-функций.
* При выключенном `workflow_use_temporal` worker не поднимается, но
  пишется **WARNING** с описанием последствий (workflow-декларации не
  исполняются Temporal-движком), а не INFO-молчание.

### 4. Перекомпиляция заменяет класс

* `WorkflowRegistry.unregister(name)` — новая операция реестра.
* `compile_workflow` при `ValueError` от `register` делает
  unregister + register: в реестре всегда лежит актуальная версия класса,
  которую видят worker и replay.
* Post-check `compile_workflows` проверяет **identity** класса, а не
  только имя, — stale-регистрация больше не проходит молча.

### 5. Детерминизм gateway-компиляторов

* Join-точки переведены на `temporalio.workflow.wait` (детерминированная
  замена `asyncio.wait`; в sandbox'е `asyncio.wait` рестритктуется).
  `asyncio.gather` / `asyncio.as_completed` / `asyncio.create_task` из
  workflow-кода убраны.
* Победитель OR-ветки выбирается детерминированно: среди завершившихся
  веток — первая успешная **в порядке объявления** (не «первая по
  времени завершения»).
* `tools/s86_workflow_sandbox_guard.py` теперь ловит `asyncio.wait`,
  `asyncio.gather`, `asyncio.as_completed`, `asyncio.create_task`,
  `asyncio.ensure_future` — guard больше не молчит.

### 6. Переключение движков и типовая сохранность payload'ов

* `factory.create_workflow_backend` ловит **любую** ошибку подключения
  (`OSError`, `ConnectionError`, `TimeoutError`, `temporalio` RPCError),
  а не только `RuntimeError`.
* Downgrade Temporal → pg_runner — **degraded-режим**: логируется
  WARNING с перечнем потерянных гарантий (replay / determinism /
  typed-query). Явный `kind="temporal"` не деградирует — ошибка
  пробрасывается (fail-closed). В staging/prod downgrade запрещён по
  политике: оператор обязан поднять кластер или выставить флаг явно;
  автоматическая деградация — только в dev-профилях.
* Data-converter Temporal'а сохраняет богатые типы: значение проходит
  через `to_jsonable` (tagged-dict) и восстанавливается через
  `from_jsonable`; byte-stability canonical-JSON сохраняется.

## Альтернативы

* **Адаптировать потребителей (admin/MCP) под `WorkflowDeclaration`.**
  Отклонено: descriptor-реестр по контракту хранит `WorkflowDescriptor`
  (`input_schema`/`tags`/`max_attempts`), MCP и admin читают именно его;
  «подгонка» потребителей размножила бы duck-typing в двух слоях.
* **Оставить `KeyError` в рантайме activity.** Отклонено: дефект
  проявлялся в рантайме workflow'а (потерянное время + неясная причина);
  build-time резолв даёт ошибку сразу при сборке worker'а.
* **Регистрировать activity «на лету» по имени шага (без bridge).**
  Отклонено: теряется единая точка декорирования и capability-guard.
* **Запретить downgrade Temporal → pg_runner полностью.** Отклонено как
  ломающее деградацию dev-среды; вместо этого downgrade стал явным
  (WARNING + список потерь) и запрещён при явном `kind="temporal"`.
* **Оставить `asyncio.gather` (sandbox его не рестритктует).**
  Отклонено: gather не даёт гарантированного порядка join'а и не
  выражает «дождаться всех» через Temporal-примитив; `workflow.wait`
  — канонический API SDK для этого случая.

## Последствия

* **Позитивные**: YAML-воркфлоу репозитория резолвятся на build-time;
  `module:fn` работает в workflow-DSL; admin-trigger и MCP видят
  корректный descriptor; worker исполняет activity из деклараций;
  перекомпиляция не оставляет stale-класс; порядок событий gateway'ев
  детерминирован; падение коннекта к Temporal больше не роняет процесс
  молча и не теряет типы payload'а.
* **Издержки**: неизвестное имя activity теперь валит сборку worker'а
  (fail-loud) — сбойная YAML-декларация должна быть исправлена, а не
  «поймана» в рантайме; `to_jsonable` добавляет небольшой overhead к
  сериализации payload'ов.
* **Совместимость**: `type: activity` + `name: "module:fn"` продолжает
  работать (нормализуется в `call_function`); обычные action-имена не
  меняются; YAML без `tags` валиден.
* **Ограничение**: `call_function` исполняется в activity-контексте и
  не проходит whitelist-модулей route-DSL — ограничение применяется на
  уровне плагина (`plugin.toml`), а не DSL-процессора.

## Проверка

* `tests/unit/infrastructure/workflow/test_workflow_declaration_bridge.py` —
  11 тестов: нормализация `module:fn`, регистрация `call_function`-
  activity, build-time резолв (action / `module:fn` / неизвестное имя),
  реальные YAML репозитория (`credit_assessment` резолвится,
  `kyc_aml_check` даёт понятную ошибку).
* `tests/unit/infrastructure/workflow/test_workflow_descriptor_registration.py` —
  5 тестов: descriptor вместо декларации, `input_schema`/`tags`,
  `route_id`, hot-reload, auto-load из `EXTENSIONS_DIR`.
* `tests/unit/infrastructure/workflow/test_temporal_worker_activities.py` —
  5 тестов: сбор activity шагов, `collect_activities` в worker-сборке,
  компиляция деклараций, WARNING при выключенном флаге.
* `tests/unit/infrastructure/workflow/test_workflow_recompile_registry.py` —
  4 теста: recompile заменяет класс, post-check ловит stale/отсутствие
  регистрации, `unregister`.
* `tests/unit/infrastructure/workflow/test_workflow_gateway_determinism.py` —
  7 тестов: двукратный запуск → одинаковый порядок событий (AND/OR),
  детерминированный победитель OR, guard ловит `asyncio.wait`/
  `asyncio.gather`, текущие исходники компилятора — 0 violations.
* `tests/unit/infrastructure/workflow/test_workflow_backend_factory.py` —
  6 тестов: fallback на `OSError`/`TimeoutError`, WARNING с потерями,
  fail-closed для `kind="temporal"`, round-trip типов и byte-stability.
* `pytest tests/unit/infrastructure/workflow tests/unit/services/workflows`
  → **310 passed, 5 skipped** (пропуски — pre-existing: API-drift
  temporalio и тяжёлый S180-тест).
* `pytest tests/unit/dsl/workflow tests/unit/plugins/composition/
  test_workflow_setup.py tests/unit/core/workflow` → 402 passed, 6 skipped,
  1 pre-existing order-dependent failure
  (`test_auto_dev_light_picks_lite_temporal` — в изоляции проходит, та же
  картина на HEAD).
* `ruff check` по файлам кластера — чисто; `ruff format` — чисто (кроме
  двух файлов с pre-existing отклонениями: `temporal_worker_runtime.py`
  и `tools/s86_workflow_sandbox_guard.py` — там формат не менялся).
* `tools/config_audit.py --scope orphans` → 0; `tools/check_layers.py
  --strict` → 41 (baseline, новых нет); `tools/check_docstrings.py src
  --max-allowed 0` → 0.

## Связи

ADR-045, ADR-0394, ADR-0396, ADR-035.
