# ADR-0394 — PG-runner: транзиции состояний, payload-контракт, lease и отмена

* Статус: Accepted (2026-10-29, волна 19, кластер A)
* Автор: coder-агент, кластер A
* Связи: ADR-031 (pg-runner), ADR-045 (Wave D.1 pg-runner backend),
  ADR-0396 (Saga-компенсации в pg-runner), ADR-0291 (polling-backoff)

---

## Контекст

Волна 19 нашла в ядре PG-runner (`src/backend/infrastructure/workflow/`) кластер
из 8 дефектов проб ревью:

1. **Потеря данных между этапами.** Событие `created` не несли вход workflow'а
   в `exchange_snapshot`; результат шага ехал в payload под ключом `"output"`,
   а фолдер читал `"exchange"`; `StepResult.output_state` не сохранялся
   runner'ом. Первый процессор получал `{}` вместо `{"seed": 7}`.
2. **Падение этапа никогда не давало FAILED.** catch-all в executor'е всегда
   возвращал `PAUSE`; `WorkflowSpec.max_attempts` не проверялся; payload
   `step_failed` без ключа `attempt` не увеличивал `state.attempts` — бесконечный
   retry в статусе `paused` (`attempts` после 5 падений = 0).
3. **Отмена не работала.** `cancel_workflow` переводил инстанс в `cancelling`,
   runner терминальными считал только `succeeded/failed/cancelled` — шаг всё
   равно исполнялся, инстанст навсегда оставался в `cancelling` без `finished_at`.
4. **Branch-шаг зацикливался.** `_exec_branch` эмитил только `branch_taken`;
   `_apply` его не инкрементит → 5 `branch_taken` подряд, `s2` не выполнялся,
   `current_step` навсегда = 1.
5. **Wait-шаг не завершался.** Всегда `PAUSE` с `now + duration_s`; дедлайн не
   сохранялся, курсор не двигался (`created,paused,paused,paused`).
6. **CONTINUE-reenqueue терялся.** id клался в очередь, пока он ещё был в
   `_active_executions`; `_dispatch_loop` выбрасывал такой элемент → следующий
   шаг ждал backup-poll (30 с) вместо немедленного продолжения.
7. **Lease-лок не защищал от двойного исполнения.** `try_lock` возвращал `True`,
   даже если `UPDATE workflow_instances` не обновил ни одной строки (`rowcount`
   игнорировался); advisory-lock — xact-scope.
8. **Lease не продлевался.** TTL 120 с (`RunnerConfig.lock_ttl_s`) меньше
   дефолтного таймаута шага 300 с → backup-poll + `locked_until < now`
   подхватывали инстанст повторно и дублировали побочные эффекты.

Дополнительно (дефекты, зафиксированные кластером C как «вне зоны», но
файлы — в зоне кластера A):

9. **Идемпотентность ретраев/рестарта.** События писались **после** выполнения
   шага: падение между эффектом шага и append'ом события приводило к
   повторному исполнению шага при resume без отметки в логе.
10. **`WorkflowEventStore.snapshot()` не вызывался нигде** → колонка
    `workflow_instances.snapshot_state` всегда оставалась NULL (admin-API
    отдавал `result=None`), событие `snapshotted` не писалось, и replay
    event log'а шёл с самого начала.

## Решение

### 1. Единый payload-контракт событий

| Событие | Payload |
|---|---|
| `created` | `workflow_name`, `route_id`, `input` (вход workflow'а) |
| `step_started` | `cursor`, `attempt`, `idempotency_key` |
| `step_finished` | `next_step`, `exchange` (результат шага), `attempt`, `idempotency_key` |
| `step_failed` | `error`, `attempt`, `reason` |
| `branch_taken` | `chosen`, `branch`, `branch_name` |
| `paused` | `next_attempt_at`, `wait_deadline`, `wait_step` |
| `snapshotted` | `at_seq`, `state` (дамп materialized state) |

* Результат шага едет **только** под ключом `exchange`. Фолдер читает `exchange`,
  а для событий, записанных до ADR-0394, оставлен fallback на legacy-ключ
  `output` (`pg_runner_internals/state.py`).
* `created` кладёт `input` в `exchange_snapshot` (служебные `__`-ключи —
  `__workflow_id`, `__task_queue` и т. п. — отбрасываются, в процессоры не
  попадают).
* Runner применяет каждое appended-событие к in-memory state
  (`WorkflowState.apply_event`) — state не расходится с event log'ом; после
  шага `output_state` мержится в state и сохраняется в snapshot (см. п. 8).
* Событие `snapshotted` несёт сам дамп состояния (`payload.state`) —
  иначе replay из snapshot'а восстанавливал бы пустой state (потеря данных
  при compaction event log'а).

### 2. FAILED вместо бесконечного PAUSE

* Номер попытки считается один раз на шаг: `next_attempt(state) = state.attempts + 1`
  и едет в `step_started`/`step_failed`; фолдер увеличивает `state.attempts`
  по событию `step_failed` — по явному `attempt` и по умолчанию (legacy-события
  без ключа). Событие `step_started` счётчик **не** трогает: `attempts` =
  число зафиксированных падений (см. п. 7).
* Executor возвращает `FAILED` c `reason="max_attempts_exceeded"`, когда
  `attempt >= WorkflowSpec.max_attempts`; иначе — `PAUSE` (retry через
  backoff runner'а).
* Runner дублирует проверку как safety-net для не-DSL executor'ов:
  `result.max_attempts` (из спецификации) → `RunnerConfig.max_attempts_default`
  (fallback). При исчерпании бюджета — `update_status(failed, error=...)`.
* Backoff считается от номера попытки: первое падение — `retry_base_delay_s`,
  далее — экспонента с jitter.

### 3. Отмена

* `cancelling` обрабатывается в runner'е **до** `execute_next`: пишется событие
  `cancelled`, статус переводится в `cancelled` (`finished_at` проставляется
  `update_status`), шаги не исполняются.
* `WorkflowInstanceStore.list_pending` включает `cancelling` — backup-poll
  подхватывает отменённый инстанс. Промежуточная задержка отмены — не более
  одного backup-poll интервала (30 с) либо ближайшего LISTEN-wakeup'а.
* `cancelled` — терминальный статус: повторный pickup ничего не делает.

### 4. Branch и Wait

* `_exec_branch` завершается событием `step_finished` (`next_step = cursor + 1`,
  `exchange` = тело ветки) — курсор двигается, `s2` выполняется.
* Wait-шаг фиксирует дедлайн в состоянии (`WorkflowState.wait_deadlines`,
  ключ — имя шага, значение — ISO-8601). Первый вызов возвращает `PAUSE` с
  дедлайном; последующие возвращают `PAUSE` до того же срока (срок не
  пересчитывается); по достижении срока шаг эмитит `step_finished` и курсор
  двигается. Дедлайн переживает requeue, т. к. лежит в event log'е.

### 5. CONTINUE-reenqueue

* Runner **снимает** id из `_active_executions` **до** re-enqueue: иначе
  `_dispatch_loop` считает элемент дубликатом активной execution'и и выбрасывает
  его (следующий шаг ждал бы backup-poll).
* Lease освобождается **до** re-enqueue: `CONTINUE` не меняет статус инстанса,
  поэтому следующий pickup сразу получает lease. Для остальных исходов lease
  освобождается после обновления статуса.

### 6. Lease: rowcount + heartbeat

* `try_lock` возвращает `False`, если `UPDATE workflow_instances ... SET
  locked_by/locked_until` не обновил ни одной строки (`result.rowcount == 0`) —
  lease, занятый другим worker'ом, больше не выдаётся «вслепую». Advisory-lock
  остаётся как защита от гонки внутри транзакции.
* `renew_lock(workflow_id, worker_id, ttl_s)` продлевает lease (тот же
  `rowcount`-контроль: `False`, если lease уже не наш).
* Runner запускает **heartbeat** на время выполнения шага: продление каждые
  `lock_ttl_s / 3` секунд (не менее 0.1 с). Heartbeat останавливается через
  stop-event (без отмены задачи) до освобождения lease.

### 7. Идемпотентность ретраев и рестарта

* Событие `step_started` пишется **до** выполнения шага: runner запрашивает у
  executor'а описание следующего шага (`DSLStepExecutor.describe_next` →
  `StepDescriptor(name, kind, attempt)`) и сам append'ит `step_started` с
  idempotency-key. Падение между эффектом шага и append'ом результата больше
  не теряется: в логе остаётся «начатая, но не завершённая» попытка.
* `idempotency_key = sha256(instance_id|step_name|attempt)`
  (`runner.idempotency_key`) кладётся в payload `step_started` и
  `step_finished` — повторное исполнение того же шага той же попытки
  распознаётся по одинаковому ключу.
* `state.attempts` теперь = число **зафиксированных падений** (`step_failed`),
  а не число стартов: после падения без `step_failed` повтор получает тот же
  номер попытки и тот же ключ (повтор узнаваем). Счётчик растёт на
  `step_failed` — по явному `attempt` и по умолчанию (legacy-события).
* Executor'ы без `describe_next` (в т.ч. no-op executor воркера) работают в
  прежнем режиме: `step_started` пишет сам executor.

### 8. Snapshot состояния (заполнение `snapshot_state`)

* `WorkflowEventStore.snapshot()` вызывается runner'ом после каждого
  execution: он атомарно пишет колонку `workflow_instances.snapshot_state` и
  событие `snapshotted` в event log. Раньше метод не вызывался нигде →
  `snapshot_state` всегда был NULL, admin-API отдавал `result=None`, а replay
  шёл с начала лога.
* Payload `snapshotted` = `{"at_seq": <seq>, "state": <дамп state>}` —
  согласован с replay: `WorkflowState.replay` находит последний snapshot и
  восстанавливает state из `payload.state` + хвост событий.
* Из `WorkflowInstanceStore` удалён избыточный `update_snapshot` (тот же
  `UPDATE ... snapshot_state` делает `event_store.snapshot()`).

## Альтернативы

* **Поднять TTL lease выше таймаута шага** (например 600 с > 300 с).
  Отклонено как основной вариант: таймаут задаётся per-spec
  (`WorkflowSpec.default_timeout_s`) и может быть больше, а «ожидаемый TTL»
  перестаёт быть параметром, завязанным на реальную длительность шага.
  Heartbeat покрывает любую длительность и не требует знания таймаута;
  TTL 120 с остаётся как «время до обнаружения падения worker'а».
* **Оставить advisory-lock как единственную защиту.** Отклонено: lock
  xact-scope и живёт до конца транзакции — между шагами он не защищает.
  Lease в `workflow_instances` — единственный межшаговый артефакт.
* **Считать `max_attempts` только в runner'е.** Отклонено: runner не знает
  `WorkflowSpec.max_attempts`; бюджет едет из spec'а в `StepResult`, runner
  использует его как safety-net (fallback — `RunnerConfig.max_attempts_default`).
* **Хранить данные между шагами только в `snapshot_state`.** Отклонено: snapshot
  — кэш; источник истины — event log. Данные едут в payload `step_finished`
  (`exchange`), snapshot лишь дублирует их для быстрого чтения.
* **Хранить дедлайн wait'а в `workflow_instances.next_attempt_at`.** Отклонено:
  поле перезаписывается retry-механикой; дедлайн в состоянии переживает
  requeue и виден в replay.

## Последствия

* **Позитивные**: данные между шагами не теряются; падение шага даёт
  терминальный `FAILED` с причиной; отмена финализируется; branch/wait больше не
  зацикливаются; следующий шаг стартует без ожидания backup-poll; двойное
  исполнение шага блокируется lease'ом; долгий шаг не теряет lease; повтор
  шага после падения распознаваем по idempotency-key; `snapshot_state` всегда
  заполнен (admin-API отдаёт результат), replay стартует с последнего
  snapshot'а.
* **Издержки**: heartbeat — один `UPDATE` каждые `lock_ttl_s / 3` секунд на
  активный шаг; на каждый execution — один snapshot (`UPDATE snapshot_state` +
  событие `snapshotted` в логе), т. е. лог растёт на одно событие на шаг;
  `state.wait_deadlines` расширяет формат snapshot.
* **Совместимость**: события, записанные до ADR-0394, читаются корректно
  (fallback на ключ `output`, default-инкремент `attempts` у `step_failed`).
  Новые события используют только `exchange`/`attempt`/`next_step`/
  `idempotency_key`. Изменение семантики `attempts` (счётчик падений, а не
  стартов) влияет на workflow'и, записанные до ADR-0394: их счётчик
  пересчитывается по `step_failed`.
* **Ограничение**: отмена применяется при ближайшем pickup'е (≤ backup-poll
  интервала) — «мягкая» отмена, а не прерывание шага на полпути. Для
  paused-инстанса с будущим `next_attempt_at` отмена применяется после
  наступления этого срока (тот же фильтр `list_pending`). Идемпотентность
  обеспечивается **распознаванием** повтора (ключ + «начатая, но не завершённая»
  попытка), а не автоматическим подавлением эффектов — подавление ответателен
  за шагом (ADR-0396, компенсации).

## Проверка

* `tests/unit/infrastructure/workflow/test_pg_runner_wave19.py` — 19 тестов:
  * вход `created` → `exchange_snapshot` (+ фильтр `__`-ключей);
  * payload-контракт `exchange` (без `output`);
  * сквозной прогон runner'а: «выход шага 1 виден шагу 2»;
  * runner сохраняет `output_state` в snapshot;
  * `attempts` растут, `max_attempts` → `FAILED` (+ `reason`);
  * runner переводит инстанс в `FAILED` при исчерпанном бюджете;
  * `cancelling` → `cancelled` (событие + `finished_at`), шаги не выполняются;
  * branch двигает курсор (`current_step == 1`);
  * wait завершается по дедлайну;
  * `CONTINUE` снимает id из `_active_executions` до re-enqueue;
  * dispatch-loop исполняет re-enqueue без backup-poll;
  * `try_lock` → `False` при `rowcount == 0`, `True` при `rowcount == 1`;
  * `renew_lock` → `False`, когда lease чужой;
  * heartbeat продлевает lease во время долгого шага;
  * `step_started` пишется **до** эффекта шага (порядок событий:
    created → step_started → step_finished → snapshotted);
  * `step_started`/`step_finished` несут детерминированный
    `idempotency_key = sha256(instance_id|step_name|attempt)`;
  * runner пишет snapshot: событие `snapshotted` + `payload.state`, replay из
    snapshot'а восстанавливает тот же state.
* `pytest tests/unit/infrastructure/workflow -q -p no:randomly` — 200 passed,
  5 skipped (без падений). Отдельно устранён order-dependent сбой чужого
  набора: pre-existing тест `test_replay_registry_cycle33.py` делал
  `importlib.reload(core.workflow_registry)` и оставлял в модуле новый
  singleton — из-за этого регистрации соседних тестов уходили в старый
  объект; тест теперь восстанавливает pre-reload singleton.
* `pytest tests/unit/infrastructure/` — 2890 passed; 3 падения вне зоны
  (`database/test_db_wave3_runtime.py` × 2, `messaging/test_dlq_lazy_init.py` × 1) —
  order-dependent, в изоляции проходят, к workflow не относятся.
* `ruff check` по файлам кластера — чисто; `mypy src/backend/infrastructure/workflow/`
  — чисто (по всему `src` — 9 ошибок в чужих файлах, бюджет гейта не проходит).
* `tools/config_audit.py --scope orphans` → 0; `tools/check_layers.py --strict`
  → 41 (baseline, новых нет); `tools/check_docstrings.py src --max-allowed 0`
  → 0 пропусков.

## Связи

ADR-031, ADR-045, ADR-0396, ADR-0291.
