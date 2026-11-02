# ADR-0414 — Модель аудита шагов workflow (волна 23, кластер C4)

* Статус: Accepted (2026-11-02, волна 23, кластер C4 — аудит шагов workflow)
* Cycle: 182 (волна 23)
* Связан с:
  - ADR-0401 (аудит **процессоров** DSL: базовый класс эмитит `audit_event` — только метаданные capability/route/tenant, без значений данных),
  - ADR-0394 (pg-runner: pre-step событие `step_started` с `idempotency_key`, состояния event-log, retry-бюджет),
  - ADR-0398 (пагинация чтения event log'а — полный replay),
  - ADR-0392 (sync-fallback доставки audit-событий из чисто sync-контекста),
  - ADR-0187 / ADR-0190 (канонический `AuditService` и `core.audit.facade`)
* Затрагивает:
  - `src/backend/infrastructure/workflow/pg_runner_internals/step_audit.py` (новый),
  - `src/backend/infrastructure/workflow/pg_runner_internals/__init__.py`,
  - `src/backend/infrastructure/workflow/runner.py`,
  - `docs/roadmap/OWNER_TASKS.md` (§9),
  - `tests/unit/infrastructure/workflow/test_step_audit_wave23.py` (новый)

---

## Контекст

ADR-0401 закрыл долг «`audit_event` объявлен, но никем не потребляется»:
базовый класс процессоров DSL (`src/backend/dsl/engine/processors/base.py`)
эмитит audit-событие шага — **только метаданные** (имя процессора,
capability, route, tenant), **без значений данных**.

Шаги **workflow** в pg-runner остались без аудита:

1. **События шагов не доходят до audit-сервиса.** pg-runner пишет в
   append-only `workflow_events` события `step_started` / `step_finished` /
   `step_failed` — это журнал состояний, а не журнал аудита: unified
   audit-service о шагах workflow не знает ни одной строки. По
   инстанту workflow нельзя построить цепочку «кто, каким шагом, с
   каким исходом что делал» — она есть только в SQL-таблице, которую
   никто не читает как аудит.
2. **Не определено, что считать шагом для аудита.** Instance-level
   события (`created` / `paused` / `resumed` / `cancelled`) — не шаги;
   `branch_taken` / `loop_iter` / `compensated` — не шаги, а элементы
   шага. Без контракта «шаг = …» любая реализация audit была бы
   догадкой, и две реализации в разных кластерах разошлись бы.
3. **Долг зафиксирован как owner-задача.** `docs/roadmap/OWNER_TASKS.md`
   §9 «Step-level audit-события workflow»: «требует владельца — выбор
   модели аудита шагов». Волна 23 закрывает выбор моделью и кодом.

---

## Решение

### 1. Модель «шаг workflow для аудита»

**Шаг** — переход между событиями event log'а `step_started` и
терминальным исходом (`step_finished` / `step_failed` / отмена
workflow'а). Instance-level события шагами не считаются.

На шаг эмитится **два** audit-события:

| Фаза | Событие | Когда |
|---|---|---|
| `started` | `workflow.step.started` | сразу после pre-step события `step_started` (до эффекта шага) |
| `succeeded` | `workflow.step.succeeded` | терминальное событие `step_finished` шага |
| `failed` | `workflow.step.failed` | терминальное событие `step_failed` шага |
| `cancelled` | `workflow.step.cancelled` | workflow отменён, а pending-шаг не был выполнен |

Отмена workflow'а — instance-level событие, но она **терминализирует
шаг**: шаг, который не был выполнен из-за отмены, получает исход
`cancelled` (имя шага берётся из pre-step-дескриптора `describe_next`;
если шаг определить нельзя — события нет: аудитировать нечего).

### 2. Метаданные — и только они

Формат события (`core.audit.facade.emit_audit`) — тот же, что в
ADR-0401 для процессоров:

* `event` — `workflow.step.<фаза>`;
* `actor` / `resource` — `workflow_step:<имя шага>`;
* `action` — `execute`;
* `outcome` — фаза шага (`started` / `succeeded` / `failed` /
  `cancelled`);
* `details` — **только метаданные**:
  `route_id`, `step`, `tenant`, `attempt`, `outcome`, `duration_ms`,
  `capability` (`audit.write`), `workflow_id` (UUID инстанса).

Значения данных шага и payload шага (`exchange`, `result`, `error`
текст, тело шага) в событие **не попадают** — тот же принцип «без
данных», что в ADR-0401: audit-лог не должен становиться копией
бизнес-данных.

### 3. Идемпотентность

Событие старта эмитится **один раз** на пару (инстанс, шаг, попытка).
Признак «старт уже зафиксирован» — событие `step_started` с тем же
`idempotency_key` в event log'е (ключ детерминирован:
`sha256(instance|step|attempt)`, ADR-0394). Поэтому повторный запуск
шага (переpickup инстанста другим worker'ом) событие старта **не
дублирует** — дедупликация переживает перезапуск процесса, потому что
источник истины — event log, а не память runner'а.

Терминальное событие дедуплицируется симметрично (по `idempotency_key`
терминального события либо по паре «имя шага + номер попытки»).

### 4. Гейт включения

Аудит шагов работает, только если роут **объявил** capability
`audit.write` (проверка декларации в capability-gate, не runtime-гейт
авторизации: событие пишет runner, а не пользовательский агент).
Без декларации — событий нет. Это ровно тот же opt-in-механизм, что
`audit_event` у процессоров в ADR-0401: роут решает, что его шаги
аудируются.

### 5. Точки интеграции

* `pg_runner_internals/step_audit.py` — модель и эмиссия
  (`emit_step_audit`, `step_audit_enabled`, `step_start_logged`,
  `step_terminal_logged`); вызов unified audit-сервиса — через
  `core.audit.facade.emit_audit` (sync-fallback доставки — ADR-0392).
* `runner.py::_run_step` — эмиссия `started` (после pre-step события) и
  терминального исхода (после append'а событий executor'а);
  `runner.py::_finalize_cancelled` — исход `cancelled`.
* Порядок чтения event log'а в `_run_step` изменён: события читаются
  **до** проверки отмены — иначе отменённый шаг нельзя назвать. Число
  обращений к БД не изменилось (`_write_snapshot` читал те же события).

---

## Альтернативы (отклонённые)

* **Аудитить instance-level события (`created` / `paused` / `cancelled`)
  как шаги.** Отклонено: шаг — единица исполнения, а не жизни инстанса;
  иначе «шаг workflow» и «workflow» смешиваются, а объём событий
  растает без пользы.
* **Эмитить одно событие на шаг (только терминальный исход).**
  Отклонено: без события старта нельзя отличить «шаг не начался» от
  «шаг начался и упал» — именно этот вопрос закрывает аудит
  инцидентов.
* **Отдельный audit-сервис workflow'ов.** Отклонено: дублирование
  инфраструктуры; unified audit-сервис уже умеет доставку из
  sync-контекста (ADR-0392) и формат метаданных (ADR-0401).
* **Аудит на стороне executor'а (DSL-процессоры).** Отклонено: у
  executor'а нет ни номера попытки, ни tenant'а инстанса, ни знания о
  key идемпотентности; кроме того, события executor'а — это шаги
  *спеки*, а не шаги *инстанса* (одна спека обслуживает много
  инстансов).
* **Runtime capability-гейт вместо проверки декларации.** Отклонено:
  гейт спрашивает «может ли этот principal», а вопрос здесь другой —
  «обязан ли роут аудировать свои шаги». Декларация — статический
  контракт роута (`route.toml` → `RouteLoader` → capability-gate).
* **In-memory дедупликация в runner'е.** Отклонено: теряется при
  перезапуске процесса — источник истины должен быть event log.

---

## Последствия

**Положительные:**

* У инстанса workflow появился журнал исполнения шагов в unified
  audit-service: «роут → шаг → попытка → исход → длительность», без
  данных шага.
* Модель едина с аудитом процессоров (ADR-0401): тот же формат
  метаданных, тот же принцип «без данных», тот же opt-in-гейт.
* Идемпотентность не зависит от памяти процесса.

**Ограничения (потолок решения):**

* **Только pg-runner.** Temporal-backend (production-путь) шаги не
  аудирует — у него своя history-модель; её аудит — отдельная задача
  (ADR не закрывает Temporal-шаги).
* **Роут без декларации `audit.write` не аудируется вовсе.** Это
  осознанный opt-in (как `audit_event` у процессоров): чтобы шаги
  аудировались, capability нужно объявить в `route.toml`.
* **Дедупликация по `idempotency_key` переживает DLQ-replay.**
  Admin-replay сбрасывает счётчик попыток (`attempts_reset`), поэтому
  новая попытка получает тот же ключ, что и прежняя, — событие старта
  для неё не эмитится. Терминальное событие при этом эмитится.
* **Отменённый шаг аудируется, только если его имя известно**
  (`describe_next`); для экзотических executor'ов без pre-step
  протокола событие старта не эмитится, терминальное — эмитится.

**Миграции:** не требуются (append-only журнал, новых таблиц нет).

---

## Проверка

* `tests/unit/infrastructure/workflow/test_step_audit_wave23.py` —
  8 тестов: события `started` + `succeeded` с полными метаданными;
  `failed`; `cancelled`; отсутствие данных шага в событии;
  отсутствие дубля события старта при повторном запуске; отсутствие
  событий без декларации `audit.write`; `step_audit_enabled` по
  декларации; неизвестная фаза не эмитится (падало → зелёное).
* Регресс: `tests/unit/infrastructure/workflow/` +
  `tests/unit/core/workflow/` — 358 passed, 5 skipped.
* Гейты: `ruff`; `tools/config_audit.py --scope orphans` → 0;
  `tools/check_layers.py --strict` (baseline 41 — без новых нарушений);
  `tools/checks/mypy_budget.py`.

---

## Открытое (owner-задачи)

1. **Аудит шагов Temporal-backend'а** — production-путь не покрыт
   (у Temporal своя history-модель). Критерий приёмки: те же фазы
   (`started` / `succeeded` / `failed` / `cancelled`) и тот же формат
   метаданных в audit-событиях Temporal-шагов. Владелец: K3
   DSL+Workflow.
2. **Декларация `audit.write` в роутах с workflow** — без неё шаги не
   аудируются. Критерий приёмки: в `routes/*/route.toml` роутов с
   workflow-спеками объявлена `audit.write`, и в unified audit-service
   видны события их шагов. Владелец: авторы роутов + SRE.
3. **Выгрузка audit-событий шагов в ClickHouse** — audit-service
   пишет через `ClickHouseAuditService`; если он выключен флагом
   `audit_clickhouse_enabled`, события не сохраняются. Критерий
   приёмки: в проде флаг включён и события `workflow.step.*` читаются
   в ClickHouse. Владелец: SRE.

---

## Связи

* ADR-0401 — аудит процессоров DSL (образец формата метаданных и
  принципа «без данных»).
* ADR-0394 — `idempotency_key` шага (основа дедупликации) и
  pre-step событие `step_started`.
* ADR-0398 — пагинация чтения event log'а (полный replay перед
  дедупликацией).
* ADR-0392 — sync-fallback доставки audit-событий из sync-контекста.
* ADR-0187 / ADR-0190 — канонический `AuditService` и `core.audit.facade`.
* `docs/roadmap/OWNER_TASKS.md` §9 — закрытая этим ADR позиция
  «Step-level audit-события workflow».
