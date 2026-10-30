# ADR-0398 — Пагинация event-log, семантика sub_flow, retry-бюджет и build-time резолв activity

* Статус: Accepted (2026-10-30, волна 20, кластер W1 — workflow)
* Автор: coder-агент, кластер W1
* Связи: ADR-031 (pg-runner), ADR-0394 (состояния PG-runner, lease, идемпотентность),
  ADR-0395 (декларации workflow, worker-регистрация), ADR-0396 (компенсации и time-budget),
  ADR-0397 (эргономика DSL)

---

## Контекст

Ре-аудит кластера W1 (воркфлоу) нашёл семь дефектов pg-runner'а и DSL-компилятора:

1. **[critical] Обрезка event-log.** `WorkflowEventStore.read_events` читает
   `LIMIT :limit` (по умолчанию 1000), а runner вызывал её **без пагинации**
   (`runner.py`, `_run_step` и `_write_snapshot`). Replay находил последний
   `snapshotted` только в пределах первой тысячи событий; при более длинном
   логе состояние откатывалось к старому snapshot'у, и уже выполненные шаги
   исполнялись повторно (дубли эффектов).
2. **[critical] `sub_flow` не порождает child.** `executor/sub_flow_mixin.py`
   эмитил только событие `sub_spawned` (без `child_workflow_id`), событие
   `sub_completed` не producer'ится нигде, `state.py` его не читает. Родитель
   навсегда оставался в статусе `running`, а шаг переисполнялся на каждом
   backup-poll (30 с).
3. **[high] Admin-retry не сбрасывает retry-бюджет.** `admin_workflows/facade.py`
   менял только статус инстанса. Счётчик падений в event log'е оставался
   (`next_attempt = attempts + 1`), поэтому workflow с `attempts=11` падал
   снова, не выполнив ни одного шага — восстановить его было нельзя.
4. **[high] `for_each` теряет результаты элементов.** `control_flow_mixin.py`
   делал `final_body.update(r)` для каждого item — в exchange попадали только
   значения последнего элемента (3 item'а → `{'current_item': 3, 'out': 'A'}`).
5. **[high] Build-time резолв activity в проде выключен.**
   `setup_infra/lifecycle.py` вызывал `collect_activities(declarations)` без
   `validate=True`: неизвестные activity-имена молча регистрировались как
   activity-обёртки. 13 из 14 YAML-воркфлоу репозитория давали Unknown
   activity (`receive_dataset`, `consolidate_results`, `kyc_check`, …);
   резолвился только `credit_assessment`.
6. **[medium] Activity sensor-предиката не регистрировалась.**
   `_iter_activity_specs` не знал про `SensorDeclaration`, хотя
   `compile_sensor_step` вызывает предикат через `execute_activity` → worker
   падал с `ActivityNotRegisteredError`.
7. **[high] BPMN-ветки gateway не исполнялись.** Импортёр клал в ветку
   маркер `{"bpmn_target": target_id}`, а `compiler/gateways.py` маркеры
   игнорировал → ветка = 0 действий; target оставался top-level шагом и
   выполнялся всегда. Условие `${x>=5}` не парсится simpleeval → всегда
   `False`.

## Решение

### 1. Пагинация event-log (`infrastructure/workflow/runner.py`)

* В `RunnerConfig` добавлен `event_page_size` (по умолчанию 1000).
* Runner читает лог **постранично** новым методом `_read_all_events()`:
  цикл `read_events(after_seq=…, limit=page_size)` до пустой страницы,
  с защитой от бесконечного цикла (курсор обязан двигаться). Метод
  используется и в `_run_step` (replay), и в `_write_snapshot` (state для
  snapshot'а). Реальный `WorkflowEventStore` не менялся — он уже умеет
  `after_seq`/`limit`.

### 2. `sub_flow` — fail-fast (`executor/sub_flow_mixin.py`)

* Spawn дочернего workflow требует внешнего оркестратора (Temporal), поэтому
  в pg-runner шаг завершается **терминальным FAILED** с явным сообщением
  «sub_flow в pg-runner не поддерживается … Используйте TemporalWorkflowBackend»
  и событием `step_failed` (`reason="sub_flow_unsupported"` /
  `"missing_workflow_name"`). Событие `sub_spawned` больше не эмитится.
* Константа `StepOutcome.SUB_SPAWNED` сохранена (публичный API runner'а).

### 3. Retry-бюджет при admin-retry

* `admin_workflows/facade.py::retry_workflow` пишет в event log событие
  `resumed` с payload `{"reason": "admin_retry", "attempts_reset": true}`
  **перед** переводом инстанса в `pending`.
* `WorkflowState._apply` для `resumed` обнуляет `attempts`, если payload
  содержит `attempts_reset`. Новый тип события не вводился: `workflow_events.
  event_type` — нативный PG-enum, добавление значения потребовало бы
  Alembic-миграции (вне зоны кластера).

### 4. `for_each` — per-item результаты (`executor/control_flow_mixin.py`)

* Для каждого item'а собирается собственный body (для `parallel` — результат
  task'а, для `sequential` — снимок накопленного body после item'а).
* Список кладётся в exchange под ключом `for_each_results` → попадает в
  `step_finished`-payload и в `exchange_snapshot` (то есть переживает шаг и
  сохраняется в snapshot'е). Контракт `out` не сломан: последнее значение
  по-прежнему видно в exchange.

### 5. Build-time резолв activity

* `setup_infra/lifecycle.py::_build_temporal_activities` вызывает
  `collect_activities(declarations, validate=True)`. Неизвестные имена
  перечисляются в `UnknownActivityError` (список имён + preview известных
  actions) → worker не поднимается (fail-closed, как и задумано комментарием
  в коде), а падает не в рантайме с `ActivityNotRegisteredError`.
* Activity-имена в поставляемых шаблонах `dsl/workflow/templates/*.workflow.yaml`
  переименованы в зарегистрированные actions ядра (аргументы приведены к
  сигнатурам соответствующих методов сервисов).

### 6. Sensor-предикат (`dsl/workflow/compiler/activity_bridge.py`)

* `_iter_activity_specs` знает про `SensorDeclaration` и возвращает
  `(decl.predicate, ())` — предикат регистрируется как activity и проходит
  build-time валидацию.

### 7. BPMN gateway (`dsl/workflow/bpmn_importer.py`, `compiler/gateways.py`)

* Импортёр строит **цепочки веток**: от target'а flow'ами без условия до
  следующего gateway/endEvent. Задачи ветки становятся
  `ActivityDeclaration` внутри `GatewaySpec.branches[].steps` и **исключаются**
  из top-level шагов (иначе они выполнялись бы всегда).
* Узлы, встречающиеся сразу в нескольких ветках (join-узлы), остаются
  top-level — иначе они выполнились бы по разу в каждой ветке.
* `compiler/gateways.py::_normalize_condition` снимает BPMN-обёртку
  `${...}` (как целиком, так и вокруг одиночного идентификатора:
  `${score} >= 700` → `score >= 700`), после чего условие вычисляется
  simpleeval (сравнения поддерживаются штатно).

## Альтернативы

* **Читать весь лог одним SELECT'ом без `LIMIT`.** Отклонено: лог растёт
  линейно по числу шагов/сигналов; пагинация по `after_seq` — штатный
  cursor-механизм таблицы `workflow_events` (индекс `workflow_id, id`).
* **Реализовать spawn child-workflow в pg-runner.** Отклонено: spawn
  требует внешнего оркестратора (Temporal) — pg-runner не умеет создавать
  дочерний инстанс и получать `sub_completed`. Fail-fast честнее «висящего»
  workflow.
* **Новый тип события `retried` в `WorkflowEventType`.** Отклонено:
  `workflow_events.event_type` — нативный PG-enum; новое значение требует
  Alembic-миграции (`ALTER TYPE … ADD VALUE`), а миграции — вне зоны
  кластера. Переиспользовано существующее `resumed` с явным флагом в payload.
* **Валидировать activity-имена только в dev-профиле.** Отклонено: именно
  в проде отсутствие валидации приводило к `ActivityNotRegisteredError` в
  рантайме; fail-fast на старте worker'а дешевле.
* **Оставить BPMN-таргеты top-level-шагами.** Отклонено: это и есть дефект
  (шаг выполняется вне зависимости от выбранной ветки).

## Последствия

* **Позитивные**: replay больше не откатывает состояние на длинных логах;
  `sub_flow` даёт понятную ошибку вместо бесконечного requeue; admin-retry
  реально восстанавливает workflow; `for_each` отдаёт все результаты;
  неизвестные activity-имена ловятся на старте worker'а; sensor-шаги
  работают; BPMN-ветки реально исполняются, а условия считаются.
* **Издержки**: чтение лога — N+1 запросов на страницу (обычно 1–2);
  `_read_all_events` держит в памяти весь лог инстанса (потолок — десятки
  тысяч событий на инстанс; апгрейд при необходимости — стриминг fold'а
  прямо в SQL).
* **Поведенческий риск**: `validate=True` включает fail-closed старт
  Temporal-worker'а. Три YAML-декларации расширения
  `extensions/credit_pipeline/workflows/*` ссылаются на несуществующие
  activity-имена (17 имён) — их нельзя починить в кластере W1 (бизнес-логика
  расширений). До их правки включение `workflow_use_temporal=true` в
  окружении с расширением credit_pipeline приведёт к отказу старта worker'а
  с понятным списком имён. Флаг `workflow_use_temporal` default-OFF, поэтому
  default-конфигурация не затронута.
* **Совместимость**: activity-имена в `dsl/workflow/templates/*.workflow.yaml`
  изменены — шаблоны перестают быть «учебными» и становятся рабочими;
  два существующих теста, кодировавших дефект (неизвестное имя в шаблоне,
  синтетическое activity `orders.create` в worker-тесте), обновлены.

## Проверка

* `tests/unit/infrastructure/workflow/test_pg_runner_wave20.py` — пагинация
  (>1000 событий → replay не переисполняет шаги), fail-fast `sub_flow`,
  per-item результаты `for_each`, обнуление retry-бюджета.
* `tests/unit/entrypoints/api/v1/test_admin_workflows_retry_budget.py` —
  admin-retry сбрасывает бюджет; терминальный статус отвергается (409).
* `tests/unit/dsl/workflow/test_wave20_activities_and_bpmn.py` — build-time
  валидация и список неизвестных имён, резолв всех поставляемых шаблонов,
  регистрация sensor-предиката, развёртывание BPMN-веток, вычисление
  условий `${score} >= 700` / `${x>=5}`.
* `tools/config_audit.py --scope orphans` → 0; `tools/check_layers.py --strict`
  → 41 (baseline; моих файлов в списке нет); `tools/check_docstrings.py src
  --max-allowed 0` → 0.
* Pre-existing падения (не связаны с кластером W1, воспроизводятся и без
  правок волны 20): `tests/unit/infrastructure/workflow/test_lite_temporal_backend.py`
  (7 ошибок фикстуры — `temporalio.testing` недоступен в окружении),
  `tests/unit/infrastructure/workflow/test_temporal_otel_interceptor.py` (2),
  `tests/unit/infrastructure/workflow/versioning/test_worker_versioning.py` (1),
  `tests/unit/core/workflow/test_factory.py` (1),
  `tests/unit/infrastructure/workflow/test_replay_registry_cycle33.py` (1 ошибка).

## Связи

ADR-031, ADR-0394, ADR-0395, ADR-0396, ADR-0397.
