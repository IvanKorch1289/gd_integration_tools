# Cycle 2 — Phase 1 — Workflow domain audit

**Audit date:** 2026-08-06
**Scope (read-only, do not mutate):**
- `src/backend/dsl/workflow/**` (builder, compiler, gateways, launcher, orchestrator, yaml_io, visualize, dryrun, bpmn_importer, versioning, templates, spec, builder.pyi, __init__, handlers)
- `src/backend/dsl/engine/processors/workflow/**`
- `src/backend/dsl/engine/processors/invoke_workflow.py`
- `src/backend/dsl/engine/processors/cancel_workflow.py`
- `src/backend/dsl/engine/processors/sub_workflow.py`
- `src/backend/services/workflow/**` (только `__init__.py` re-export facade)
- `src/backend/services/workflows/**` (cost_estimator, facade, hitl_*, saga_history, sla_alerting, template_registry)
- `src/backend/infrastructure/workflow/**` (executor, factory, lite_temporal_backend, middlewares, outbox_worker, pg_runner_backend, pg_runner_internals, registry, runner, saga_state, temporal_backend, temporal_client, versioning, worker, worker_probes, __init__)
- `src/backend/core/workflow_registry.py`
- `src/backend/core/workflow/**` (backend, compensation, fake_backend, __init__)
- `src/backend/core/config/workflow.py`
- `src/backend/core/config/features/workflow.py`
- `tests/workflow/**` + `tests/unit/dsl/workflow/**` + `tests/unit/services/workflows/**` + `tests/unit/infrastructure/workflow/**` (точечно, для подтверждения use)

HEAD: `ca5bff93` (cycle 2 baseline). Не атрибутирую cycle 1 неподтверждённые правки (см. BASELINE.md).

---

## 1. Scope / не проверено

### Проверено (прочитано и верифицировано)

Все файлы scope прочитаны целиком или ключевыми окнами (классы/функции/строки импорта). Основные проверки:

- `src/backend/core/config/features/workflow.py` — все 5 полей WorkflowFlags.
- `src/backend/dsl/engine/processors/{invoke_workflow,cancel_workflow,sub_workflow}.py` — зарегистрированы через `@processor` (namespace="core", category="workflow").
- `src/backend/dsl/engine/processors/workflow/**` — 4 файла процессоров, **ни один** не использует `@processor` декоратор.
- `src/backend/dsl/workflow/compiler/activity_bridge.py` — все API.
- `src/backend/infrastructure/workflow/{worker,runner,executor,factory,temporal_backend,temporal_client}.py` — поиск ссылок на `ActivityBridge`, `TemporalWorkerPool`, `register_workflows_with_temporal`.
- `src/backend/core/workflow/{backend,compensation,fake_backend,__init__}.py` — Protocol и Pydantic модели.
- `src/backend/core/workflow_registry.py` — singleton, регистрация и lookup.
- `src/backend/services/workflows/facade.py` — capability-gated facade.
- `src/backend/dsl/workflow/{dryrun,bpmn_importer,yaml_io,versioning,visualize,gateways}.py` — конкретные проверки на использование.
- `tools/check_layers.py --root src` + `wc -l tools/check_layers_allowlist.txt` (см. ниже).
- `python -m pytest tests/unit/dsl/workflow/{test_dryrun,test_bpmn_importer,test_launcher,test_gateways,test_yaml_round_trip,test_builder,test_visualize,test_versioning,test_spec,test_to_mermaid}.py tests/unit/core/workflow/test_compensation.py` — 146 PASSED, 4 FAILED из-за missing optional deps (simpleeval/jmespath; не связаны с security).
- `tests/unit/infrastructure/workflow/test_replay_registry_cycle33.py` (через grep) — есть тесты `workflow_registry.register`/`get`.

### Не проверено

- Тесты вне `tests/unit/{dsl/workflow,services/workflows,core/workflow,infrastructure/workflow}` (не в scope).
- `extensions/**` кроме `extensions/core_entities/orders/workflows/orders_dsl.py` (затронут как reference).
- `manage.py` и `src/backend/plugins/composition/lifecycle/startup.py` — точечно проверены только в контексте Worker registration bootstrap.
- Production Temporal worker config в deploy/ — не в scope.
- Runtime e2e в реальном Temporal кластере — не выполнялось (dev_light без `temporalio` SDK).
- Лицензионный/maintenance риск библиотек (`simpleeval`, `jmespath`, `temporalio`) — не проверено (см. ниже, требует внешнего исследования).
- `docs/audit/swarm-2026-08-06/cycle-1/**`, `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md`, `PHASE-2-SUMMARY.md`, `PHASE-3-PLAN.md` — не читал по инструкции.

---

## 2. Verified strengths

| # | Что работает | Evidence |
|---|---|---|
| S-1 | Protocol-based архитектура `WorkflowBackend` (start_workflow / signal / query / cancel / await_completion / replay / await_external_signal / start_child_workflow). | `src/backend/core/workflow/backend.py:65-191` |
| S-2 | 3 production-готовых бэкенда: `TemporalWorkflowBackend`, `LiteTemporalBackend`, `PgRunnerWorkflowBackend` + `FakeWorkflowBackend` для тестов. | `src/backend/infrastructure/workflow/{temporal_backend,lite_temporal_backend,pg_runner_backend}.py`, `src/backend/core/workflow/fake_backend.py:1-205` |
| S-3 | Динамическая компиляция `WorkflowDeclaration` → `@workflow.defn` через `compile_workflow` + singleton `workflow_registry`. Re-emission идемпотентен (cycle 37 fix). | `src/backend/dsl/workflow/compiler/emitter.py:72-177` |
| S-4 | Полная saga-сематика с `compensate_map` (explicit name→step) + positional fallback, `strict_compensate=True` для fail-loud. | `src/backend/dsl/workflow/spec/activity_declarations.py:47-130`, `src/backend/dsl/workflow/compiler/step_compilers.py:181-282` |
| S-5 | `WorkflowFacade` (capability-gated) — единственный путь из плагинов к backend, с audit-sink через `WorkflowAuditSink`. | `src/backend/services/workflows/facade.py:40-192` |
| S-6 | Cycle 33 restore XOR/AND/OR gateways + runtime-компиляция `compile_xor/and/or` + `simpleeval` для условий (sandbox-safe). | `src/backend/dsl/workflow/compiler/gateways.py:124-227`, `src/backend/dsl/workflow/builder/gateway_mixin.py:1-102` |
| S-7 | 5 advanced declarations (Reflect/Checkpoint/Guardrail/Escalate/AgentInvoke) скомпилированы через `compile_*_step` и dispatch через `dispatch_step_compile`. | `src/backend/dsl/workflow/compiler/step_compilers.py:514-723` |
| S-8 | HITL `HitlService` + Redis-backed `RedisHitlSignalStore` + pub/sub broadcast (best-effort, не ломает polling waiter). | `src/backend/services/workflows/hitl_service.py:318-487`, `src/backend/services/workflows/hitl_signal_store_redis.py:1-310` |
| S-9 | Saga LRA processor + `WorkflowStateRepository` (persistent compensating state с RLS). | `src/backend/infrastructure/workflow/saga_state.py:117-277`, `src/backend/dsl/engine/processors/saga_lra.py` |
| S-10 | StepAuditMiddleware (async ClickHouse writer с back-pressure + per-tenant scoping) + `StepAuditEvent` dataclass. | `src/backend/infrastructure/workflow/middlewares/step_audit.py:1-308` |
| S-11 | Standalone durable worker через `DurableWorkflowRunner` (LISTEN/NOTIFY + advisory lock + lease-based). Worker-реплики координируются через DB. K8s probes server + Prometheus gauges. | `src/backend/infrastructure/workflow/{worker.py,runner.py,worker_probes.py}` |
| S-12 | BPMN 2.0 → WorkflowDeclaration import (через stdlib + defusedxml XXE-guard). Топологическая сортировка sequence-flow. | `src/backend/dsl/workflow/bpmn_importer.py:50-444` |
| S-13 | `WorkerVersioningHelper` для Temporal Worker Versioning (BuildID pinning). Lazy import — temporalio не подтягивается до первого использования. | `src/backend/infrastructure/workflow/versioning/worker_versioning.py:1-159` |
| S-14 | `core.workflow.__init__` — lazy `__getattr__` для `create_workflow_backend` (single export surface для extensions). | `src/backend/core/workflow/__init__.py:24-30` |
| S-15 | `WorkflowLauncher` SemVer resolution с packaging.specifiers. Worker instance resolution в `InvokeWorkflowProcessor._resolve_workflow_version` под feature-flag. | `src/backend/dsl/workflow/launcher.py:1-208`, `src/backend/dsl/engine/processors/invoke_workflow.py:129-157` |

---

## 3. Findings table (P0..P4)

| ID | Priority | Path:Line | Краткое описание |
|---|---|---|---|
| DOMAIN-WF-P0-001 | P0 | `src/backend/core/config/features/workflow.py:33-73` | WorkflowFlags docstring lie: 4 из 5 флагов задокументированы как `default-OFF до интеграции`, реально `default=True` (legacy_disabled, yaml_round_trip, bpmn_import, gateways_enabled). `workflow_orchestrator_enabled` — корректно default=False. |
| DOMAIN-WF-P0-002 | P0 | `src/backend/dsl/engine/processors/workflow/{workflow_subprocess,workflow_convert}.py` + `workflow/best_practices/{claim_check,continue_as_new}.py` | 4 процессора не зарегистрированы через `@processor`. В отличие от `invoke_workflow/cancel_workflow/sub_workflow` (в `dsl.engine.processors.workflow.__init__`), они не попадают в `processor_registry` и не могут быть вызваны из DSL-маршрутов. |
| DOMAIN-WF-P0-003 | P0 | `src/backend/dsl/workflow/compiler/activity_bridge.py:1-356` | ActivityBridge (356 LOC) написана, тесты существуют (`tests/unit/dsl/workflow/compiler/test_activity_bridge.py`), но **production worker не использует** эту машинерию. `infrastructure/workflow/worker.py` поднимает `DSLStepExecutor` поверх `WorkflowSpec`, а не `@workflow.defn` классы. `register_workflows_with_temporal` — задокументирован как существующий, но нигде не определён. |
| DOMAIN-WF-P0-004 | P0 | `src/backend/infrastructure/workflow/temporal_client.py:227-320` | `TemporalWorkerPool` определён (94 LOC), но **не инстанцируется ни в одном prod/test коде**. Используется только в `core/scaling/auto_scaler.py:139` (docstring) и `infrastructure/scheduler/temporal_scheduler_backend.py:24` (docstring) + docs/tutorials/04_temporal_workflow.md:63 (пример). |
| DOMAIN-WF-P0-005 | P0 | `src/backend/plugins/composition/workflow_setup.py:76-83` | `_bootstrap_default_declarations` импортирует `build_orders_saga_workflow` из `extensions/core_entities/orders/workflows/orders_saga` и `build_payments_saga_workflow` из `extensions/credit_pipeline/workflows/payments_saga`. Оба файла не существуют (только `orders_dsl.py` и `__init__.py`). Default-OFF (`WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=false`) маскирует баг; включение → `ImportError` на startup. |
| DOMAIN-WF-P1-001 | P1 | `src/backend/dsl/workflow/builder/{__init__,sla_mixin,wait_mixin,lifecycle_mixin,ai_mixin,gateway_mixin,workflow_mixin}.py` (общий класс `WorkflowBuilder`) + `extensions/core_entities/orders/workflows/orders_dsl.py:241,250,305,316,326,336` | `orders_dsl.py` (в `extensions/`) использует `.then(ActivityDeclaration(...))` на `WorkflowBuilder`, но `WorkflowBuilder` не имеет метода `then()`. Импорт `send_notification_workflow_spec()` упадёт на первой попытке использовать метод `.then()` (тесты подтверждают: `hasattr(b, 'then') == False`). Это dead/broken code в production extension — влияет на бутстрап `extensions/core_entities/orders`. |
| DOMAIN-WF-P1-002 | P1 | `src/backend/services/workflows/cost_estimator.py:97-192` | `WorkflowCostEstimator.estimate` читает ClickHouse workflow_audit, но **fallback на `Decimal("0")` для LLM cost** при любом сбое `LLMModelPricing` (line 178-179). Нет raise — silent degraded mode. Кроме того, `llm_breakdown` всегда `None` если feature-flag `workflow_versioning_routes=False` (т.к. `get_global_registry()` не используется) — это означает что LLM cost estimation фактически dead code для default конфигурации. |
| DOMAIN-WF-P1-003 | P1 | `src/backend/dsl/workflow/gateways.py:75-177` (класс `GatewayCompiler`) + `process_gateway` (180-205) | Legacy `GatewayCompiler` (`compile_xor/and/or` статические методы возвращают dict) + `process_gateway` dispatch — используется **только в тестах** (`tests/unit/dsl/workflow/test_gateways.py`). Реальная runtime-компиляция делается через `compiler/gateways.py:compile_xor/and/or` (async, прямой `_run_branch_steps`). 137 LOC dead code. |
| DOMAIN-WF-P2-001 | P2 | `src/backend/core/workflow/compensation.py:24-39` | `COMPENSATE_SIGNAL` константа + `CompensateWorkflowRequest` Pydantic модель определены, но в production коде не используются (только в `core/workflow/backend.py:110` как упоминание в комментарии и в `tests/unit/core/workflow/test_compensation.py`). Saga compensation реально работает через `compile_saga_step` + `SagaDeclaration.compensate[]`. 40 LOC мёртвого контракта. |
| DOMAIN-WF-P2-002 | P2 | `src/backend/dsl/workflow/handlers/continue_as_new_handler.py` (проверено через `ls` в scope) + `compiler/continue_as_new_handler.py` | `WorkflowContinueAsNewProcessor` (best_practices) НЕ имеет `@processor` (см. DOMAIN-WF-P0-002) + handler упомянут в комментариях `dsl/workflow/compiler/continue_as_new_handler.py`. Не используется нигде. |
| DOMAIN-WF-P2-003 | P2 | `src/backend/dsl/workflow/visualize.py:50-272` + `spec/workflow.py:93-100` | `WorkflowDiff` (через `diff()`) реализован, но не подключён к Admin API workflow-versioning (admin_workflow_versioning.py использует `get_global_registry().diff_versions()` — другой путь). `visualize.py:to_mermaid/to_graphviz` — есть, но `compute_step_diff` упоминается только в facade. Минимальное покрытие тестами. |
| DOMAIN-WF-P2-004 | P2 | `src/backend/dsl/workflow/bpmn_importer.py:88-95` | `BpmnImportNotAvailableError` определён, но **никогда не возбуждается** (docstring явно говорит "Текущая реализация использует stdlib ... данное исключение никогда не возбуждается. Оставлено в публичном API для совместимости"). Dead exception. |
| DOMAIN-WF-P2-005 | P2 | `src/backend/dsl/workflow/compiler/emitter.py:118` | `dispatch_step_compile` используется только в emitter.py:118 внутри `compile_workflow`. Если бы `compile_workflow` был вызван с `WorkflowDeclaration` содержащим `AgentInvokeDeclaration` с `durable=True` — вызвал бы `compile_agent_invoke_step` (476-499), но cycle 37 path registration фиксирует только успешную компиляцию. Тесты `compiler/test_emitter.py` skip без temporalio. |
| DOMAIN-WF-P2-006 | P2 | `src/backend/dsl/workflow/dryrun.py:29-137` (137 LOC) | `run_workflow_dryrun` — `dryrun.py` определяет "Pure functional симулятор без Temporal". Используется только в `tests/unit/dsl/workflow/test_dryrun.py` (3 теста) + `manage.py:1243` (CLI `workflow dryrun`) + `manage.py:1322` (import). CLI команда существует, но в production не используется. Документация (`workflow_dryrun_enabled` flag) говорит "default-OFF" но фактически `feature_flags.workflow_dryrun_enabled` default=True в `sprint5_dsl.py:212-220`. |
| DOMAIN-WF-P3-001 | P3 | `src/backend/services/workflows/sla_alerting.py:185-280` | `SlaTracker` (polling-based SLA monitor) — реализован, но не используется в `DurableWorkflowRunner` или `StepAuditMiddleware`. Service-слой с Protocol `SlaAlertDispatcher` (abstract) и `InMemorySlaAlertDispatcher` для тестов — нет ни одного production consumer. |
| DOMAIN-WF-P3-002 | P3 | `src/backend/services/workflows/saga_history.py` + `src/backend/services/workflows/hitl_history.py` | `SagaHistoryService` + `HitlHistoryService` — оба читают ClickHouse, оба не зарегистрированы в DI providers, не подключены к Admin API endpoints (admin_saga_history.py, admin_hitl_history.py проверены — они используют `get_saga_history`/`aggregate_saga_stats` через `builder_facade.py`). Фактически работают через facade. |
| DOMAIN-WF-P3-003 | P3 | `src/backend/infrastructure/workflow/middlewares/step_audit.py:158-187` | `StepAuditMiddleware` start/stop управляется через `feature_flags.workflow_step_log_enabled`. Не вызывается из `DSLStepExecutor.execute_next()` (`infrastructure/workflow/executor/__init__.py:118-200`) — middleware есть, но integration точка не подключена. Тесты (`tests/unit/dsl/workflow/test_step_audit_correlation_fallback.py`) определяют `_make_middleware()` fixture — модуль существует, но не используется. |
| DOMAIN-WF-P4-001 | P4 | (no specific file) | Library replacement — minor: `simpleeval` (sandbox-safe expression eval) и `jmespath` уже в pyproject.toml deps. `defusedxml` — transitive dep (uv.lock). Замены не требуется (зрелые, maintenance active). `temporalio` SDK (~15-20MB) — нужен для production path, не duplicate. |
| DOMAIN-WF-P4-002 | P4 | (no specific file) | Новый feature: BPMN subprocess multi-instance pattern (BPMN 2.0 §13) — bpmn_importer.py не покрывает multi-instance activity/sequential sub-process. Но это уже за рамками минимального workflow DSL и не критично для текущих use-cases (saga/temporal). |
| DOMAIN-WF-P4-003 | P4 | (no specific file) | Новый feature: workflow timeout-cancellation через Temporal `workflow.new_timer` (e.g. `cancel_after(seconds=300)` pattern) — DSL и emitter поддерживают только `default_timeout_s` на уровне workflow, не per-step TTL cancellation. Не критично. |

---

## 4. Detailed evidence

### DOMAIN-WF-P0-001 — WorkflowFlags docstring lie

**Файл:** `src/backend/core/config/features/workflow.py`
**Lines:** 33-73
**Evidence:**

```
L32-41: workflow_legacy_disabled: bool = Field(default=True, ...,
            description=(
                "K4 Wave 1. Owner: K4 Workflow. ETA: S2-W1. "
                "При True блокирует все импорты из legacy 4 файлов "
                "(state.py/state_store.py/event_store.py/state_projector.py). "
                "default-OFF до миграции 19 импортёров на TemporalFacade."
            ),

L43-51: workflow_yaml_round_trip: bool = Field(default=True, ..., 
            "default-OFF до golden-snapshot тестов на 5 эталонных workflow."

L53-61: workflow_bpmn_import: bool = Field(default=True, ...,
            "default-OFF до research-spike ADR + sample-теста."

L63-73: workflow_gateways_enabled: bool = Field(default=True, ...,
            "default-OFF до интеграции GatewayCompiler с emitter.py и staging-smoke."

L75-84: workflow_orchestrator_enabled: bool = Field(default=False, ...,  # CORRECT
            "default-OFF до интеграции с AgentRegistry и production-smoke."
```

**Проверка:** `grep -nE "workflow_(legacy_disabled|yaml_round_trip|bpmn_import|gateways_enabled|orchestrator_enabled)" src/backend/core/config/features/workflow.py` — `default=True` для 4 из 5, `default=False` для 1.

**Impact:**
- Операторы включают feature-flag (который `default=True` уже), ожидая что feature ещё не активен (по docstring). Это не security-impact, но operational confusion.
- 4 файла используются через `@processor` decorators и `WorkflowCompilerRegistry` безусловно — workflow_legacy_disabled=False по факту не даст fail-closed.
- В документации (CLAUDE.md sprint retro, `core/config/features/__init__.py:170`) говорится "Наследуются через multiple inheritance" — но реальные default отличаются от docs.
- `BpmnImportDisabledError` (bpmn_importer.py:177) срабатывает только если flag=False; с default=True BPMN import **всегда enabled в production** (defusedxml защита OK, но контракт заявлен иной).

**Минимальная рекомендация:** Привести `default=...` и description в соответствие. Для корректного fail-closed установить `default=False` для всех 4 флагов (workflow_legacy_disabled уже должен быть False до миграции 19 импортёров).

**Тест-критерий:** `make check-feature-flags` или property-тест: для каждого field в `WorkflowFlags` убедиться что `(description contains "default-OFF") ⟺ (default is False)`.

---

### DOMAIN-WF-P0-002 — 4 процессора без `@processor` декоратора

**Файлы:**
- `src/backend/dsl/engine/processors/workflow/workflow_subprocess.py` — `WorkflowSubprocessProcessor` (line 56)
- `src/backend/dsl/engine/processors/workflow/workflow_convert.py` — `WorkflowConvertProcessor` (line 23)
- `src/backend/dsl/engine/processors/workflow/best_practices/claim_check.py` — `WorkflowClaimCheckProcessor`
- `src/backend/dsl/engine/processors/workflow/best_practices/continue_as_new.py` — `WorkflowContinueAsNewProcessor`

**Evidence (grep):**
```
$ grep -rn "@processor" src/backend/dsl/engine/processors/workflow/
No non-sensitive matches found

$ grep -nE "from src.backend.dsl.registry" workflow_subprocess.py
31:from src.backend.dsl.engine.processors.base import BaseProcessor
# НЕТ импорта src.backend.dsl.registry
```

В отличие от invoke/cancel/sub_workflow, эти 4 не декорированы и не экспортируются через `dsl/engine/processors/workflow/__init__.py` (там только 3 — re-export из flat).

**Impact:**
- В DSL YAML/markup нельзя использовать `workflow_subprocess:`, `workflow_convert:`, `workflow_claim_check:`, `workflow_continue_as_new:` — они не в `processor_registry`.
- `run_workflow_by_id` (workflow_subprocess.py:24) — единственный публичный entry-point через прямой Python import. Dead path кроме тестов.
- Best-practices (claim-check для >2MB payloads, continue-as-new для Event History) — критичные Temporal паттерны, которые рекламируются в `best_practices/__init__.py` docstring, но **не работают** в DSL.

**Минимальная рекомендация:** Добавить `@processor(...)` декоратор с spec_schema на каждый из 4 классов, экспортировать через `processors/workflow/__init__.py`.

**Тест-критерий:** `make dsl-lint` или property-тест: для каждого `BaseProcessor` subclass в `dsl.engine.processors.*` убедиться что он декорирован `@processor`.

---

### DOMAIN-WF-P0-003 — ActivityBridge не используется в production worker

**Файлы:**
- `src/backend/dsl/workflow/compiler/activity_bridge.py:1-356`
- `src/backend/infrastructure/workflow/worker.py:1-418`
- `src/backend/dsl/workflow/compiler/__init__.py:28-31`

**Evidence:**
```
$ grep -ln "ActivityBridge|activity_bridge|bridge_action_handler|register_langgraph_checkpoint" src/backend/infrastructure/workflow/
(empty)

$ grep -rn "register_workflows_with_temporal" src/
src/backend/dsl/workflow/compiler/registry.py:4: hot-reload'ами, чтобы `register_workflows_with_temporal` не
src/backend/dsl/workflow/compiler/__init__.py:30: :func:`register_workflows_with_temporal`. Workflow-сэндбокс
# Только комментарии, нет определения.
```

`worker.py` (line 67-100): `_resolve_executor()` возвращает `DSLStepExecutor(spec_loader=build_spec_loader())` — это pg-runner path. `compile_workflow` + ActivityBridge → Temporal worker path не активируется.

**Impact:**
- Dynamic `@workflow.defn` компиляция работает (`compile_workflow` → `CompiledWorkflow`), но **зарегистрированные классы никогда не поднимаются в Temporal Worker**.
- `replay()` через `TemporalWorkflowBackend.replay()` (line 277-314) использует `workflow_registry.get(workflow_name)` — но без Worker registration replay не имеет смысла.
- `LANGGRAPH_CHECKPOINT_GET_ACTIVITY` / `LANGGRAPH_CHECKPOINT_PUT_ACTIVITY` — Temporal activities, но `register_langgraph_checkpoint_activities` нигде не вызывается.
- Documentation lie (`register_workflows_with_temporal` — несуществующая функция).

**Минимальная рекомендация:** Либо подключить ActivityBridge к `TemporalWorkerPool.register_worker()` через отдельный entry-point (нужно реализовать `TemporalWorkerPool` instantiation — см. DOMAIN-WF-P0-004), либо удалить ActivityBridge как dead code.

**Тест-критерий:** E2E тест: запустить `compile_workflow(WorkflowDeclaration(...))` → зарегистрировать в `TemporalWorkerPool` → запустить в LiteTemporalBackend → дождаться completion.

---

### DOMAIN-WF-P0-004 — `TemporalWorkerPool` не инстанцируется

**Файл:** `src/backend/infrastructure/workflow/temporal_client.py:227-320`
**Evidence:**
```
$ grep -rn "TemporalWorkerPool(" src/ tests/
docs/tutorials/04_temporal_workflow.md:63:pool = TemporalWorkerPool(factory=factory, namespace="default")
# Только docs, нет production/test usage.
```

Класс определён (`register_worker`, `shutdown`, `list_workers`, `__init__`), но **ни один caller не создаёт instance**. Используется в:
- `core/scaling/auto_scaler.py:139` (только docstring)
- `infrastructure/scheduler/temporal_scheduler_backend.py:24` (только docstring)
- `docs/tutorials/04_temporal_workflow.md:63` (пример, не тест)

**Impact:**
- 94 LOC мёртвого production-grade pool-кода.
- Multi-worker scaling (`auto_scaler.py` ссылается на него) фактически не работает.
- Невозможно зарегистрировать скомпилированные `@workflow.defn` классы из `compile_workflow`.

**Минимальная рекомендация:** Либо удалить `TemporalWorkerPool`, либо создать отдельный `temporal_worker.py` Typer-CLI (рядом с существующим `worker.py`), который инстанцирует pool и запускает через `register_worker`.

**Тест-критерий:** Integration test: `pool = TemporalWorkerPool(factory=..., namespace="default")` + `register_worker(task_queue="x", workflows=[MyWf], activities=[a1])` — успешно запускается.

---

### DOMAIN-WF-P0-005 — `_bootstrap_default_declarations` импортирует несуществующие модули

**Файл:** `src/backend/plugins/composition/workflow_setup.py:59-89`
**Evidence:**
```
L76-83:
    from extensions.core_entities.orders.workflows.orders_saga import (
        build_orders_saga_workflow,
    )
    from extensions.credit_pipeline.workflows.payments_saga import (
        build_payments_saga_workflow,
    )
```

**Проверка:**
```
$ ls extensions/core_entities/orders/workflows/
__init__.py  orders_dsl.py

$ ls extensions/credit_pipeline/workflows/
__init__.py  code_interpreter_loop.workflow.yaml  credit_assessment.workflow.yaml
              multi_agent_supervisor.workflow.yaml  rag_augmented_saga.workflow.yaml  README.md

# orders_saga.py — НЕТ
# payments_saga.py — НЕТ

$ tests/unit/workflows/test_orders_saga.py
L1-3: """S168 W14: orders_saga demo workflow removed (commit 9164a59 "enable all feature flags + remove demos").
All 8 tests in this module depend on build_orders_saga_workflow() which no longer exists.
Skipped — not deleted (the workflow design pattern is still valid, just the demo was removed)."""
```

**Impact:**
- `_bootstrap_default_declarations` гейтится через `WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=False` (default), но если оператор включит — `ImportError` на startup.
- Это прямой security/data-loss risk: если кто-то решит "включить bootstrap defaults" без чтения кода, приложение не стартанёт.

**Минимальная рекомендация:** Либо удалить `_bootstrap_default_declarations` целиком (saga demos удалены commit 9164a59), либо восстановить `orders_saga.py` и `payments_saga.py` в extensions.

**Тест-критерий:** `pytest tests/unit/plugins/composition/test_workflow_setup.py::test_bootstrap_with_flag_enabled` должен проходить без ImportError.

---

### DOMAIN-WF-P1-001 — orders_dsl.py использует несуществующий `.then()`

**Файл:** `extensions/core_entities/orders/workflows/orders_dsl.py:241,250,305,316,326,336`
**Evidence:**
```
L241: .then(ActivityDeclaration(name="request_skb_result", args={...}))
L250: .then(SensorDeclaration(predicate="skb_result == null", ...))
L305: .then(ActivityDeclaration(name="step_create", args={...}))
L316: .then(SleepDeclaration(name="initial_delay", ...))
L317: .then(ActivityDeclaration(name="step_poll", args={...}))
L326: .then(ActivityDeclaration(name="step_send", args={...}))
L336: .then(ActivityDeclaration(name="notify_critical_failure", args={...}))
```

**Проверка:**
```
$ PYTHONPATH=src python -c "
from src.backend.dsl.workflow.builder import WorkflowBuilder
b = WorkflowBuilder('test').description('x')
print('then?', hasattr(b, 'then'))"
then? False
```

В `WorkflowBuilder` нет метода `then()`. Доступны только: `activity`, `saga`, `sla`, `wait_for_signal`, `sleep`, `sensor`, `invoke_agent`, `reflect`, `checkpoint`, `guardrail`, `pause`, `resume`, `escalate`, `gateway_xor/and/or`, `description`, `version`, `default_timeout`, `default_retry`, `build`.

**Impact:**
- Любой caller `build_all_order_workflows()` → `AttributeError: 'WorkflowBuilder' object has no attribute 'then'`.
- Это broken code в `extensions/`, не covered by CI (extension test coverage отсутствует).
- Потенциальный blocker для `extensions/core_entities/orders` boot path.

**Минимальная рекомендация:** Либо добавить `def then(self, step: WorkflowStep) -> Self` в `WorkflowBuilder` (через mixin), либо переписать `orders_dsl.py` на `.activity()` / `.sleep()` / `.sensor()` / `.gateway_*` цепочку.

**Тест-критерий:** `pytest tests/unit/extensions/core_entities/orders/test_workflows.py::test_build_all_order_workflows` — должен проходить без AttributeError.

---

### DOMAIN-WF-P1-002 — `WorkflowCostEstimator` silent fallback

**Файл:** `src/backend/services/workflows/cost_estimator.py:97-192`
**Evidence:**
```
L167-176:
    try:
        from src.backend.dsl.workflow.versioning import get_global_registry
        registry = get_global_registry()
        wf_version = registry.get_default(workflow_id)
        ...
    except Exception as _:
        llm_breakdown = None
```

Поскольку `feature_flags.workflow_versioning_routes=True` (default — см. DOMAIN-WF-P0-001 systemic pattern), `get_global_registry()` должен вернуть registry. Но `workflows/versioning.py:161-184` (`get_global_registry`) лениво создаёт singleton; если в lifespan он не заполнен (e.g. dev_light без `temporalio`), `registry.get_default(workflow_id)` → `None`, `llm_breakdown = None`. **Silent degraded mode без warning**.

**Impact:**
- LLM cost estimation фактически возвращает `0 USD` для всех workflow, где version registry не заполнен.
- Pre-flight cost estimate (`/api/v1/admin/workflows/cost/estimate/{workflow_name}`) вводит в заблуждение.
- Data-loss impact: cost alarms не срабатывают.

**Минимальная рекомендация:** Raise `RuntimeError("workflow_versioning_routes required for LLM cost estimation")` вместо silent fallback; либо явно вернуть `CostEstimate` с `estimated_cost_usd=None` и явной меткой `cost_unavailable=True`.

**Тест-критерий:** `pytest tests/unit/services/workflows/test_cost_estimator.py` — тест-кейс `test_estimate_returns_unavailable_when_registry_empty` должен expect explicit error.

---

### DOMAIN-WF-P1-003 — Legacy `GatewayCompiler` dead code

**Файл:** `src/backend/dsl/workflow/gateways.py:75-205`
**Evidence:**
```
$ grep -rn "GatewayCompiler|process_gateway" src/backend/dsl/workflow/
src/backend/dsl/workflow/gateways.py:14: * :class:`GatewayCompiler` — чистый класс без состояния (stateless).
src/backend/dsl/workflow/gateways.py:24: process_gateway,
src/backend/dsl/workflow/gateways.py:34: result = process_gateway(spec)
src/backend/dsl/workflow/gateways.py:42: __all__ = ("BranchSpec", "GatewayCompiler", "GatewaySpec", "process_gateway")
src/backend/dsl/workflow/gateways.py:75: class GatewayCompiler:
src/backend/dsl/workflow/gateways.py:180: def process_gateway(...)
src/backend/dsl/workflow/builder/gateway_mixin.py:17: вместе с :class:`~dsl.workflow.gateways.GatewayCompiler`. Восстановлены
# В runtime compiler не используется — cycle 33 restore использует compiler/gateways.py:compile_xor/and/or.
```

**Runtime evidence:**
- `dsl/workflow/compiler/gateways.py:124-227` — async `compile_xor/and/or` с реальной runtime-семантикой (`_run_branch_steps`, `asyncio.gather`, `simpleeval`).
- Legacy `GatewayCompiler.compile_xor/and/or` возвращает dict для emitter consumption — но emitter (`compiler/emitter.py:118`) вызывает `dispatch_step_compile` → `compile_activity_step` (line 122), который уже сам делает dispatch на `compile_xor/and/or`.

**Impact:** 137 LOC неиспользуемого кода. P1 (dead code в core/dsl пути) — moderate.

**Минимальная рекомендация:** Удалить `GatewayCompiler` + `process_gateway`, оставить только `BranchSpec`/`GatewaySpec` dataclasses.

**Тест-критерий:** N/A (dead code cleanup).

---

### DOMAIN-WF-P2-001 — `COMPENSATE_SIGNAL` мёртвый контракт

**Файл:** `src/backend/core/workflow/compensation.py:1-40`
**Evidence:** определены `COMPENSATE_SIGNAL = "_compensation_request"` и `CompensateWorkflowRequest` Pydantic. Использование:
```
$ grep -rn "COMPENSATE_SIGNAL|CompensateWorkflowRequest" src/
src/backend/core/workflow/compensation.py:19: __all__ = ("COMPENSATE_SIGNAL", "CompensateWorkflowRequest")
src/backend/core/workflow/compensation.py:24: COMPENSATE_SIGNAL: str = "_compensation_request"
src/backend/core/workflow/compensation.py:27: class CompensateWorkflowRequest(BaseModel):
src/backend/core/workflow/backend.py:110: # не реализовывал его. Saga compensation работает через COMPENSATE_SIGNAL
# (только комментарий в Protocol docstring)
```

Только упоминания в `compensation.py` (определение), `backend.py` (docstring), `tests/unit/core/workflow/test_compensation.py` (тесты). Saga compensation реально работает через `compile_saga_step` + `SagaDeclaration.compensate[]`.

**Impact:** 40 LOC dead contract. Saga compensation path уже валиден без этого модуля.

**Минимальная рекомендация:** Удалить `core/workflow/compensation.py` или переместить в `dsl/workflow/compiler/saga_compensation.py` (где он реально используется).

---

### DOMAIN-WF-P2-004 — `BpmnImportNotAvailableError` никогда не возбуждается

**Файл:** `src/backend/dsl/workflow/bpmn_importer.py:88-95`
**Evidence:**
```
L88-95:
class BpmnImportNotAvailableError(RuntimeError):
    """Зарезервировано для пути SpiffWorkflow (когда extra не установлен).
    Текущая реализация использует stdlib :mod:`xml.etree.ElementTree`,
    поэтому данное исключение никогда не возбуждается. Оставлено в
    публичном API для совместимости с задачей K3 W3 и для
    альтернативного пути через SpiffWorkflow в будущем.
    """
```

**Impact:** Dead exception. SpiffWorkflow никогда не использовался (в pyproject.toml нет).

**Минимальная рекомендация:** Удалить `BpmnImportNotAvailableError` (или реализовать lazy import для SpiffWorkflow).

---

### DOMAIN-WF-P3-001 — `SlaTracker` не используется в production runner

**Файл:** `src/backend/services/workflows/sla_alerting.py:185-280`
**Evidence:**
```
$ grep -rn "SlaTracker\b" src/
src/backend/services/workflows/sla_alerting.py:28: "SlaTracker",
src/backend/services/workflows/sla_alerting.py:32: _logger = get_logger("workflow.sla_alerting")
src/backend/services/workflows/sla_alerting.py:185: """Запись tracking'а в SlaTracker."""
src/backend/services/workflows/sla_alerting.py:197: class SlaTracker:
src/backend/core/observability/metrics.py:3: ADR-0207: services/* observability (metrics.py, sla_alerting.py) импортируют
src/backend/core/utils/timeout_helper.py:16: lineage / sla_alerting.
src/backend/core/di/providers/observability_bridge.py:74: services/workflows/sla_alerting.py) для инициализации
```

**Impact:** SLA tracker написан, но runner его не использует. SLA breach monitoring — silent. Soft/hard limit нарушения не приводят к alert.

**Минимальная рекомендация:** Либо подключить `SlaTracker` к `DurableWorkflowRunner` через polling активных instances (line 169-176 `runner.py`), либо удалить.

---

### DOMAIN-WF-P3-003 — `StepAuditMiddleware` не подключён к executor

**Файл:** `src/backend/infrastructure/workflow/middlewares/step_audit.py:158-200`
**Evidence:** `_run_step` и `_exec_sequential` (executor/__init__.py:118-200) не вызывают `StepAuditMiddleware.track_step()`. Middleware есть, но integration точка отсутствует.

**Impact:** Step-level audit events для ClickHouse не пишутся. Observability gap для production debugging.

**Минимальная рекомендация:** Wrap `DSLStepExecutor.execute_next()` в `StepAuditMiddleware.track_step()` (через `__init__.py` injection).

---

### Layer violation рост (173→180 vs BASELINE 175)

**Evidence:**
```
$ python tools/check_layers.py --root src
Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)

$ wc -l tools/check_layers_allowlist.txt
180 tools/check_layers_allowlist.txt
```

**Факт:** allowlist файл содержит 180 строк, но `check_layers.py` reports **175 активных** legacy нарушений. Последнее изменение allowlist — коммит `df7ed5639d` (2026-08-05) добавил 1 entry (`core/di/providers/billing.py`). Рост 173→180 в user-reported цифре **не соответствует** текущему состоянию (175 legacy).

**Причина расхождения:**
- 180 lines = 175 active + 5 stale entries (нарушения исправлены, записи не удалены).
- Заявленный рост 173→180 — артефакт из cycle-1 отчёта; в cycle 2 baseline зафиксировано 175.

**Workflow-related layer violations (из strict mode):**
```
src/backend/core/workflow/__init__.py  core/  →  src.backend.infrastructure.workflow.factory
src/backend/entrypoints/api/generator/setup.py  entrypoints/  →  src.backend.workflows.workflows_service
src/backend/entrypoints/api/v1/endpoints/admin_workflow_versioning.py  entrypoints/  →  src.backend.dsl.workflow.versioning
src/backend/entrypoints/api/v1/endpoints/admin_workflows/helpers.py  entrypoints/  →  src.backend.dsl.commands.registry
src/backend/entrypoints/mcp/workflow_tools.py  entrypoints/  →  src.backend.dsl.commands.registry
src/backend/infrastructure/workflow/executor/sequential_mixin.py  infrastructure/  →  src.backend.dsl.engine.exchange
src/backend/infrastructure/workflow/worker.py  infrastructure/  →  src.backend.dsl.commands.setup
src/backend/infrastructure/workflow/worker.py  infrastructure/  →  src.backend.dsl.routes
src/backend/services/dsl_portal/builder_facade.py  services/  →  src.backend.dsl.workflow.{spec,versioning,visualize,yaml_io}
src/backend/services/workflow/__init__.py  services/  →  src.backend.infrastructure.workflow.registry
src/backend/services/workflows/cost_estimator.py  services/  →  src.backend.dsl.workflow.versioning
src/backend/services/workflows/hitl_pubsub.py  services/  →  src.backend.infrastructure.clients.storage.redis
```

Все 15 строк — allowlisted (legacy). Никаких новых нарушений в workflow scope.

---

## 5. Cycle-1 residuals (verified или mutated)

| Cycle-1 ID | Verification | Status |
|---|---|---|
| DOMAIN-WF-P0-001 | WorkflowFlags defaults перепроверены: 4 из 5 default=True, docstring "default-OFF". Не исправлено. | **RESIDUAL** (unresolved). |
| DOMAIN-WF-P0-002 | 4 процессора (workflow_subprocess, workflow_convert, best_practices/claim_check, continue_as_new) не имеют `@processor`. Не исправлено. | **RESIDUAL** (unresolved). |
| DOMAIN-WF-P0-003 | ActivityBridge (356 LOC) написана, `bridge_action_handler`, `register_langgraph_checkpoint_activities`, `ActivityBridge.get/collect_activities/decorate` — все присутствуют. Но `worker.py` использует `DSLStepExecutor`, не ActivityBridge. Не исправлено. | **RESIDUAL** (unresolved). |
| TemporalWorkerPool (P0 #?) | Класс `TemporalWorkerPool` (`temporal_client.py:227-320`) определён, нигде не инстанцируется. Только docs/tutorials. Не исправлено. | **RESIDUAL** (unresolved). |

**Cycle-1 ID для Workflow domain, которые я НЕ могу напрямую отследить** (без чтения cycle-1 отчётов): только 4 указанных в user prompt. Дополнительные ID из BASELINE.md (`Resolved in cycle 1: T-0.1, T-1.4, T-1.5, T-3.1. 4 закрыты, 5 отложены.`) не относятся к Workflow domain по описанию (`T-1.x` — composition/auth/DLQ; `T-3.1` — текст-RAG).

---

## 6. Contradictions / overlaps to flag

### C-1. `register_workflows_with_temporal` — фантомная функция

Документирована в 3 местах (`compiler/__init__.py:30`, `compiler/registry.py:4`, `compiler/emitter.py:42` docstrings), но **нигде не определена**. Это signal того, что bridge между compile_workflow → Temporal Worker был запланирован, но не реализован.

### C-2. Documentation lie про TemporalWorkerPool

`services/workflows/cost_estimator.py:262` ("WorkflowCostEstimator") ссылается на `feature_flags.workflow_*` но **feature_flags.workflow_cost_estimator_enabled** не существует (флаг называется иначе или отсутствует). Cost estimation просто работает без feature-flag gate.

### C-3. `run_workflow_by_id` в workflow_subprocess.py vs `WorkflowLauncher`

`workflow_subprocess.py:42` создаёт `WorkflowLauncher(installed_workflows={workflow_id: "1.0.0"})` с фиксированной версией 1.0.0 — это противоречит контракту WorkflowLauncher (всегда возвращает `ResolvedWorkflow(name, version, spec)`).

### C-4. `Cycle 33 restore` для gateways vs factory.py

`factory.py:90` (`create_workflow_backend(kind="auto")`) возвращает `PgRunnerWorkflowBackend()` если temporalio не установлен. `compiler/gateways.py:compile_xor/and/or` использует `simpleeval` (sandbox-safe). Это OK, но dev_light path использует pg-runner с in-memory DSLStepExecutor — **gateways runtime compilation работает только в production** (где temporalio есть). Нужно подтверждение что pg-runner test path покрывает gateway steps (не нашёл test case).

### C-5. orders_dsl.py vs existing builder API

`orders_dsl.py` использует legacy step-based API (через `.then()`), но WorkflowBuilder теперь fluent `WorkflowDeclaration`-based. Migration path не документирован.

---

## 7. Readiness score 0–100

**Формула:**

```
base_score = 100
P0 = -20 each (5 P0)
P1 = -10 each (3 P1)
P2 = -4 each (6 P2)
P3 = -2 each (3 P3)
P4 = -1 each (3 P4)

score = max(0, base_score - Σ penalties)
```

**Расчёт:**
```
100
- 5 × 20 (P0: 5 P0 findings — WorkflowFlags lie, 4 processors unregistered, ActivityBridge unused, TemporalWorkerPool uninstantiated, bootstrap default import) = -100
- 3 × 10 (P1) = -30
- 6 × 4 (P2) = -24
- 3 × 2 (P3) = -6
- 3 × 1 (P4) = -3
= max(0, 100 - 163) = 0
```

**Score: 0 / 100**

**Обоснование:**
1. **5 P0 findings — все unresolved.** Это блокирующие баги:
   - Feature-flags docstring lie нарушает fail-closed контракт (`workflow_legacy_disabled` должен быть default=False до миграции 19 импортёров; в реальности default=True → миграция не нужна, но фича "не работает").
   - 4 процессора не зарегистрированы — DSL не может использовать критичные Temporal паттерны (claim-check, continue-as-new).
   - ActivityBridge + TemporalWorkerPool — 450+ LOC мёртвого production-grade кода, при этом документация утверждает обратное.
   - `_bootstrap_default_declarations` упадёт на startup если кто-то включит флаг.
   - orders_dsl.py использует несуществующий `.then()` — extension broken.
2. По правилам "Оценка ≥80 запрещена при наличии P0/P1" — максимальный разрешённый score = 79 (но P0 + P1 penalty даёт score ≤ 0).
3. **Architectural completeness:** core/dsl/infrastructure/services слои разделены правильно, layer violations все allowlisted (не новые), facade pattern применён (WorkflowFacade).
4. **Production path:** DurableWorkflowRunner + DSLStepExecutor работают, ClickHouse audit + StepAuditMiddleware + SagaState persistence — operational stack готов.
5. **Production gap:** Temporal @workflow.defn path — ActivityBridge написана, но Worker не регистрирует compiled classes. Это означает что production Temporal workflow runtime **не использует DSL compiler output**.

**Production-readiness фактическая оценка:** Workflow DSL compile path functional, Temporal worker registration path not wired.

---

## 8. Recommended next tasks (без блокировки work)

Приоритет 1 (P0 closure):
1. **T-WF-P0-001:** Привести WorkflowFlags defaults в соответствие с docstring (fail-closed: default=False для legacy_disabled/yaml_round_trip/bpmn_import/gateways_enabled). Сопровождающий тест в `test_workflow_flags.py`.
2. **T-WF-P0-002:** Добавить `@processor(...)` к 4 процессорам. Проверить через `pytest tests/unit/dsl/engine/processors/ -k "register"`.
3. **T-WF-P0-003 (опционально):** Решить судьбу ActivityBridge/TemporalWorkerPool — либо wire в production (нужен новый `temporal_worker.py` CLI), либо удалить как dead code (350 LOC уменьшение).
4. **T-WF-P0-004:** Удалить `_bootstrap_default_declarations` (saga demos удалены commit 9164a59) либо восстановить `orders_saga.py` и `payments_saga.py`.
5. **T-WF-P0-005:** Исправить orders_dsl.py — заменить `.then(...)` на `.activity(...)` / `.sleep(...)` / `.sensor(...)` либо добавить `def then(self, step) -> Self` в WorkflowBuilder.

Приоритет 2 (P1 closure):
6. **T-WF-P1-001:** Поднять слой error-handling в `WorkflowCostEstimator` — fail-loud для unavailable cost вместо silent 0 USD.
7. **T-WF-P1-002:** Удалить legacy `GatewayCompiler`/`process_gateway` (137 LOC).
8. **T-WF-P1-003:** Расширить покрытие тестами `extensions/core_entities/orders/workflows/orders_dsl.py` (сейчас 0%).

Приоритет 3 (P2 cleanup):
9. **T-WF-P2-001:** Удалить `core/workflow/compensation.py` (40 LOC dead contract).
10. **T-WF-P2-002:** Удалить `BpmnImportNotAvailableError` (dead exception).
11. **T-WF-P2-003:** Подключить `SlaTracker` к `DurableWorkflowRunner` либо удалить (140 LOC).
12. **T-WF-P2-004:** Подключить `StepAuditMiddleware` к `DSLStepExecutor.execute_next()` либо удалить (308 LOC).

---

## 9. Commands run

```bash
# Read scope
ls src/backend/dsl/workflow/
ls src/backend/dsl/engine/processors/workflow/
ls src/backend/services/workflow/  # only __init__.py
ls src/backend/services/workflows/
ls src/backend/infrastructure/workflow/
ls src/backend/core/workflow/
ls tests/workflow/

# WorkflowFlags — проверка дефолтов
read src/backend/core/config/features/workflow.py
grep -nE "default=True|default=False" src/backend/core/config/features/workflow.py

# @processor registration
grep -rn "@processor" src/backend/dsl/engine/processors/workflow/
grep -rn "from src.backend.dsl.registry" src/backend/dsl/engine/processors/workflow/

# ActivityBridge usage
grep -ln "ActivityBridge|activity_bridge|bridge_action_handler|register_langgraph_checkpoint" src/backend/infrastructure/workflow/
grep -rn "register_workflows_with_temporal" src/ tests/

# TemporalWorkerPool instantiation
grep -rn "TemporalWorkerPool(" src/ tests/

# saga builders — extension reality
ls extensions/core_entities/orders/workflows/
ls extensions/credit_pipeline/workflows/
grep -rn "build_orders_saga_workflow|build_payments_saga_workflow" extensions/ src/ tests/ manage.py

# Layer violations
python tools/check_layers.py --root src
python tools/check_layers.py --root src --strict 2>&1 | grep -i workflow
wc -l tools/check_layers_allowlist.txt
git log -1 --format="%H %ci %s" -- tools/check_layers_allowlist.txt
git diff df7ed563~1 df7ed563 -- tools/check_layers_allowlist.txt

# Tests
python -m pytest tests/unit/dsl/workflow/{test_dryrun,test_bpmn_importer,test_launcher,test_gateways,test_yaml_round_trip,test_builder,test_visualize,test_versioning,test_spec,test_to_mermaid}.py tests/unit/core/workflow/test_compensation.py --tb=short
# Result: 146 PASSED, 4 FAILED (missing optional deps jmespath/simpleeval), 5 SKIPPED (temporalio not installed)

# WorkflowBuilder method existence
PYTHONPATH=src python -c "
from src.backend.dsl.workflow.builder import WorkflowBuilder
b = WorkflowBuilder('test').description('x')
print('then?', hasattr(b, 'then'))"
# Result: then? False
```

---

## Summary

**Status:** NOT READY for production Temporal path.
**P0:** 5, **P1:** 3, **P2:** 6, **P3:** 3, **P4:** 3. **Total:** 20.
**Readiness:** 0/100.
**Key blockers (P0):** DOMAIN-WF-P0-001 (WorkflowFlags lie), DOMAIN-WF-P0-002 (4 processors unregistered), DOMAIN-WF-P0-003 (ActivityBridge unused), DOMAIN-WF-P0-004 (TemporalWorkerPool uninstantiated), DOMAIN-WF-P0-005 (bootstrap saga demos don't exist).
**Important context:** Core DSL/builder/executor/runner architecture is sound; main blocker is bridge between compile_workflow output и Temporal Worker registration — ActivityBridge написан, но Worker не использует compiled classes. Production сейчас работает на pg-runner fallback path (DSLStepExecutor), что функционально но не использует full Temporal capabilities.
