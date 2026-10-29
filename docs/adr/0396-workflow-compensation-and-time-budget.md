# ADR-0396 — Компенсации Saga в pg-runner-пути и бюджет времени workflow

* Статус: Accepted (2026-10-29, волна 19 повторного аудита вехи «воркфлоу»)
* Автор: coder-агент, кластер C (компенсации и Saga в PG-пути)
* Связи: ADR-0394 (retry-бюджет и lease в pg-runner), ADR-0305
  (deadline-бюджет запроса), ADR-045 (workflow-фасад и capability-гейт),
  ADR-031 (pg-runner как durable-источник истины)

---

## Контекст

Волна 19 повторного аудита вехи «воркфлоу» нашла в кластере
«компенсации и Saga в PG-пути» четыре дефекта:

1. **[high] Компенсации в pg-runner-пути не исполнялись.** `kind="compensate"`
   в `executor/__init__.py` был no-op (`StepResult(CONTINUE, events=[])`), а
   runner при `FAILED` только записывал статус в БД. Откат выполненных
   forward-шагов терялся: saga оставалась с неоткаченными side-effect'ами.
2. **[medium] Docstring'и обещали несуществующее поведение.** `WorkflowStep`
   документировал `compensate` как «выполняется runner'ом при перехода в
   failed», фактически шаг просто пропускался.
3. **[medium] Бюджет времени workflow отсутствовал.** `WorkflowFacade.start`
   по умолчанию передавал `execution_timeout=None`, pg-runner-бэкенд клал
   маркер `__execution_timeout_s` в payload, но никто его не проверял; SLA-
   политика была инертна — `SlaTracker.track()` не имел ни одного
   production-caller'а, runbook `docs/runbooks/hitl-stuck-workflow.md` был
   неисполним.
4. **[medium] `CompensatingDriverWorker` переводил зависшую saga в
   `rolled_back` без исполнения `compensating_actions`** — молчаливая потеря
   отката (дефект описан в `saga_lra.py`).

Дополнительно (вне зоны кластера, см. отчёт): `runner.py` пишет события
*после* исполнения шага (нет idempotency-key и «started»-события до
эффекта), а `WorkflowEventStore.snapshot()` не вызывается нигде — из-за
этого `snapshot_state` всегда `NULL`, и admin-API отдаёт `result=None`.

## Решение

### Компенсации в pg-runner (дефекты 1, 2)

* Новый модуль `src/backend/infrastructure/workflow/executor/compensating.py` —
  каноническая saga-семантика pg-runner, выровненная с Temporal-путём
  (`dsl/workflow/compiler/step_compilers/flow.py`):
  * `build_compensation_plan()` строит план компенсаций для уже выполненных
    forward-шагов в **reverse-порядке** (упавший шаг не компенсируется);
  * маппинг forward→compensate: явный `WorkflowSpec.compensate_map`
    (имя→имя), иначе позиционный fallback (i-й compensate-шаг ↔ i-й
    forward-шаг) — как в Temporal;
  * `execute_compensation()` исполняет цепочку и при `strict_compensate`
    поднимает `CompensationError` с цепочкой исключений: `__cause__` —
    последняя ошибка компенсации, `.original` — исходная ошибка
    forward-шага, `.errors` — все ошибки компенсаций.
* `WorkflowSpec` дополнен полями `compensate_map`, `strict_compensate`,
  `run_timeout_s` (ADR-0394 уже добавил retry-бюджет `max_attempts`).
* `DSLStepExecutor.execute_next()` на **любом терминальном `FAILED`**
  (таймаут процессора, исчерпанный retry-бюджет, неизвестный kind-шага,
  исчерпанный бюджет времени) перед возвратом результата исполняет цепочку
  компенсаций и дописывает событие `compensated` в event-log
  (`status=completed|failed` + список откатанных шагов).
* `compensate`-шаг в **прямом** потоке пропускается (это rollback-действие,
  а не forward-действие): handler отдаёт `CONTINUE` + `step_finished` с
  `skipped="compensation_step"`, чтобы cursor сдвинулся за rollback-шаг.
  Docstring'и `WorkflowStep`/`WorkflowSpec` приведены в соответствие с
  фактическим поведением.
* `CompensatingDriverWorker` больше **не** помечает saga `rolled_back`, если
  остались неисполненные `compensating_actions`: состояние остаётся
  `compensating`, компенсации доигрываются при re-entry
  `SagaLRAProcessor._resume_compensating`. Saga без pending-компенсаций
  по-прежнему фиксируется как `rolled_back`.

### Бюджет времени и SLA (дефект 3)

* `WorkflowFacade` получил опциональные `sla_tracker` и `sla_resolver`:
  * SLA hard-limit используется как `execution_timeout` (если вызывающий не
    задал его явно) — бюджет времени workflow теперь реальный: Temporal
    применяет его нативно, pg-runner — через маркер
    `__execution_timeout_s` в payload'е инстанса;
  * запущенный workflow ставится на `SlaTracker.track()`, после
    `await_completion` — снимается через `untrack()`. SLA-политика перестала
    быть инертной.
* `DSLStepExecutor._check_time_budget()` проверяет бюджет перед каждым
  шагом: `WorkflowSpec.run_timeout_s` → иначе `__execution_timeout_s` из
  payload'а. Исчерпанный бюджет → терминальный `FAILED` с событием
  `step_failed(reason="execution_timeout")` (и компенсациями, как любой
  `FAILED`).

## Альтернативы

* **Оставить `compensate` no-op и ограничиться правкой docstring'ов.**
  Отклонено: дефект high — компенсации не исполнялись вообще, откат
  терялся; правка документации не устраняет потерю side-effect'ов.
* **Перенести компенсации целиком в runner (`runner.py`).** Отклонено: у
  runner'а нет доступа к определениям шагов (spec) и к exchange-контексту;
  исполнить rollback-действия может только executor. Runner остаётся
  оркестратором (см. ADR-0394: retry-бюджет и lease).
* **Вынести компенсации в отдельную БД-очередь (outbox).** Рассмотрено и
  отложено: требует отдельного воркера с доступом к spec'ам маршрутов;
  текущий синхронный откат в executor'е покрывает дефект без новых
  подсистем.
* **Считать бюджет времени только в Temporal (нативный `execution_timeout`).**
  Отклонено: pg-runner — dev/staging/CI-путь, но именно в нём терялись
  компенсации и отсутствовал лимит времени; оставлять путь без бюджета —
  сохранять дефект.
* **Оставить `CompensatingDriverWorker` помечать `rolled_back` всегда.**
  Отклонено: это молчаливая потеря отката (дефект, который ADR-0396 и
  закрывает).

## Последствия

* **Позитивные**: откат в pg-runner исполняется в reverse-порядке и
  фиксируется в event-log событием `compensated`; ошибки компенсаций
  сохраняют цепочку исключений (исходная ошибка + ошибки отката); workflow
  получает реальный лимит времени; SLA-политика мониторится, а не лежит
  мёртвым грузом; зависшая saga больше не помечается откатанной без отката.
* **Издержки**: `WorkflowSpec` получил три новых поля; компенсации
  исполняются в executor'е (дополнительная работа в том же тике runner'а —
  компенсации обязаны быть идемпотентными); `WorkflowFacade` получил два
  опциональных параметра (обратная совместимость сохранена).
* **Совместимость**: `compensate`-шаги в прямом потоке пропускаются, а не
  исполняются — для workflow'ов, где compensate-шаг стоял в `spec.steps`,
  поведение forward-флона не меняется (шаг и раньше был no-op), но теперь
  он же используется как rollback-действие при откате.

## Проверка

* `tests/unit/dsl/engine/processors/test_pg_runner_compensation_wave19.py` —
  reverse-порядок плана компенсаций, позиционный и явный `compensate_map`,
  цепочка исключений (`CompensationError.__cause__`/`.original`/`.errors`),
  исполнение компенсаций executor'ом при `FAILED`, ошибка компенсации в
  `error_message` + событии `compensated`, применение бюджета времени
  (`__execution_timeout_s` и `run_timeout_s`), сохранение pending-компенсаций
  driver'ом.
* `tests/unit/services/workflows/test_workflow_time_budget_wave19.py` —
  SLA hard-limit как `execution_timeout`, приоритет явного таймаута,
  `SlaTracker.track()`/`untrack()` из фасада, отсутствие изменений без SLA.
* `tools/config_audit.py --scope orphans` → 0; `tools/check_layers.py --strict`
  → без новых нарушений (baseline 41); `tools/check_docstrings.py src
  --max-allowed 0` → без новых замечаний.

## Связи

ADR-0394, ADR-0305, ADR-045, ADR-031.
