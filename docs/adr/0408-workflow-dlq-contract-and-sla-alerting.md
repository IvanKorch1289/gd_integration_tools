# ADR-0408 — Workflow-DLQ: контракт для исчерпавших попыток шагов + SLA-алертинг (волна 22, кластер B4)

* Статус: Accepted (2026-11-02, волна 22, кластер B4 — workflow-DLQ и SLA-алертинг)
* Cycle: 181 (волна 22)
* Связан с:
  - ADR-0403 (волна 21: удаление мёртвого `SlaTracker`, честная фиксация «workflow-DLQ не реализована»),
  - ADR-0394 (pg-runner: состояния event-log, lease, retry-бюджет `max_attempts`),
  - ADR-0396 (компенсации и бюджет времени workflow — SLA hard-limit как `execution_timeout`),
  - ADR-0399 (workflow-метрики pg-runner),
  - ADR-0284 (матрица слоёв: `infrastructure → services` требует per-ADR)
* Затрагивает:
  - `src/backend/infrastructure/workflow/pg_runner_internals/workflow_dlq.py` (новый),
  - `src/backend/infrastructure/workflow/pg_runner_internals/__init__.py`,
  - `src/backend/infrastructure/workflow/runner.py`,
  - `src/backend/infrastructure/workflow/pg_runner_backend.py`,
  - `src/backend/core/observability/workflow_sla.py` (новый),
  - `src/backend/services/workflows/sla_alerting.py`,
  - `docs/ops/workflow-sla-alerts.md` (новый — alert-рул),
  - `docs/runbooks/hitl-stuck-workflow.md`,
  - `tests/unit/infrastructure/workflow/test_workflow_dlq_wave22.py` (новый),
  - `tests/unit/services/workflows/test_workflow_sla_metric_wave22.py` (новый)

---

## Контекст

Волна 21 (ADR-0403) зафиксировала два открытых долга по workflow:

1. **Workflow-DLQ не реализован.** Исчерпание retry-бюджета шага давало
   терминальный `WorkflowStatus.failed` + метрику
   `record_workflow_status` + текст ошибки в `workflow_instances.error`,
   но **нигде не оставалось** самого исчерпанного шага: разбирать его
   было негде. `PgRunnerWorkflowBackend.replay()` при этом бросает
   `NotImplementedError` — это replay-gate (детерминизм history), а не
   DLQ.
2. **SLA-алертинг мёртв (GAP-WF-4.5).** `SlaTracker` и
   `SlaAlertDispatcher` удалены как неинстанцируемый код, а чистая
   функция `evaluate_sla` не вызывалась нигде в `src/` → метрика
   `workflow_sla_compliance_total` не эмитилась, Grafana-дашборд
   `workflow_sla_compliance.json` и Prometheus-алерты не имели данных.

Дополнительно (pre-existing, вне заявленного долга, но блокировало
работу): `src/backend/infrastructure/workflow/runner.py` не компилировался —
волна 19 (коммит `77b33e0b4`, ADR-0398/0399) вернула Python-2 синтаксис
`except asyncio.CancelledError, Exception:`. Весь pg-runner стек
(`runner`, `executor`, `worker`) не импортировался: unit-тесты падали на
collection.

Фактическое состояние проверено на волну 22: маршрут «шаг исчерпал
попытки → терминальный FAILED» живёт в `runner.py::_apply_outcome`
(ветки `FAILED` и `PAUSE` с `attempts >= max_attempts`); точка решения о
SLA — терминальный переход workflow'а, где известны `created_at`
инстанса и бюджет времени.

---

## Решение

### 1. DLQ-контракт для исчерпанного шага workflow

Новый модуль `src/backend/infrastructure/workflow/pg_runner_internals/workflow_dlq.py`:

* `build_exhausted_step_envelope(...)` — собирает обычный
  `DLQEnvelope` (`infrastructure/messaging/dlq_base.py`) с
  `transport="workflow"`:
  * `route_id`, `tenant_id` — из строки workflow-инстанса;
  * `step`, `attempts`, `max_attempts` — по исчерпавшемуся шагу;
  * `reason` — `DLQReason.RETRIES_EXHAUSTED`;
  * `metadata.payload_keys` — **имена** ключей входного payload'а;
  * `original_payload=None` — **значения данных workflow в DLQ не
    попадают** (DLQ — сигнал о потерянном шаге, а не его архив);
* `WorkflowDLQPublisher` — публикация через canonical `DLQWriter`
  (тот же контракт, что у HTTP/SOAP/gRPC-транспортов):
  * **идемпотентность**: `dlq_id` детерминирован (`sha256(instance|step|attempt)`
    — тот же ключ идемпотентности шага, что в event log'е), поэтому
    повторный запуск того же шага не создаёт вторую запись
    (`InboxDLQWriter` → `ON CONFLICT (dlq_id) DO NOTHING`, плюс
    in-process дедупликация publisher'а);
  * **fail-loud**: без writer'а — warning-лог + метрика
    `workflow_dlq_publish_total{status="no_writer"}`; ошибка записи —
    `status="error"`; workflow при этом не падает.

* **Переигровка (вторая половина контракта).** ADR-0403 §Открытое
  спрашивал: «что переигровывается, где хранится, кто разбирает».
  Ответ волны 22: переигровывается **исчерпанный шаг** — тот самый,
  который лежит в DLQ под transport'ом `workflow`.
  `PgRunnerWorkflowBackend.replay()` (ветка `NotImplementedError`
  заменена реализацией, ADR-0408) принимает JSON DLQ-записи
  (`{"workflow_id": ..., "step": ..., "attempts": ...}`) и:
  1) пишет событие `resumed` с `attempts_reset=True` (сброс
     retry-бюджета — иначе следующая попытка сразу превысила бы
     `max_attempts`, ADR-0398);
  2) переводит инстанс в `pending` — runner подхватывает его и
     исполняет шаг заново;
  3) fail-loud: нечитаемая запись → `ValueError`, неизвестный
     инстанс → `KeyError`, терминальный статус (`succeeded`/
     `cancelled`) → `ValueError` («переигровывать нечего»).
  Temporal-совместимый replay history pg-runner по-прежнему не
  поддерживает (backend deprecated).

Точка подключения — `runner.py`: `DurableWorkflowRunner` получил
`dlq_writer` (конструктор) и `set_dlq_writer()` (DI-мост, как у
`CDCClient`). Публикация происходит в двух ветках терминального FAILED
(`FAILED` с исчерпанным бюджетом и `PAUSE` с `attempts >=
max_attempts`). Writer по умолчанию — PG-`dlq_inbox` (тот же
`InboxDLQWriter`, что у outbox-DLQ: pg-runner и DLQ живут в одной
PostgreSQL); он подставляется лениво, поэтому контракт работает без
правок composition root.

### 2. SLA-алертинг: метрика + alert-рул (GAP-WF-4.5 закрыт)

* `src/backend/core/observability/workflow_sla.py` — единственный
  источник определения счётчиков (core, чтобы `infrastructure` не тянул
  `services`, а `services` не зависел от `infrastructure`):
  `workflow_sla_compliance_total{level=none|soft|hard}` и
  `workflow_dlq_publish_total{status}`; чистая классификация
  `classify_sla_breach(...)`.
* `services/workflows/sla_alerting.py` — `evaluate_sla` теперь
  делегирует классификацию и эмиссию метрики в core (без дублей
  определения счётчика); `SlaBreachLevel` — алиас общего enum'а.
* **Рантайм-путь**: `runner.py::_record_sla_compliance` оценивает SLA на
  каждом терминальном переходе workflow'а (`succeeded` / `failed`).
  Бюджет времени: `__sla_hard_limit_s` → `__execution_timeout_s`
  (ADR-0396: `execution_timeout` = SLA hard-limit) → `run_timeout_s`
  спеки workflow'а из реестра workflow'ов. Без бюджета метрика не
  растёт (нечего оценивать). Soft-лимит (`__sla_soft_limit_s`)
  используется, если он задан.
* **Alert-рул**: `docs/ops/workflow-sla-alerts.md` — Prometheus/alertmanager
  правила (нарушение SLA, деградация compliance, «DLQ не настроен»),
  порог нарушения — бюджет времени workflow'а, согласованный с SLO
  роутов (`route.toml::slo.timeout_ms`), агрегированный порог — error
  budget 5 % (SLO-цель 95 %).
* Честная оговорка: **эскалация email/Slack по-прежнему не
  реализована** — канала эскалации в репозитории нет. Уведомление о
  нарушении приходит через Prometheus-алерт; сам трекер (`SlaTracker`)
  не возвращался.

### 3. Фикс пре-реквизита: `runner.py` не компилировался

Волна 19 оставила Python-2 синтаксис в `except`; исправлено на
`except (asyncio.CancelledError, Exception):` — без этого невозможны ни
DLQ-контракт, ни SLA-оценка (модуль не импортируется).

### 4. Честная фиксация в коде и документации

* `pg_runner_backend.py`: раздел «Workflow-DLQ» переписан — DLQ для
  исчерпанных шагов **реализован** (ADR-0408); `replay()` реализован
  как переигровка исчерпанного шага по DLQ-записи (см. §1) — это
  различие фиксируется в docstring'е и в тексте ошибок.
* `docs/runbooks/hitl-stuck-workflow.md` приведён к фактической
  семантике: терминальный `FAILED` + запись в DLQ + переигровка шага +
  метрика SLA + alert-рул; формулировка «SLA-алертинг не реализован»
  заменена на «эскалация email/Slack не реализована, детекция — по
  метрике и алерту».

---

## Альтернативы

* **Отдельная очередь `workflow_dlq` (своя таблица/топик).**
  Отклонено: ADR-0403 фиксирует, что переигровывать шаг нечем
  (`workflow_events` — append-only event log, а не очередь
  недоставленных сообщений). Задача кластера — **сигнал** о
  потерянном шаге, а не архив и не механизм replay; DLQ-инфраструктура
  (admin-API `/api/v1/admin/dlq/*`, cleanup, retention) уже существует
  и дублировать её — долг.
* **Вернуть `SlaTracker` + dispatcher.** Отклонено (ADR-0403):
  инстанцировать его негде, канала эскалации нет. Оценка SLA не
  требует фонового трекера — она выполняется в точке терминального
  перехода, где данные и так есть.
* **Удалить `evaluate_sla` и дашборд** (вариант «или» из owner-задачи).
  Отклонено: дашборд `workflow_sla_compliance.json` и описание
  feature-флага — вне зоны кластера; удаление сломало бы чужой
  артефакт.
* **Только алерт-рул без кода.** Отклонено: без эмиссии метрики правило
  не имеет данных — это был бы «тихий зелёный» статус, ровно то, что
  ADR-0403 называл источником ложной уверенности.
* **Новый конфиг-ключ для порога SLA.** Отклонено: конфиг-ключи берутся
  только из существующих моделей (`tools/config_audit.py --scope orphans`
  → 0); порог живёт в существующих настройках SLO роутов.

---

## Последствия

* **pg-runner снова импортируется**: до фикса `runner.py` был сломан с
  волны 19 — unit-тесты workflow'ов падали на collection. Синтаксис
  волны 19 — pre-existing регрессия, устранена попутно (пре-реквизит
  контракта).
* **Метрики SLA/DLQ регистрируются в дефолтном `prometheus_client.REGISTRY`
  явно.** Фабрика `core/utils/metrics_registry.py` создаёт счётчики с
  `registry=None` — в текущей версии prometheus_client такой счётчик
  **не** попадает в дефолтный REGISTRY и не отдаётся на `/metrics`
  (pre-existing долг всего проекта, вне зоны кластера). Явная
  регистрация идемпотентна (дубликат игнорируется) — после исправления
  фабрики её нужно убрать.
* **Значения данных workflow в DLQ не попадают** — только метаданные
  (имена ключей). Это осознанное ограничение: DLQ не архив.
* **Дубликаты в DLQ исключены** по детерминированному `dlq_id`
  (идемпотентность на уровне БД через `ON CONFLICT DO NOTHING`).
* **Семантика `replay()` у pg-runner изменена**: вместо
  `NotImplementedError` — переигровка исчерпанного шага по DLQ-записи.
  Инвариант Sprint 7 «replay() не должен молча возвращаться» сохранён
  (некорректный вход → fail-loud `ValueError`); тест
  `tests/unit/infrastructure/workflow/test_pg_runner_replay_deprecated.py`
  обновлён под новую семантику.
* **Вне зоны кластера (требует владельца):**
  * `docs/runbooks/dlq-replay.md` — утверждает, что workflow-шаги не
    попадают в DLQ (формулировка волны 20 теперь неверна);
  * `docs/workflows/index.md` — раздел «Не реализовано» про workflow-DLQ;
  * `docs/roadmap/PROD_READINESS_GAPS.md` / `OWNER_TASKS.md` — реестр
    owner-задач (GAP-WF-4.5 закрыт кодом);
  * `docs/adr/INDEX.md` — индекс ADR (генерируется отдельно, правилом
    волны запрещено редактировать);
  * `deploy/` — доставка alert-рула в Prometheus (в репозитории нет
    Prometheus rule-файлов; рул приведён в `docs/ops/`).

---

## Проверка

* `tests/unit/infrastructure/workflow/test_workflow_dlq_wave22.py` —
  DLQ-поступление при исчерпании попыток (обе ветки терминального
  FAILED), отсутствие дублей при повторе, состав envelope'а (в том числе
  отсутствие значений данных), поведение без writer'а, DLQ-replay
  (сброс бюджета + возврат в `pending`, fail-loud на мусорных данных)
  (падало → зелёное).
* `tests/unit/services/workflows/test_workflow_sla_metric_wave22.py` —
  метрика SLA при нарушении (`level="hard"`/`"none"`), отсутствие метрики
  без бюджета, эмиссия из чистой функции (падало → зелёное).
* `tests/unit/services/workflows/test_sla_alerting_removed_wave21.py` —
  трекер по-прежнему удалён; docstring фиксирует метрику + alert-рул;
  ADR-0408 закрывает GAP-WF-4.5.
* `tests/unit/infrastructure/workflow/test_pg_runner_backend_dlq_statement.py` —
  `replay()` — replay-gate, не DLQ; DLQ-контракт в docstring модуля.
* Гейты: `ruff`; `tools/config_audit.py --scope orphans` → 0;
  `tools/check_layers.py --strict` (baseline 41 — без новых нарушений);
  `tools/checks/mypy_budget.py` (бюджет 30); `tools/check_docstrings.py`;
  `tools/generate_adr_index.py --check` (ожидаемо требует обновления
  индекса ADR — владелец волны).

---

## Открытое (owner-задачи)

1. **Доставка alert-рула в Prometheus.** В репозитории нет Prometheus
   rule-файлов; рул описан в `docs/ops/workflow-sla-alerts.md`. Владелец:
   K2 (messaging) + SRE.
2. **Подключение `WorkflowFacade` к production-пути** (иначе soft-лимит
   SLA и `SlaPolicy` не доезжают до рантайма). Владелец: K3 DSL+Workflow.
3. **Реестр owner-задач** (`docs/roadmap/PROD_READINESS_GAPS.md`,
   `docs/roadmap/OWNER_TASKS.md`) — обновить статус GAP-WF-4.5 и
   workflow-DLQ. Владелец: roadmap.
4. **Фабрика метрик** (`core/utils/metrics_registry.py`) — счётчики не
   регистрируются в дефолтном REGISTRY (pre-existing долг всего
   проекта). Владелец: K2/SRE.

---

## Связи

* ADR-0403 — удаление мёртвого `SlaTracker` и честная фиксация
  «workflow-DLQ не реализована» (этот ADR закрывает оба пункта).
* ADR-0394 — retry-бюджет `max_attempts` и идемпотентность шага
  (источник ключа `dlq_id`).
* ADR-0396 — SLA hard-limit как `execution_timeout` (бюджет времени
  workflow'а) и компенсации при терминальном FAILED.
* ADR-0399 — workflow-метрики pg-runner (соседний слой наблюдаемости).
* ADR-0284 — матрица слоёв (per-ADR на межслойные импорты).
* `docs/ops/workflow-sla-alerts.md` — alert-рул волны 22.
* `docs/runbooks/hitl-stuck-workflow.md` — runbook (обновлён).
* `docs/roadmap/PROD_READINESS_GAPS.md` — GAP-WF-4.5.
