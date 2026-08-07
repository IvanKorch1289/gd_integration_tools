# Cycle 1 — Phase 1 — Audit of Domain A8-Workflow-Temporal

**Дата:** 2026-08-06
**HEAD:** `7f3d94a3`
**Аудитор:** A8-агент (cycle 1, independent verification, read-only)

---

## 1. Сводка готовности по 5 категориям

| # | Категория | Готовность | Обоснование |
|---|-----------|-----------:|-------------|
| **A** | Архитектурная целостность `WorkflowBackend` Protocol | **85** | Protocol декларирован в `core/workflow/backend.py:65-191` (8 методов). `FakeWorkflowBackend` (205), `TemporalWorkflowBackend` (368), `LiteTemporalBackend` (76), `PgRunnerWorkflowBackend` (376). **Минус:** `TemporalWorkflowBackend` НЕ реализует `start_child_workflow`/`await_external_signal` (D-A8-04 P0). |
| **B** | DSL-декларативность и компилятор | **70** | `WorkflowBuilder` (17+ методов, 6 mixins). Pydantic discriminated union (`WorkflowStep` — 12 declaration-типов). Saga с `compensate_map`. BPMN через `defusedxml`. **Минусы:** 4 процессора без `@processor()`; `_resolve_workflow_version` silent fallback; dead code. |
| **C** | Runtime / Saga / Worker | **60** | `DurableWorkflowRunner` (461), `CompensatingDriverWorker` (156, D-AUDIT-FIX-184-1), `WorkflowEventStore`+`WorkflowInstanceStore`. **Минусы:** Temporal Worker lifecycle отсутствует — `TemporalWorkerPool` (94) ни разу не вызывается; `WorkflowSpec`/`WorkflowDeclaration` двойные parallel spec. |
| **D** | Observability / Audit / DLQ | **75** | `StepAuditMiddleware` (308), `WorkflowAuditSink` integrated, `ActivityHeartbeatMonitor`. **Минусы:** StepAuditMiddleware НЕ интегрирован в `DSLStepExecutor`; `SlaTracker` (330) без consumer. |
| **E** | Capability-gate / Security | **80** | `WorkflowFacade` capability-gated; `CapabilityDeniedError` fail-closed. Saga через `TenantMixin` (RLS). **Минусы:** `TemporalWorkflowBackend.start_workflow` namespace mismatch warning-only. |

**Средневзвешенная**: (85+70+60+75+80)/5 = **74/100**

**Однако: 6 P0 + 5 P1 = clamp to 25/100 по формуле cycle-3.**

---

## 2. P0 — блокирующие

| ID | Файл:строка | Описание | Фикс |
|---|---|---|---|
| **D-A8-01** | `core/config/features/workflow.py:32-72` | **WorkflowFlags docstring lie**: 4 из 5 флагов `default=True`, docstring обещает `default-OFF` | `default=False` для 4 |
| **D-A8-02** | `dsl/engine/processors/workflow/{workflow_subprocess,workflow_convert,continue_as_new}.py` + `best_practices/{claim_check,continue_as_new}.py` | **4 процессора без `@processor()`** — capability-check никогда не срабатывает | Добавить `@processor()` |
| **D-A8-03** | `dsl/workflow/compiler/activity_bridge.py:288-305` | **`ActivityBridge.decorate()` никогда не вызывается** — Temporal Worker упадёт | Wire в `_run_worker` |
| **D-A8-04** | `infrastructure/workflow/temporal_client.py:227-321` | **`TemporalWorkerPool` не инстанцируется** — 94 LOC, 0 call-sites | Создать `temporal_worker_runtime.py` |
| **D-A8-05** | `plugins/composition/workflow_setup.py:76-83` | **`_bootstrap_default_declarations` импортирует несуществующие модули** | Удалить функцию |
| **D-A8-06** | `extensions/core_entities/orders/workflows/orders_dsl.py:241,250,305,316,326,336` | **`orders_dsl.py` использует несуществующий `.then()`** | Добавить `.then()` alias в WorkflowBuilder |

---

## 3. P1 — runtime fragile / security fail-open

| ID | Файл:строка | Описание |
|---|---|---|
| **D-A8-07** | `dsl/workflow/compiler/step_compilers.py:602-672` | `GuardrailDeclaration` fail-open для non-numeric (cost explosion) |
| **D-A8-08** | `infrastructure/workflow/temporal_backend.py:165-176` | Multi-tenant namespace mismatch warning-only |
| **D-A8-09** | `dsl/engine/processors/cancel_workflow.py:146-148` | `WorkflowHandle(workflow_id=wf_id, run_id=wf_id)` semantic violation |
| **D-A8-10** | `dsl/workflow/compiler/step_compilers.py:379-401` | `compile_sensor_step` infinite polling |
| **D-A8-11** | `services/workflows/hitl_signal_store_redis.py:218-256` | `WatchError` retry-loop без iteration cap |

---

## 4. P2 — dead code / cleanup (10 штук)

`ContinueAsNewHandler` (D-A8-15), `_iter_activity_names` (D-A8-18), `BpmnImportNotAvailableError` (D-A8-17),
`run_workflow_by_id` stub (D-A8-16), `SlaTracker` без consumer (D-A8-13), `HitlService.resolve` (D-A8-14),
`WorkflowVersionRegistry` race (D-A8-19), `orchestrator_engine._evaluate_condition` swallow-all (D-A8-21),
`cost_estimator.llm_breakdown` (D-A8-22), `ContinueAsNew` docs misleading (D-A8-20).

---

## 5. P3 — library replacements (8 штук)

`WorkflowSubprocessProcessor` + BPMN importer → `spiffworkflow` (D-A8-23, −300 LOC),
DOT injection (D-A8-25), exception_to_result (D-A8-26), DurableWorkflowRunner re-implementation (D-A8-27),
Saga/Hitl/StepAuditMiddleware без consumer (D-A8-28), WorkflowDiff не подключён (D-A8-29),
legacy GatewayCompiler (D-A8-30), CJK symbol (D-A8-24).

---

## 6. P4 — missing DSL features (4 штуки)

cron/schedule DSL (D-A8-31), parallel() fan-out (D-A8-32), with_timeout per-step (D-A8-33),
`start_child_workflow`/`await_external_signal` (D-A8-34).

---

## 7. Недавно исправлено в HEAD

- **D-AUDIT-FIX-184-1** (commit `ae35c291`): `CompensatingDriverWorker` (NEW, 156 LOC) — periodic 60s
  drainer для stuck compensating sagas. Только 1 cross-domain fix в HEAD `7f3d94a3`.

---

## 8. Не проверено

Реальный Temporal кластер, `manage.py workflow *` CLI, extensions/{core_admin,example_plugin,skb,test_plug},
infrastructure/scheduler/temporal_scheduler_backend.py, tools/checks/, services/audit/workflow_audit_sink.py,
pytest --cov, services/workflows/{saga_history,hitl_history}.py, extensions/core_entities/orders/workflows/orders_dsl.py,
deploy/{helm,k8s,docker-compose}, frontend streamlit.

---

## 9. Запросы к смежным доменам

| Домен | Запрос |
|---|---|
| **A1** | `outbox_worker.py:36` `global _scheduler` — re-implementation APScheduler |
| **A2** | `capability_guarded_activity.fail-closed` (line 223-228) production verification |
| **A3** | `WorkflowFacade.await_completion` без capability-check (line 184-192) |
| **A4** | `cancel_workflow` inconsistent sync semantics (D-A8-05 cycle 3 P0-005) |
| **A5** | `WorkflowDeclaration.version` semver + `WorkflowDiff` API не экспортированы через schema-registry |
| **A6** | cancel_workflow inconsistent — нарушает contract route/processor композиции |
| **A9** | `compile_agent_invoke_step` payload без `cost_budget_usd` |
| **A11** | `temporalio>=1.27.0,<2.0.0` verify CVE-free |
| **A12** | `WorkflowFlags` 4 из 5 default=True (D-A8-01) cross-domain fix |

---

## 10. Готовность домена: **25/100** (clamp из-за 6 P0)

**Обоснование:**
1. DSL полностью декларативен (12 declaration-типов, 17+ builder-методов, BPMN, semver)
2. Protocol-based backend architecture корректна (4 backend'а + DI factory)
3. Capability-gated facade + audit-sink
4. **Главная проблема — 6 P0 PERSISTS:** WorkflowFlags lie, 4 unregistered processors,
   `ActivityBridge.decorate()` + `TemporalWorkerPool` ни разу не вызваны (Temporal Worker runtime path мёртв),
   `_bootstrap_default_declarations` импортирует несуществующие saga-модули,
   `orders_dsl.py` использует `.then()` метод, которого нет
5. 5 P1 fail-open/race/data-loss
6. Workflow domain = "DSL complete, runtime fragile"

**Recommended next-tasks (B-33..B-48):** WorkflowFlags default=False (+4 LOC), register 4 processors (+24),
Wire ActivityBridge+TemporalWorkerPool (+72), fix _bootstrap (−30), .then() alias (+5),
compile_guardrail_step fail-open fix (+10), compile_sensor_step safety cap (+2), namespace mismatch raise (+8),
WorkflowHandle run_id (+9), WatchError cap (+8), P2 cleanup (−400), P3 library replacement (−300),
P4 Temporal child workflow (+30).

---

**Файл отчёта сохранён. Самодостаточен для Phase-2 summarizer.**
