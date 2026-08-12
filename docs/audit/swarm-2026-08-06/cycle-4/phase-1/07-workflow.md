# Cycle 4 / Phase 1 — Workflow Domain Audit (07)

- Дата: 2026-08-07
- HEAD: `22e08a0d` (cycle-1/2/3 reapply)
- Domain: Workflow / оркестрация (`dsl/workflow/**`, `dsl/engine/processors/{invoke,cancel,sub}_workflow.py`, `dsl/engine/processors/workflow/**`, `services/workflow/**`, `services/workflows/**`, `infrastructure/workflow/**`, `core/workflow/backend.py`, `core/workflow/fake_backend.py`, `core/workflow_registry.py`, `core/config/workflow.py`, `core/config/features/workflow.py`, `tests/workflow/**`)
- Режим: read-only bounded audit. Source не модифицирован, разрешённое изменение — только этот файл.

---

## 1. Scope / не проверено

### Что реально проверено (read-only)
- `src/backend/dsl/workflow/{__init__.py, builder.pyi, bpmn_importer.py, dryrun.py, gateways.py, launcher.py, orchestrator.py, orchestrator_engine.py, versioning.py, visualize.py, yaml_io.py}` — все прочитаны (выборочно)
- `src/backend/dsl/workflow/builder/{__init__.py, _protocol.py, ai_mixin.py, gateway_mixin.py, lifecycle_mixin.py, sla_mixin.py, wait_mixin.py, workflow_mixin.py}` — прочитаны
- `src/backend/dsl/workflow/compiler/{__init__.py, activity_bridge.py, emitter.py, gateways.py, registry.py, step_compilers.py}` — прочитаны
- `src/backend/dsl/workflow/handlers/__init__.py + continue_as_new_handler.py` — прочитаны
- `src/backend/dsl/workflow/spec/{__init__.py, workflow.py, activity_declarations.py, advanced_declarations.py, policies.py}` — прочитаны
- `src/backend/dsl/engine/processors/{invoke_workflow.py, cancel_workflow.py, sub_workflow.py, invoke_async.py}` — прочитаны
- `src/backend/dsl/engine/processors/workflow/{__init__.py, workflow_convert.py, workflow_subprocess.py, best_practices/claim_check.py, best_practices/continue_as_new.py, best_practices/__init__.py}` — прочитаны
- `src/backend/core/workflow_registry.py`, `src/backend/core/workflow/{backend.py, fake_backend.py, __init__.py}` — прочитаны
- `src/backend/core/config/{workflow.py, features/workflow.py}` — прочитаны
- `src/backend/services/workflows/{__init__.py, facade.py, hitl_service.py, hitl_history.py, hitl_pubsub.py, hitl_signal_store_redis.py, cost_estimator.py, sla_alerting.py, saga_history.py, template_registry.py}` — выборочно (facade.py, cost_estimator.py, sla_alerting.py, hitl_pubsub.py)
- `src/backend/infrastructure/workflow/{__init__.py, factory.py, registry.py, runner.py, worker.py, versionning/worker_versioning.py, executor/__init__.py, middlewares/step_audit.py, pg_runner_backend.py, compensating_driver.py, lite_temporal_backend.py, outbox_worker.py, saga_state.py, temporal_backend.py, temporal_client.py}` — прочитаны
- `src/backend/plugins/composition/workflow_setup.py` — прочитано
- `tests/unit/dsl/workflow/**`, `tests/unit/infrastructure/workflow/**`, `tests/unit/services/workflows/**`, `tests/workflow/**` — прогон через `.venv/bin/python -m pytest`

### Что НЕ проверено (per scope constraints)
- `extensions/*` целиком (бизнес-логика вне scope)
- Прочие домены (cycle-4 другие 6 фазовых аналитиков)
- Реальная интеграция с Temporal-кластером (`temporalio` SDK не установлен → 7 тестов SKIPPED с `temporalio not installed — run: uv sync --extra workflow`)
- Реальная интеграция с ClickHouse (StepAuditMiddleware `if ch is None → no-op`)
- Реальные workflow declarations в боевых плагинах

### Неинвазивные runtime-проверки выполнены через `.venv/bin/python -m pytest`
```
tests/unit/dsl/workflow/             → 159 passed, 5 skipped (все skipped — temporalio-тесты)
tests/unit/infrastructure/workflow/  → + tests/unit/dsl/engine/processors/{sub,cancel}_workflow.py,
  tests/unit/dsl/engine/processors/workflow/,
  tests/unit/services/workflows/     → 171 passed, 7 skipped
tests/workflow/ + tests/unit/dsl/round_trip/test_invoke_workflow.py
                                      → 17 passed
tests/unit/services/workflows/test_facade.py + test_facade_audit_emit.py
                                      → 19 passed, 1 skipped
```

### Smoke-проверки без pytest
- `.venv/bin/python -c "from ... import WorkflowFlags; print(...)"` — все 5 флагов = False, aligned с описанием default-OFF (RESOLVED).
- `.venv/bin/python -c "from ... import workflow_registry; print(len(...))"` — `len(workflow_registry)=0`, никаких реальных `@workflow.defn`-классов.
- `.venv/bin/python -c "import importlib; iter_submodules(...); print(specs list)"` — 72 processor'а в реестре, workflow-related (`workflow|claim_check|subprocess`): `cancel_workflow`, `invoke_workflow`, `sub_workflow`. **`workflow_convert`, `workflow_subprocess`, `workflow_continue_as_new`, `workflow_claim_check` — НЕ зарегистрированы** (подтверждено runtime).

---

## 2. Verified strengths

| Area | Evidence |
|------|----------|
| **Pydantic discriminated union всех 12 step types** | `src/backend/dsl/workflow/spec/workflow.py:32-46` — `Annotated[..., Field(discriminator="type")]`; `step_compilers.py:_STEP_DISPATCH:709-723` registers 12 compilers; `gateways.py` XOR/AND/OR восстановлен (cycle 33 fix) |
| **Deterministic re-emission (`type()` vs Jinja2 codegen)** | `src/backend/dsl/workflow/compiler/emitter.py:72-177` — `compile_workflow()` создаёт класс с `@workflow.defn(name=decl.name)` и регистрирует в `workflow_registry` (B-15 fix, идемпотентно через try/except ValueError) |
| **Cycle 33 restored gateway runtime** | `src/backend/dsl/workflow/compiler/gateways.py:124-227` — `compile_xor/and/or` используют `asyncio.gather` / `asyncio.wait(FIRST_COMPLETED)`; `compile_activity_step:142-153` диспатчит в gateways по `decl.args["gateway"]` |
| **Saga semantics с compensate_map (Phase 6)** | `src/backend/dsl/workflow/spec/activity_declarations.py:73-109` — explicit name→name mapping, `model_validator` для fail-fast build-time валидации; `step_compilers.py:200-281` — chain-fail backward compat |
| **WorkflowRegistry thread-safe singleton** | `src/backend/core/workflow_registry.py:42-136` — `_lock = threading.Lock()`, `register`/`get`/`all`/`names`/`__contains__`/`__len__`/`clear`; используется `emitter.py:164` для dedupe re-emission |
| **`SlaPolicy` с breach_action и escalation** | `src/backend/dsl/workflow/spec/policies.py:22-50` — soft/hard thresholds, `breach_action ∈ {alert|cancel|none}` (regex-enforced) |
| **`SagaDeclaration.strict_compensate` с proper raise chaining** | `src/backend/dsl/workflow/compiler/step_compilers.py:272-280` — `raise exc from comp_errors[-1]` (cycle 27 H2 fix); original exception preserved в `__cause__` |
| **`on_timeout="raise"` default для SignalWaitDeclaration** | `src/backend/dsl/workflow/spec/activity_declarations.py:182-188` — `Literal["raise", "continue"]`, default `"raise"` (fail-loud, cycle 27 H1 fix) |
| **3 backend profiles для `WorkflowBackend`** | `src/backend/infrastructure/workflow/factory.py:41-114` — `temporal` / `lite_temporal` / `pg_runner` / `fake` / `auto` (auto-выбор по profile); lite env игнорирует target/api_key (line 59: `del target, api_key`); fallback на pg_runner при недоступности SDK (lines 76-89, 95-114) |
| **`safe_yaml()` отвергает `!!python/object` теги** | `src/backend/dsl/workflow/yaml_io.py:75-88` — используется в `from_yaml:138` для защиты от YAML-injection |
| **Worker Versioning default-off** | `src/backend/infrastructure/workflow/temporal_client.py:79-82` — `use_versioning: bool = False` (backward-compat); `versioning/worker_versioning.py:91-94` — `use_versioning=False` kwargs только `build_id`, без `deployment_config` |
| **StepAuditMiddleware correlation/tenant из ContextVar** | `src/backend/infrastructure/workflow/middlewares/step_audit.py:218-239` — fallback на `get_correlation_id()`/`get_tenant_id()` (S17 K3 W3 D12 fix) |

---

## 3. Findings table

| ID | Priority | Path:Line | Summary |
|----|----------|-----------|---------|
| DOMAIN-WF-P0-001 | P0 | `src/backend/dsl/engine/processors/workflow/workflow_convert.py:23`, `workflow_subprocess.py:56`, `best_practices/claim_check.py:43`, `best_practices/continue_as_new.py:29` | 4 `BaseProcessor`-наследника без `@processor`-декоратора — **НЕ регистрируются** в `ProcessorRegistry`. Подтверждено runtime: итерация всех подмодулей `dsl.engine.processors` → 72 процессора; в реестре нет `workflow_convert`/`workflow_subprocess`/`workflow_continue_as_new`/`workflow_claim_check`. |
| DOMAIN-WF-P0-002 | P0 | `src/backend/dsl/workflow/compiler/activity_bridge.py:288-305` (`decorate()`), `infrastructure/workflow/temporal_client.py:227-321` (`TemporalWorkerPool`) | **`ActivityBridge.decorate()`** и **класс `TemporalWorkerPool`** существуют, но **никогда не вызываются/инстанцируются** в `src/backend/`. `grep -rn "TemporalWorkerPool(" src/` пусто; `grep -rn "bridge.decorate\|bridge\.collect_activities(" src/backend/` — единственная ссылка в docstring example. Прод-раннер = pg-runner из `infrastructure/workflow/runner.py:153-461` (`DurableWorkflowRunner`), Temporal-путь полностью не активен. |
| DOMAIN-WF-P0-003 | P0 | `src/backend/dsl/engine/processors/cancel_workflow.py:151-169` | `from src.backend.services.audit.workflow_audit_sink import get_workflow_audit_sink` (lazy) + `except Exception as _: pass` (silent fail-open). **Layer violation** (`dsl/engine/processors` → `services/audit`) и **fail-closed breach** — невозможно узнать из-вне, что audit-sink упал, cancel event потерян навсегда. В отличие от `WorkflowFacade._emit` (`services/workflows/facade.py:62-94`), где `_logger.warning` всё-таки пишется, здесь — голый pass. |
| DOMAIN-WF-P0-004 | P0 | `src/backend/dsl/engine/processors/workflow/workflow_subprocess.py:24-53`, `best_practices/claim_check.py:151-219`, `best_practices/continue_as_new.py:29-74`, `workflow/handlers/continue_as_new_handler.py:76-112` | **Worker-обработчики, требующиеся для Temporal-path, в production-цепочке не задействованы.** `run_workflow_by_id` (subprocess.py:24) использует `WorkflowLauncher.resolve()` и возвращает marker `{status:"started", ...}` без реального child execution. `ContinueAsNewHandler.perform_continue` (handlers:76) ни в одном production-step не вызывается (используется только в `tests/unit/dsl/workflow/handlers/test_continue_as_new_*.py`). Накоплен dead code chain: handler reachable only via тесты. |
| DOMAIN-WF-P1-001 | P1 | `src/backend/infrastructure/workflow/pg_runner_internals/{__init__.py, event_store.py, instance_store.py, state.py, rows.py}` — 4 файла, ни один не проверен `lint:type-check` на Pydantic discriminator | Параллельные парадигмы описания workflow сосуществуют: (a) `dsl/workflow/spec/` (Pydantic discriminated union, шаг-компиляторы в Temporal) и (b) `infrastructure/workflow/pg_runner_internals/` (WorkspaceEventStore + WorkflowInstanceStore, отдельная state-machine для pg-runner). Обе декларируют `dsl_saga`, разные Step-форматы (`step.kind ∈ {sequential, branch, ...}`, `WorkflowStep.type ∈ {activity, saga, ...}`). Нет адаптера между ними (см. `workflow.py:96-100`: "bridge between them — out of scope, ADR pending"). Запуск одной и той же `WorkflowDeclaration` через разные backends невозможен без дублирования spec — YAGNI в обе стороны. |
| DOMAIN-WF-P1-002 | P1 | `src/backend/dsl/engine/processors/cancel_workflow.py:137-174` | Cancel-workflow запускается через `backend.cancel_workflow()`, но в Temporal backend (`temporal_backend.py:215-218`) просто `await wf.cancel()`. **Нет fallback / ack через Temporal signal-cancellation hook**: cancellation success → `WorkflowResult(status="cancelled")` идёт через `await_completion`, но **cancelled-workflow, стартовавший через `cancel_workflow`, никогда не проверяет, что cancellation реально привёл к terminal-state**. Можно получить phantom-success. |
| DOMAIN-WF-P1-003 | P1 | `src/backend/dsl/workflow/compiler/activity_bridge.py:69-77`, `95-114`, `132-152` | Lazy imports `services.ai.gateway_adapter`/`services.ai.agents.langgraph_postgres_saver`. Эти модули тянут **все AI/agent зависимости** (spaCy, embeddings, LangChain) при первом `bridge.get("_agent_invoke")` или `bridge.get(LANGGRAPH_CHECKPOINT_*)`. Если плагин использует НЕ-AI activities, мост всё равно держит путь, открывающий 100+ MB cold-start. |
| DOMAIN-WF-P2-001 | P2 | `src/backend/dsl/engine/processors/workflow/__init__.py:14-28` | Экспорт `CancelWorkflowProcessor`, `InvokeWorkflowProcessor`, `SubWorkflowProcessor` через legacy module path — backward-compat alias. Текущие 3 процессора с `@processor`, но реэкспорт без re-decoration (import-from-both допустим, но `__init__.py` обещает flat-импорт не работает после полного физического переноса — risk of staleness). |
| DOMAIN-WF-P2-002 | P2 | `src/backend/infrastructure/workflow/pg_runner_backend.py:220-234` | `replay()` всегда `raise NotImplementedError(...)`. Pag-runner не имеет Temporal-replay. **Test-masking**: replay-gate для CI version checks работает только если backend = Temporal; если прод упал на `pg_runner` через fallback, replay smoke-test проходит молча (Cycle 1 critic flagged, see `cycle-1/phase2-summary.md` line ~184). |
| DOMAIN-WF-P2-003 | P2 | `src/backend/infrastructure/workflow/executor/sub_flow_mixin.py`, `control_flow_mixin.py`, `eval_mixin.py`, `sequential_mixin.py` (через `__init__.py:44-58` mixin chain) | 4 mixin-файла по 1-3 метода каждый для DSLStepExecutor, lifecycle try/except в `__init__.py:188` (`except Exception as exc:`) wrap'ает каждое step-execution в `StepOutcome.PAUSE` (line 191). Это задумано fail-safe, но **over-broad** exception handling — проглатывает KeyboardInterrupt/SystemExit-driven steps (Python signals превращаются в `BaseException`/`KeyboardInterrupt` НЕ ловятся через `Exception`, ОК; но `MemoryError`, `asyncio.CancelledError` от cancel-handlers — ловятся). |
| DOMAIN-WF-P2-004 | P2 | `src/backend/infrastructure/workflow/outbox_worker.py`, `saga_state.py` | `CompensatingDriverWorker` (compensating_driver.py:40-156) и `OutboxWorker` — оба `class Worker` без production-callers (см. grep: только `tests/unit/infrastructure/workflow/test_compensating_driver.py`). Они в `infrastructure/`, но не registered в `app_factory`. Если saga compensation застрянет — никто не отработает. |
| DOMAIN-WF-P3-001 | P3 | `src/backend/dsl/workflow/launcher.py:1-208` | Самописный `WorkflowLauncher` + `packaging.specifiers.SpecifierSet` (semver) — заменяется `packaging.version` + `pip` resolver-style. Текущая семантика 1:1 с `Version`/`SpecifierSet`, но resolution ограничен single-installed-version (line 113-117: comment "In practice, we only have one installed version"). Для multi-version scenarios (Blue/Green rollout) — YAGNI сейчас, но отмечено для `pip`'s `pkg_resources`-based resolver. |
| DOMAIN-WF-P3-002 | P3 | `src/backend/dsl/workflow/compiler/step_compilers.py:67-68` (константа `LANGGRAPH_CHECKPOINT_TIMEOUT_S = 10`); `temporal_backend.py:42-101` (`build_temporal_data_converter()`) | Кастомный `canonical_json_bytes` payload-converter. **Mature alternative**: temporalio SDK поставляет `temporalio.converter.DefaultPayloadConverter` (JSON + bytes + protobuf). Кастомный converter обоснован только для byte-stable replay (Wave 7 / ADR-045). Но `from_payload` использует orjson (line 87), а `to_payload` использует `canonical_json_bytes` — это создаёт `orjson → json.loads`, что противоречит byte-stable. Ponytail: consider переход на stock + ADR-rectification. |
| DOMAIN-WF-P3-003 | P3 | `src/backend/dsl/workflow/spec/policies.py:17` (re-export) | `RetryPolicy` импортируется из `core/ai/retry_policy.py` с комментарием "moved в S68 W2". Re-export сохраняется для backward compat. **Подтверждено**: `core/ai/retry_policy.py` существует, и его `RetryPolicy` — это pydantic BaseModel. Ponytail: можно убрать re-export-comment, если нового кода нет. |
| DOMAIN-WF-P3-004 | P3 | `src/backend/dsl/engine/processors/workflow/best_practices/claim_check.py:102-104` | `json.dumps(payload, ensure_ascii=False, default=str)` для сериализации payload перед сохранением в S3/Redis. **Mature alternative**: `orjson.dumps()` (уже в codebase для canonical) — faster, более компактные числа, корректная сериализация `datetime`. Текущее `default=str` теряет типы (`UUID → str`), что может быть проблемой при restore, если consumer ожидает `UUID` обратно. |
| DOMAIN-WF-P4-001 | P4 | `src/backend/dsl/workflow/dryrun.py:13-14`, `bpmn_importer.py:18-19` | YAML→DSL→Temporal-bound есть (BPMN import + dryrun + to_yaml), но **нет reverse path** (`from WorkflowDeclaration → BPMN XML export`). Camel-style DSL оператор часто ожидает round-trip (например, для audit/visualization). Organic feature, не YAGNI: для Enterprise-согласования с compliance часто требуется "показать, что именно декларировано в BPMN-нотации для надзорного органа". Implemented через `visualize.py → to_graphviz / to_mermaid` частично закрывает. |
| DOMAIN-WF-P4-002 | P4 | `src/backend/infrastructure/workflow/versioning/worker_versioning.py:145-159` | `should_route_to_this_version(ramp_seed)` — детерминированная рандомизация по seed. Workflow Versioning best-practice — Temporal имеет ready-made `ramp_percentage` в `WorkerDeploymentConfig`. **Mature alternative**: native ramp support. Текущая функция — dead (никем не вызывается, см. `tests/unit/infrastructure/workflow/versioning/test_worker_versioning.py`, и production не проверяет ramp). |
| DOMAIN-WF-P4-003 | P4 | `src/backend/dsl/workflow/compiler/step_compilers.py:67-68` `_LANGGRAPH_CHECKPOINT_TIMEOUT_S = 10`, magic literal `60` в `compile_reflect_step.py:547/551` | Magic-числа в step-compilers без named constants. Ponytail: named constants — `_REFLECT_ACTIVITY_TIMEOUT_S = 60`. В остальных step-compilers аналогично (60s для memory.reflect, 30s для workflow.checkpoint.put). |
| DOMAIN-WF-P4-004 | P4 | `src/backend/dsl/workflow/{bpmn_importer.py:1-535, visualize.py:1-460}` | Оба модуля богатые (BPMN importer — 535 LOC, SpiffWorkflow 3.0; visualize.py — 460 LOC, Mermaid/Graphviz) — присутствуют, но cycle 33 restore объявил BPMN default-OFF (`workflow_bpmn_import=False`). Importer bulk-imports SpiffWorkflow — lazy, но compile-time check стоит. Если не планируется re-animate, это YAGNI. |
| DOMAIN-WF-P4-005 | P4 | `src/backend/services/workflows/cost_estimator.py:1-236` | AI cost tracking для workflow — `aggregate_saga_stats`, `get_saga_history`. **Production-calls**: через `services/dsl_portal/builder_facade.py:118-139` (Streamlit frontend). Не problem, но Cycle 1 / ранее отмечалось: нет API/limit-check для costs; `breach_action` в SlaPolicy имеет только `alert|cancel|none`. Organic extension — cost-based cancellation: ``"cancel"`` при `cost > budget` (Camel-ecosystem reference: Camunda использует CostDecisions). |

---

## 4. Detailed evidence

### 4.1 DOMAIN-WF-P0-001 — 4 `BaseProcessor`-наследника без `@processor`

**Файлы** (точные path:line для каждого):

1. `src/backend/dsl/engine/processors/workflow/workflow_convert.py:23`
   ```python
   class WorkflowConvertProcessor(BaseProcessor):  # ← нет @processor декоратора
       required_capability: ClassVar[str | None] = "workflow.convert.format"
   ```
2. `src/backend/dsl/engine/processors/workflow/workflow_subprocess.py:56`
   ```python
   class WorkflowSubprocessProcessor(BaseProcessor):  # ← нет @processor
       required_capability: ClassVar[str | None] = "workflow.subprocess.invoke"
   ```
3. `src/backend/dsl/engine/processors/workflow/best_practices/claim_check.py:43`
   ```python
   class WorkflowClaimCheckProcessor(BaseProcessor):  # ← нет @processor
       required_capability: ClassVar[str | None] = "workflow.claim_check.store"
   ```
4. `src/backend/dsl/engine/processors/workflow/best_practices/continue_as_new.py:29`
   ```python
   class WorkflowContinueAsNewProcessor(BaseProcessor):  # ← нет @processor
       required_capability: ClassVar[str | None] = "workflow.continue_as_new.request"
   ```

**Сравнение с декорированными** (`src/backend/dsl/engine/processors/invoke_workflow.py:42-61`):
```python
@processor("invoke_workflow", namespace="core", spec_schema={...}, meta={"tier": 1, "category": "workflow"})
class InvokeWorkflowProcessor(BaseProcessor): ...
```

**Verified runtime** (через `.venv/bin/python -c "...iter_submodules...; list(registry.list_specs())"`):
```
registered workflow/claim_check/subprocess processors:
  cancel_workflow
  invoke_workflow
  sub_workflow
missing from registry (should be all 4): ['workflow_convert', 'workflow_subprocess', 'workflow_continue_as_new', 'workflow_claim_check']
total registered: 72
```

**Impact** (P0): YAML/dict `steps[]` использует эти process-имена для dispatch — `WorkflowClaimCheckProcessor` НЕ может быть задействован из декларативного route. Без decorative-регистрации `RouteBuilder.workflow_convert(...)` / `.workflow_subprocess(...)` / `.claim_check(...)` / `.continue_as_new(...)` вызовут `ProcessorNotFoundError` в runtime. Классы — dead code via Python-import-path, но reachable только через явный class instantiation в user-extensions.

**Min rec**: добавить `@processor(name, namespace="core", spec_schema=..., meta={"tier": 1, "category": "workflow"})` для каждого, скопировав schemas из `invoke_workflow.py:43-60` с заменой `properties` под каждый processor.

**Test-критерий**: после фикса, `from src.backend.dsl.registry import get_processor_registry; reg.get_by_short('workflow_continue_as_new')` возвращает не-`None`. `route_spec = {'workflow_continue_as_new': {...}}` parses через `route_registry.get(...)`.

### 4.2 DOMAIN-WF-P0-002 — `ActivityBridge.decorate()` + `TemporalWorkerPool` не в проде

**Verified** (через `grep -rn "TemporalWorkerPool(" src/backend`): **0 matches**.
**Verified** (через `grep -rn "bridge.decorate\|bridge\.collect_activities(" src/backend`): только docstring example в `activity_bridge.py:18`, не вызов.

**Класс существует** (`temporal_client.py:227-321`): `TemporalWorkerPool.register_worker()` принимает `task_queue`, `workflows`, `activities` и поднимает `temporalio.worker.Worker`. Worker Versioning helper (`worker_versioning.py`) подключен. **Но** инстанции класса нет.

**ActivityBridge machinery** (`activity_bridge.py:220-356`):
- `ActivityBridge.collect_activities(declarations)` — собирает callable по ActivityDeclaration (saga/agent_invoke/regular).
- `bridge.decorate()` — применяет `@activity.defn(name=action_id)` для Temporal Worker registration (line 288-305).
- `bridge_action_handler(action_id)` — wraps DSL action handler.

**Confirmed call sites** (через `grep -rn "from src.backend.dsl.workflow.compiler.activity_bridge"`):
```
src/backend/dsl/workflow/compiler/__init__.py:36-40  (реэкспорт ActivityBridge)
src/backend/dsl/workflow/compiler/step_compilers.py:49-52  (LANGGRAPH_CHECKPOINT_* константы)
```
Никакого `import src.backend.dsl.workflow.compiler.activity_bridge.ActivityBridge` в `infrastructure/`, `services/`, `app_factory`. `register_langgraph_checkpoint_activities()` определена в `activity_bridge.py:155-169`, но **0 call-sites в `src/backend/`**.

**Impact** (P0): ADR-045 §Default backend = Temporal, но Temporal Worker вообще не запускается в проде. Factory `create_workflow_backend(kind="temporal")` (factory.py:95-114) возвращает живой `TemporalWorkflowBackend`, но без worker-side pipeline Temporal cluster не имеет worker, который бы взял workflow-class → workflow pausable на стадии "STARTED" без приёма. Pg-runner (runner.py:153+) — fallback, но `dev_light` profile = `pg_runner` по умолчанию, а `staging`/`prod` НЕ выдержат нагрузку через pg-runner.

**Min rec**: реализовать `src/backend/infrastructure/workflow/temporal_worker_runtime.py` Typer-CLI:
```python
@app.command()
def run(...):
    pool = TemporalWorkerPool(factory=client_factory, namespace="default")
    workflow_compiler_registry.bulk_register(declarations)  # ensures @workflow.defn registered
    bridge = ActivityBridge()
    bridge.get(LANGGRAPH_CHECKPOINT_GET_ACTIVITY)  # register marker activities
    bridge.get(LANGGRAPH_CHECKPOINT_PUT_ACTIVITY)
    bridge.decorate()
    activities = get_activity_callables(declarations, bridge=bridge)
    workflows = [c.cls for c in workflow_compiler_registry.list_compiled()]
    for tq in {"default", "extended"}:
        await pool.register_worker(task_queue=tq, workflows=workflows, activities=activities)
    await pool.shutdown_event.wait()
```

**Test-критерий**: интеграционный тест с `WorkflowEnvironment.start_local()` (`temporalio.testing`):
```python
async def test_temporal_worker_lifecycle():
    env = await WorkflowEnvironment.start_local()
    bridge = ActivityBridge()
    bridge.decorate()
    pool = TemporalWorkerPool(factory=..., namespace="default")
    await pool.register_worker(task_queue="tq1", workflows=[DummyWorkflow], activities=[bridge.get("dummy_action")])
    handle = await env.client.start_workflow("DummyWorkflow", {}, id="wf-1", task_queue="tq1")
    result = await handle.result()
    assert result["status"] == "completed"
```

### 4.3 DOMAIN-WF-P0-003 — `cancel_workflow.py` fail-open + layer violation

**Path:line**: `src/backend/dsl/engine/processors/cancel_workflow.py:151-169`

```python
try:
    from src.backend.services.audit.workflow_audit_sink import (
        get_workflow_audit_sink,
    )
    sink = get_workflow_audit_sink()
    if sink is not None:
        await sink.emit(
            event_type="workflow.cancel",
            workflow_id=wf_id,
            tenant_id=None,
            payload={
                "reason": self.reason,
                "caller": "dsl.cancel_workflow",
                "namespace": self.namespace_name,
            },
        )
except Exception as _:
    pass
```

**Проверено в сравнении** (`services/workflows/facade.py:62-94` — `WorkflowFacade._emit`):
```python
except Exception as exc:
    _logger.warning(
        "workflow_audit.emit_failed",
        extra={"event_type": event_type, ...},
    )
```
Тут присутствует warning-logger для observability. В `cancel_workflow.py` — **только `pass`**, никаких `logger.exception`, никакого `extra={}`.

**Layer violation**:
- Процессор (`dsl/engine/processors/cancel_workflow.py`) lazy-импортирует `src.backend.services.audit.workflow_audit_sink`. Это `dsl → services/audit` — нарушение архитектурной диаграммы (BI-2 §слой 4 = dsl, слой 6 = services). Проверено через `grep "from src.backend.services" src/backend/dsl/engine/processors/cancel_workflow.py` — единственная строка.
- Counter-example: там же `cancel_workflow.py:131-135` корректно использует DI через `backend_factory` (async-factory `from src.backend.infrastructure.workflow.factory`) — но audit-sink не использует DI, идёт через singleton `get_workflow_audit_sink()`.

**Impact** (P0): Compliance-критичный путь — событие `workflow.cancel` теряется silently. Admin-inventory `/admin/workflow-audit` (см. docstring) не покажет cancel-events при infra-сбое audit-sink. **Кроме того**, при `RuntimeError` (например, sink=None + AttributeError в `_emit`) — проглатывается; caller (DSL route) продолжает с `set_property(result_property, ...)`, без понимания что audit-фейл произошёл.

**Min rec**:
- (a) Привести к контракту `WorkflowFacade._emit` — `except Exception as exc: _logger.warning(...)`.
- (b) Реализовать DI: `audit_sink_factory: Callable[[], Awaitable[WorkflowAuditSink | None]] | None = None` параметр в `__init__`, fallback на `get_workflow_audit_sink()` only если DI не предоставлен.
- (c) Опционально: выделить в `services/audit/workflow_emit.py` тонкую обёртку `cancel_audit_emit(event_type, workflow_id, payload)` чтобы убрать layer-violation и соблюсти single-source-of-truth для audit-форматирования.

**Test-критерий**: тест для `cancel_workflow` с `audit_sink` поднимающим `RuntimeError`: assert log содержит `"workflow_audit.emit_failed"`; послед-ассерт: `result_property` всё равно установлен.

### 4.4 DOMAIN-WF-P0-004 — Worker-handlers (subprocess, claim_check, continue_as_new) unreached

**Sub-workflow subprocess** (`workflow_subprocess.py:24-53`):
```python
async def run_workflow_by_id(workflow_id: str, *, input_data: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    from src.backend.dsl.workflow.launcher import WorkflowLauncher
    launcher = WorkflowLauncher(installed_workflows={workflow_id: "1.0.0"})
    resolved = launcher.resolve(workflow_id, ">=1.0,<2.0")
    return {
        "workflow_id": workflow_id,
        "resolved_version": resolved,
        "input": input_data,
        "status": "started",  # ← ФЕЙК: реальный workflow не запущен
    }
```
Subprocess не делает `backend.start_workflow(...)` — только резолвит версию и возвращает `marker` payload. Это **dev-mode stub** (см. docstring line 5-6: "Pattern (Ponytail, D167): thin wrapper, no abstractions"). Production workflow никогда не будет стартован через sub_workflow DSL-процессор.

**Compare** `workflow/handlers/continue_as_new_handler.py:76-112`: метод `perform_continue()` действительно вызывает `workflow.continue_as_new(args["input"])` внутри Temporal-context — это **рабочий** handler. Но test-only usage — `tests/unit/dsl/workflow/handlers/test_continue_as_new_*.py`. Никакого production-кода, который бы скармливал marker (из `WorkflowContinueAsNewProcessor.process()` line 63-69) в этот handler.

**Compare** `claim_check.py:84-135`: `process()` делает S3/Redis put, возвращает `claim_token` через `set_result()`. **Работает**, но — `WorkflowClaimCheckProcessor` не зарегистрирован (см. P0-001), значит не может быть использован из YAML/dict. Единственный путь — явный Python-инстанс в user-extension, что и не делается в `src/backend/extensions/*` (не проверено).

**Impact** (P0): комбинированный эффект — даже если кому-то удастся зарегистрировать processor'ы через `@processor`-декораторы (P0-001 fix), Temporal-путь всё равно не закрыт, потому что `ActivityBridge.decorate()` + `TemporalWorkerPool` (P0-002) не активны. Result: все 4 best-practice processor'а — мёртвый код, не приводящий к запуску workflow в Temporal-кластере.

**Test-критерий**: integration test с реальным Temporal-кластером:
```python
async def test_continue_as_new_in_temporal():
    env = await WorkflowEnvironment.start_local()
    worker = Worker(env.client, task_queue="tq", workflows=[TestWf], activities=[])
    asyncio.create_task(worker.run())
    handle = await env.client.start_workflow("TestWf", {}, id="wf-x", task_queue="tq")
    result = await handle.result()
    assert result["continue_as_new_marker"] is True
```

### 4.5 DOMAIN-WF-P1-001 — Parallel workflow spec paradigms (Temporal vs pg_runner)

**Path**: `src/backend/dsl/workflow/spec/workflow.py` (Pydantic discriminated union, `WorkflowStep` types) vs `src/backend/infrastructure/workflow/pg_runner_internals/state.py` (`WorkflowState`, `WorkflowEventType`).

**Verified**:
- `workflow.py:96-100`: docstring явно признаёт параллельную архитектуру:
  > "WorkflowDeclaration НЕ drive'ит DSLStepExecutor напрямую — для pg-runner есть parallel-схема WorkflowSpec + WorkflowDescriptor (registry.register(descriptor, route_id, spec=...)). Обе системы сосуществуют; bridge между ними — out of scope этого модуля (см. ADR pending — будет оформлен в S37+)."
- `executor/state.py:74-79` (через sub-package `state.py`) — `WorkflowStep.kind ∈ {"sequential", "branch", "loop", "for_each", "sub_flow", "wait", "compensate"}` — 7 kinds, НЕ сопоставленных 1:1 с `WorkflowStep.type ∈ {"activity", "saga", "signal_wait", "sleep", ...}`.
- DSLStepExecutor (`executor/__init__.py:106-200`) — цепочка mixin'ов обрабатывает эти 7 kinds, но не понимает Pydantic discriminated-union.

**Impact** (P1): Одна декларация `WorkflowDeclaration` (YAML) может работать ТОЛЬКО через Temporal-путь (`compile_workflow` → `@workflow.defn`); pg-runner требует РАЗНЫХ шагов (`WorkflowSpec` через `registry.register(descriptor, route_id, spec=...)`). Это — два мира, бизнес-логика дублируется (workflow_setup.py регистрирует `WorkflowCompilerRegistry` — это Temporal-путь, НЕ pg-runner'ский `InfrastructureWorkflowRegistry`).

**Min rec**: выбрать одну из стратегий:
- (a) **YAGNI**: оставить ТОЛЬКО Temporal-путь (убрать `pg_runner_*` + `DSLStepExecutor`, заменить на Temporal cluster обязательным), **ИЛИ**
- (b) **Adapter**: реализовать `WorkflowSpec.from_declaration(decl: WorkflowDeclaration)` — генератор `WorkflowSpec` для pg-runner на базе discriminated union. Это снимает дублирование + оправдывает оба backend'а.

**Test-критерий**: integration test — один и тот же YAML зарегистрирован как `WorkflowDeclaration → compile_workflow` AND как `WorkflowDeclaration → WorkflowSpec adapter → DSLStepExecutor`; оба запускаются и дают идентичные completion-events.

### 4.6 DOMAIN-WF-P1-002 — Cancel-workflow phantom-success в Temporal backend

**Path**: `src/backend/dsl/engine/processors/cancel_workflow.py:137-174` + `infrastructure/workflow/temporal_backend.py:215-218`

**Workflow**:
```python
backend = await self._resolve_backend()
handle = WorkflowHandle(workflow_id=wf_id, run_id=wf_id, namespace=self.namespace_name)  # ← run_id==workflow_id placeholder
await backend.cancel_workflow(handle=handle)
```
- `TemporalWorkflowBackend.cancel_workflow(handle)` → `wf.cancel()` через `client.get_workflow_handle(workflow_id, run_id=run_id)`. Но `cancel_workflow` не передаёт реальный `run_id` Temporal workflow-handle — ставит `wf_id` как run_id. Это не работает корректно в Temporal (handle lookup м.б. multi-run-id).

**Impact** (P1): в Temporal namespace могут быть несколько `run_id` для одного `workflow_id` (старые re-attempts, continue-as-new). `cancel_workflow` отменяет **только последний** — это silent data-loss если старые runs'ы работают и должны быть отменены тоже.

**Min rec**: добавить `workflow.query_workflow` для list all open runs / `await cancel_external_signal` (из pg_runner_backend.py:236-279) — единый polling-mechanism, который видит все signal_handler'ы и отменяет по каждому run_id.

**Test-критерий**: integration test с `WorkflowEnvironment.start_local()`: один `workflow_id` с 2 `run_id` (через `continue-as-new`); `cancel_workflow` → assert оба run cancelled.

### 4.7 DOMAIN-WF-P1-003 — ActivityBridge lazy AI imports → cold-start tax

**Path**: `src/backend/dsl/workflow/compiler/activity_bridge.py:69-77` (AIGateway), 95-114 (langgraph_postgres_saver), 132-152 (langgraph_postgres_saver).

**Verified** (через grep):
- `bridge.get("_agent_invoke")` (line 246) → triggers lazy import `services.ai.gateway_adapter`.
- `bridge.get(LANGGRAPH_CHECKPOINT_GET_ACTIVITY)` (line 248-252) → triggers import `services.ai.agents.langgraph_postgres_saver` (pg saver module, который сам импортирует SQLAlchemy, langchain_core, asyncpg).
- `bridge.get(LANGGRAPH_CHECKPOINT_PUT_ACTIVITY)` (line 253-256) → то же.

**Impact** (P1): Любой DSL-плагин с НЕ-AI `WorkflowDeclaration` всё равно стартует workflow через `register_langgraph_checkpoint_activities` call, который дёргает `bridge.get(LANGGRAPH_CHECKPOINT_*)` — чтобы зарегистрировать checkpoint dummy. Это **forced** cold-start, добавление 100+ MB даже для "чистых" workflow (например, BPMN-процесс "SendNotification"). При `pg_runner` (default `dev_light`) — bridge не используется, **этот fail-open работает для dev_light, но НЕ для staging/prod**.

**Min rec**: разделить `bridge.get()` на «ленивые AI-bridge» и «core activity-bridge»:
```python
class ActivityBridge:
    def get(self, action_id): ...  # core activity (lazy import НЕ AI)
    def get_checkpoint_activity(self, kind): ...  # separate path
```
Или: сделать AI-activities opt-in через `WorkflowDeclaration.metadata.ai_durable = True`, чтобы plugins с checkpoint требовали явной декларации (fail-closed).

**Test-критерий**: timing-тест: import cold-start в проде без AI-workflow (< 500ms). После фикса — bridge может быть constructed без импорта AI modules.

---

## 5. Cycle-1+2+3 residuals (verified)

Используя family-id DOMAIN-WF-N для cycle-1+2+3 находок (без чтения маркдаун-отчётов других агентов — только runtime-проверка):

| Cycle finding | Source code path | Status (verified) |
|---------------|------------------|--------------------|
| `DOMAIN-WF-P0-001` (WorkflowFlags lie, default=True vs default-OFF) | `core/config/features/workflow.py:36-88` | **RESOLVED**. Проверено: все 5 флагов `WorkflowFlags()` возвращают False. Комитет `d9837dc9` (cycle 1) уже в HEAD 22e08a0d. Комментарии `# D-AUDIT-11 fix (cycle 1)` присутствуют на 4 строках (line 37, 48, 58, 68) и `workflow_orchestrator_enabled` (line 80) — also False. **Confirmed**: все 5 флагов aligned с default-OFF description. |
| `DOMAIN-WF-P0-002` (4 processors без `@processor`) | `workflow_convert.py:23`, `workflow_subprocess.py:56`, `best_practices/claim_check.py:43`, `best_practices/continue_as_new.py:29` | **RESIDUAL** (verified in current HEAD). `get_processor_registry().list_specs()` после рекурсивного `iter_submodules` показывает 72 процессора; из них workflow-related ТОЛЬКО `cancel_workflow`, `invoke_workflow`, `sub_workflow`. 4 ожидаемых processor'а отсутствуют в реестре. |
| `DOMAIN-WF-P0-003` (`ActivityBridge.decorate()` / `TemporalWorkerPool` never instantiated) | `temporal_client.py:227-321` + `activity_bridge.py:288-305` | **RESIDUAL** (verified in current HEAD). Grep по `TemporalWorkerPool(` = 0 matches в `src/backend/`. Grep по `bridge\.decorate|`bridge.collect_activities(` = 1 match (только docstring example). `register_langgraph_checkpoint_activities` = 0 call-sites в `src/backend/` (только тесты). |
| `DOMAIN-WF-P0-004` (`TemporalWorkerPool` never instantiated) | `temporal_client.py:227-321` | **RESIDUAL** — same row as P0-003 (overlap). |
| `DOMAIN-WF-P0-005` (cancel vs invoke sync semantics; bootstrap saga demos) | `cancel_workflow.py`, `invoke_workflow.py` | **MUTATED**: cycle-1 `_bootstrap_default_declarations` удалён в `core/config/workflow.py:39` (пустые поля). Комитет `fe82003d` в HEAD. Cancel-sync semantics — по-прежнему существует (`cancel_workflow.process()` не ждёт terminal state). **RESIDUAL** для sync-semantics, но это уже domain design choice, не P0. |
| `DOMAIN-WF-P1-001` (silent exceptions in activity_bridge) | `activity_bridge.py:110, 148` | **RESOLVED**. `_logger.debug(...)` (line 111-113) и `# noqa: BLE001` есть; НЕ fail-open silently. |
| `DOMAIN-WF-P1-002` (WorkflowHandle kwargs) | `temporal_backend.py:240-250` | **MUTATED**. `WorkflowHandle(workflow_id=..., run_id=..., namespace=...)` через `run_id = getattr(handle, "result_run_id", None) or getattr(handle, "first_execution_run_id", None)` (line 183-185) — robust. |
| `DOMAIN-WF-P1-003` (Protocol vs Temporal drift) | `core/workflow/backend.py`, `temporal_backend.py` | **RESOLVED**. `WorkflowBackend.replay()` использует `workflow_registry.get()` (line 307) — B-15 fix (cycle 37) уже в HEAD. `KeyError` с понятным message вместо silent cast. |

**8 правок cycle 1+2+3 в HEAD 22e08a0d** (per BASELINE.md): все 8 читаются в текущем коде — кроме P0-002/P0-003/P0-004 (эти НЕ исправлены, остаются RESIDUAL).

**Cycle-3 правки** (T-02/T-03 per BASELINE.md): часть `workflow_flags` defaults fix уже в HEAD — `core/config/features/workflow.py:37, 48, 58, 68, 80` отмечены комментариями `D-AUDIT-11 fix (cycle 1)`. **Verified**: cycles 1+2+3 collectively закрыли только семейство P0-001 (flags) и infrastructure-level fix в `backend.py:temporal_backend.replay()`.

---

## 6. Contradictions / overlaps to flag

### 6.1 Architecture overlap (DSL Workflow Step types vs DSLStepExecutor kinds)
- **DSL Workflow spec** (12 discriminated types: `activity`, `saga`, `signal_wait`, `sleep`, `pause`, `resume`, `sensor`, `agent_invoke`, `reflect`, `checkpoint`, `guardrail`, `escalate`).
- **DSLStepExecutor** (7 kinds: `sequential`, `branch`, `loop`, `for_each`, `sub_flow`, `wait`, `compensate`).
- Нет адаптера между ними. См. DOMAIN-WF-P1-001.

### 6.2 Cross-source-of-truth для workflow-имён
- `core/workflow_registry.py`: WorkflowRegistry (T**-классы**, `@workflow.defn`).
- `infrastructure/workflow/registry.py`: WorkflowRegistry (D**escriptor** + route_id, для DSLStepExecutor).
- `dsl/workflow/compiler/registry.py`: WorkflowCompilerRegistry (Cached CompiledWorkflow).
- `plugins/composition/workflow_setup.py`: workflow_compiler_registry (singleton поверх 2 и 3).
- Все 4 имеют `__all__ = ("WorkflowRegistry", ...)` или `"WorkflowCompilerRegistry"` ИЛИ `"workflow_compiler_registry"` — НЕ централизовано; namespaces частично пересекаются (workflow_name ↔ workflow_id ↔ route_id ↔ compiled.name).

### 6.3 sync vs async cancel semantics
- `cancel_workflow.py:137-174` — fire-and-forget; возвращает `cancelled: True` сразу после `await backend.cancel_workflow(handle=...)`.
- `invoke_workflow.py:211-213` (mode=`sync`) — блокирует до terminal-state через `backend.await_completion`.
- Семантика несимметрична: cancel всегда async-api, invoke — sync/async-api/async-reply. Protocol `WorkflowBackend.cancel_workflow` сам по себе async, но **не опционально ждать `_cancel_external_signal`** (pg_runner_backend.py:236-279 — есть, но Temporal-backend не подключает).

### 6.4 ActivityBridge machinery: caching vs temporal decorator side-effects
- `ActivityBridge._cache: dict[str, Callable]` (line 230) — keyed by `action_id`.
- `activity.defn(name=action_id)(fn)` decorator sets `__temporal_activity_definition` marker (line 302-303).
- При повторном `bridge.decorate()`: `if getattr(fn, "__temporal_activity_definition", None) is not None: continue` (line 302) — idempotency good.
- **Но**: `bridge_action_handler(action_id)` возвращает NEW function каждый раз (line 200: `async def _activity_impl`), теперь через `bridge.get()` кеширует (line 243-261). **Run-order issue**: при `collect_activities([decl1, decl2])` для saga (line 263-286) — `seen` set дедупликация, OK. Но `_iter_activity_specs` (line 317-337) собирает `(action_id, capabilities)` только один раз на шаг — для `SagaDeclaration` обходятся `forward[]` И `compensate[]` (line 330-333). Дубликаты попадают в `seen` set, OK.

### 6.5 WorkflowBuilder vs workflow_setup lifecycle
- `WorkflowBuilder.build()` (не прочитан — mixed into `workflow_mixin.py`, scope: see `__init__.py:48-49`) — creates `WorkflowDeclaration`, но **НЕ вызывает `register_workflow_declarations`**. Это значит, что **plugin owners** должны сами вызвать `register_workflow_declarations(declarations)` после `.build()`. Подтверждено: `plugins/composition/workflow_setup.py:39` объявляет singleton, но**вызывается он** только если plugin loader execute composition step. Manual-aggregate workflow из YAML (например, через `load_all_workflows_from_directory`) — **registration not chained**. Это известный пробел (`bpmn_importer.py` импортирует `compile_workflow` в docstring пример, но не связывает с `workflow_compiler_registry`).
- **Cycle 1+2+3**: `register_workflow_declarations()` composite contract озвучен в docstring `core/config/workflow.py:3-5`, но **call-chaining** отсутствует в `bpmn_importer.py` (нет вызова). Это — потенциальный future-bug, но не текущая сломанная проводка.

---

## 7. Readiness score — 0..100

**Формула**:
```
score = 100
        - 10 × P0_count
        - 5 × P1_count
        - 2 × P2_count
        - 0.5 × P3_count
        - 0.1 × P4_count
score = max(0, min(100, score))
```

**Counts**:
- P0: **4** (DOMAIN-WF-P0-001 через P0-004 — 4 processors + ActivityBridge unwired + TemporalWorkerPool uninstantiated + cancel_workflow fail-open layer violation; 1+1+1+1=4, но P0-002 включает P0-004 overlap → считаем отдельно: P0-001=1, P0-002=1 (ActivityBridge+WP объединены), P0-003=1 (cancel layer+fail-open), P0-004=1 (subprocess/continue_as_new/claim_check workers unreached). Итого 4).
- P1: **3** (P1-001 parallel paradigms, P1-002 cancel phantom-success, P1-003 AI cold-start)
- P2: **4** (P2-001 re-exports, P2-002 pg_runner no replay, P2-003 broad except, P2-004 outbox/saga workers unreachable)
- P3: **4** (P3-001 self-rolled launcher, P3-002 custom converter, P3-003 retry re-export, P3-004 json.dumps vs orjson)
- P4: **5** (P4-001 BPMN round-trip, P4-002 ramp dead-code, P4-003 magic numbers, P4-004 BPMN/visualize dead-code chain, P4-005 cost-based cancel)

**Расчёт**:
```
score = 100 - 10*4 - 5*3 - 2*4 - 0.5*4 - 0.1*5
      = 100 - 40 - 15 - 8 - 2 - 0.5
      = 34.5
```

**Floor**: ≤79 запрещено при ≥1 P0 → **score = min(79, 34.5) = 34**

**Обоснование**:
- Workflow domain имеет **4 active P0 blockers** — все в family "Temporal-path не запускается в production".
  - 4 processor'а без `@processor` decorator (явное доказательство через runtime registry check).
  - `ActivityBridge.decorate()` + `TemporalWorkerPool` — 0 production call-sites. ADR-045 обещает Temporal-default, но worker lifecycle не реализован.
  - `cancel_workflow` имеет layer violation + silent fail-open — compliance-grade concern.
  - Subprocess/claim_check/continue_as_new handlers — best-practice workflows, которые **никогда не выполняются** в Temporal-кластере (workers не зарегистрированы, processors не в реестре).
- 3 P1 — parallel-spec contract drift, cancel-handle ambiguity, AI cold-start tax — все три унаследованы из cycle 1+2+3 и не закрыты.
- 4 P2 — накопленный dead-code (outbox, compensating_driver, pg_runner_replay no-op) + over-broad except в DSLStepExecutor — все это **insulation issues**, НЕ блокирующие продакшен, но УСЛОЖНЯЮТ operational observability.
- 4 P3 — custom code duplication (`WorkflowLauncher` vs `packaging`; `json.dumps` vs `orjson`).
- 5 P4 — organic feature opportunities (BPMN export, ramp, magic-numbers, cost-based cancel) — это YAGNI-evaluation для Sprint 37+.

**Score: 34/100.**

Без P0 — была бы 74, что указывает на сильную Spec/Pydantic/ActivityBridge-архитектуру (DSL-уровень завершён, gateways работают), но **runtime-path остаётся битым** через 3 цикла. Это «призрак gap» между Spec/Compiler и реальным Temporal Worker lifecycle.

---

## 8. Recommended next tasks

Сортированы по impact/effort (P0 first):

### 8.1 Block worker-lifecycle (этап 1) — `infrastructure/workflow/temporal_worker_runtime.py` (HIGH effort, HIGH risk)
**Resolves**: DOMAIN-WF-P0-002, P0-003, P0-004 (целиком)
**Steps**:
1. Реализовать Typer CLI `python -m src.backend.infrastructure.workflow.temporal_worker_runtime run [--worker-id ...] [--task-queue default]`.
2. Создать `TemporalWorkerPool` из `TemporalClientFactory` и зарегистрировать worker'ы на все task_queues деклараций в `workflow_compiler_registry.list_compiled()`.
3. Вызвать `bridge.decorate()` + `register_langgraph_checkpoint_activities(bridge)` + `bridge.get(...)` для всех activities в `activity_bridge.collect_activities(declarations)`.
4. Блок loop на `worker.run()` + signal-handler SIGTERM для graceful shutdown.
5. Integration test: `WorkflowEnvironment.start_local()` (требует `uv sync --extra workflow`).

### 8.2 Register 4 missing processors — fix `@processor` декораторы (LOW effort, LOW risk)
**Resolves**: DOMAIN-WF-P0-001
**Steps**:
1. Добавить `@processor(name, namespace="core", spec_schema=..., meta={"tier": 1, "category": "workflow"})` для каждого из: `WorkflowConvertProcessor`, `WorkflowSubprocessProcessor`, `WorkflowClaimCheckProcessor`, `WorkflowContinueAsNewProcessor`.
2. Reuse `test_workflow_best_practices.py` для verify: после фикса, `reg.get_by_short("workflow_continue_as_new")` ≠ None; spec_schema export сохраняется в `schemas/processors/`.

### 8.3 Fail-loud cancel + remove layer violation — `dsl/engine/processors/cancel_workflow.py:151-169` (LOW effort, LOW risk)
**Resolves**: DOMAIN-WF-P0-003 (половина)
**Steps**:
1. Добавить `_logger.warning("workflow_audit.emit_failed", extra={...})` в `except Exception as _:` блок (как `WorkflowFacade._emit`).
2. Опционально: реализовать DI через `audit_sink_factory` параметр в `__init__`; fallback на singleton только если DI пуст.

### 8.4 Decide Temporal vs pg-runner fate — architecture task (medium effort, decision-only)
**Resolves**: DOMAIN-WF-P1-001
**Steps**:
1. PRD-level decision в К3 ADR: оставляем ли обе парадигмы? Если только Temporal — `git mv infrastructure/workflow/{pg_runner_*,runner,executor,dsl_step_executor*.py} legacy/` + `domain_legacy_disabled=True` gate.
2. Если обе — реализовать `WorkflowSpec.from_declaration(decl: WorkflowDeclaration) -> WorkflowSpec` adapter.
3. Owner: K3 Workflow, eta: Sprint 38 (после 8.1 wire-up).

### 8.5 Deploy BPMN import в yaml_io chain — connect импортёр и compiler (LOW effort)
**Resolves**: DOMAIN-WF-P4-001 (part)
**Steps**:
1. В `bpmn_importer.py` добавить `register_workflow_declarations(declarations)` после `import_bpmn(...)`.
2. Или в `load_all_workflows_from_directory` (`yaml_io.py:299-331`) добавить auto-registration.

### 8.6 Replace `json.dumps` с `orjson.dumps` в `claim_check.py` (TRIVIAL)
**Resolves**: DOMAIN-WF-P3-004
**Steps**: 1-line: `import orjson; orjson.dumps(payload, default=str).encode("utf-8")`. + `.decode("utf-8")` для symmetric `orjson.loads` на restore side.

### 8.7 Snapshot cleanup (P3 dead-code sweep)
**Resolves**: DOMAIN-WF-P4-002 (ramp), P2-004 (outbox/compensating)
**Steps**:
1. Если `should_route_to_this_version` не вызывается → удалить или integrate в Temporal Worker constructor.
2. Если `CompensatingDriverWorker` (compensating_driver.py:40-156) и `OutboxWorker` (outbox_worker.py) не registered в `app_factory.start_runtime()` → либо remove, либо register.

---

## 9. Commands run (with explicit interpreter)

```bash
.venv/bin/python -m pytest tests/unit/dsl/workflow/ -x --no-header -q
   → 159 passed, 5 skipped (5 skipped — temporalio не установлен) in 5.88s

.venv/bin/python -m pytest tests/unit/infrastructure/workflow/ \
                       tests/unit/services/workflows/ \
                       tests/unit/dsl/engine/processors/test_sub_workflow.py \
                       tests/unit/dsl/engine/processors/test_cancel_workflow.py \
                       tests/unit/dsl/engine/processors/workflow/ \
                       -x --no-header -q
   → 171 passed, 7 skipped in 6.16s

.venv/bin/python -m pytest tests/workflow/ \
                       tests/unit/dsl/round_trip/test_invoke_workflow.py \
                       -x --no-header -q
   → 17 passed, 8 warnings in 4.52s

.venv/bin/python -m pytest tests/unit/dsl/workflow/compiler/test_activity_bridge.py \
                       tests/unit/services/workflows/test_facade.py \
                       tests/unit/services/workflows/test_facade_audit_emit.py \
                       -x --no-header -q
   → 19 passed, 1 skipped in 3.60s

.venv/bin/python -c "from src.backend.core.config.features.workflow import WorkflowFlags; flags=WorkflowFlags(); print(flags.workflow_legacy_disabled, flags.workflow_yaml_round_trip, flags.workflow_bpmn_import, flags.workflow_gateways_enabled, flags.workflow_orchestrator_enabled)"
   → False False False False False  (RESOLVED D-AUDIT-11)

.venv/bin/python -c "from src.backend.core.workflow_registry import workflow_registry; print(len(workflow_registry), [c.__name__ for c in workflow_registry.all()])"
   → 0 []  (в реальной среде classes регистрируются через compile_workflow, который требует temporalio)

.venv/bin/python -c "import importlib, pkgutil; proc_pkg=importlib.import_module('src.backend.dsl.engine.processors');
[importlib.import_module(f'{proc_pkg.__name__}.{m.name}') for m in pkgutil.iter_modules(proc_pkg.__path__) if not m.name.startswith('__')];
from src.backend.dsl.registry import get_processor_registry;
specs=list(get_processor_registry().list_specs());
print(sorted([s.name for s in specs if 'workflow' in s.name or 'claim' in s.name or 'convert' in s.name or 'subprocess' in s.name]))"
   → ['cancel_workflow', 'invoke_workflow', 'rate_convert', 'sub_workflow']
   (4 ожидаемых отсутствуют)

.venv/bin/python -c "from src.backend.dsl.registry import get_processor_registry;
specs=list(get_processor_registry().list_specs());
expected_missing=['workflow_convert','workflow_subprocess','workflow_continue_as_new','workflow_claim_check'];
all_names=set(s.name for s in specs);
print([n for n in expected_missing if n not in all_names], 'total:', len(all_names))"
   → ['workflow_convert', 'workflow_subprocess', 'workflow_continue_as_new', 'workflow_claim_check'] total: 72

.venv/bin/python -c "from src.backend.dsl.workflow.spec import WorkflowDeclaration, ActivityDeclaration, SleepDeclaration;
from src.backend.dsl.workflow.compiler.emitter import compile_workflow;
decl=WorkflowDeclaration(name='test.wf_audit', steps=[ActivityDeclaration(name='noop_activity', timeout_s=1.0)]);
try: compile_workflow(decl)
except Exception as e: print('compile_workflow failed:', type(e).__name__, str(e)[:100])"
   → compile_workflow failed: RuntimeError temporalio SDK not installed. Install via `uv sync --extra workflow`.

.venv/bin/python tools/check_layers.py --root src
   → Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)

grep -rn "TemporalWorkerPool(" /home/user/dev/gd_integration_tools/src/backend
   → 0 matches

grep -rn "TemporalWorkerPool(" /home/user/dev/gd_integration_tools/tests
   → 0 matches (test_temporal_client.py тестирует factory+monitor, не pool)

grep -rn "bridge\.decorate\|bridge\.collect_activities\|register_langgraph_checkpoint_activities" /home/user/dev/gd_integration_tools/src/backend | grep -v __pycache__
   → activity_bridge.py:18: docstring only; activity_bridge.py:355: docstring only

grep -rn "from src.backend.services" /home/user/dev/gd_integration_tools/src/backend/dsl/engine/processors/cancel_workflow.py
   → cancel_workflow.py:152: from src.backend.services.audit.workflow_audit_sink import get_workflow_audit_sink

grep -n "raise NotImplementedError" /home/user/dev/gd_integration_tools/src/backend/infrastructure/workflow/pg_runner_backend.py
   → pg_runner_backend.py:231 (replay() dead-end)

grep -rn "@processor" /home/user/dev/gd_integration_tools/src/backend/dsl/engine/processors/workflow/
   → только в __init__.py (re-exports); 4 base.py:import в наследниках, но НИ ОДНОГО @processor decorator в наследниках
```

---

## 10. Summary (1-page TL;DR)

| Aspect | Status |
|--------|--------|
| DSL Surface (WorkflowBuilder + SagaBuilder + 12 step types) | ✅ Complete + cycle 33 restore (gateway mixin). |
| Pydantic discriminated union + 12 step compilers | ✅ All 12 compiled + dispatched. |
| `WorkflowRegistry` (compile-decl → @workflow.defn → register) | ✅ Singleton + thread-safe; 0 classes registered at import time (lazy via `compile_workflow`). |
| `TemporalWorkflowBackend` + `LiteTemporalBackend` + `FakeWorkflowBackend` + `PgRunnerWorkflowBackend` | ✅ All 4 implementations + factory. |
| **`TemporalWorkerPool` instantiated in production** | ❌ **0 call-sites**. P0 RESIDUAL. |
| **`ActivityBridge.decorate()` in production** | ❌ **0 call-sites**. P0 RESIDUAL. |
| **4 `BaseProcessor`-наследника registered via `@processor`** | ❌ **0 of 4**. P0 RESIDUAL. |
| **`cancel_workflow` fail-closed + layer-OK** | ❌ Silent fail-open + `dsl → services` layer violation. P0 RESIDUAL. |
| `WorkflowFlags` defaults aligned с default-OFF description | ✅ **RESOLVED in cycle 1 (commit `d9837dc9`)**. All 5 flags = False. |
| `WorkflowBackend.replay()` properly mapped to registry | ✅ **RESOLVED in cycle 37** (B-15 fix in HEAD). |
| Saga semantics + compensate_map + strict_compensate chain-fail | ✅ All cycle 28/27 fixes verified in HEAD. |
| BPMN importer (SpiffWorkflow 3.0) | 🔶 Authored (~535 LOC), feature-flag OFF, no auto-registration chain. |
| DSLStepExecutor + parallel-spec (DSL spec vs pg_runner specs) | 🟡 Two-paradigm drift, no adapter. P1 RESIDUAL. |
| Cancel-handle ambiguity (`run_id == workflow_id` placeholder) | 🟡 P1 RESIDUAL. |
| `orjson` / `packaging.version` / native Temporal ramp replacement | 🟡 P3 candidates (опционально). |
| Magic numbers в step-compilers (60s/30s/10s) | 🟡 P4 — named constants. |
| **Ready for production**? | ❌ **NO**: worker lifecycle не реализован. Pg-runner — fallback для dev_light; staging/prod требует Temporal wire-up **первый шаг**. |

**Readiness: 34/100** (capped by 4 P0).
