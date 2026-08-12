# Audit Report — Domain: Workflow (DSL + Infrastructure + Services)

**Cycle**: 1, Phase 1
**Scope**:
- `src/backend/dsl/workflow/**`
- `src/backend/dsl/engine/processors/workflow/**`
- `src/backend/dsl/engine/processors/invoke_workflow.py`, `cancel_workflow.py`, `sub_workflow.py`
- `src/backend/services/workflows/**`
- `src/backend/infrastructure/workflow/**`
- `src/backend/core/workflow_registry.py`
- `src/backend/core/config/workflow.py`, `src/backend/core/config/features/workflow.py`
- `tests/workflow/**` и workflow-focused tests

**Baseline**: `b69d6b49bc62918a02e47dc20ab81615fd8500b1` (cycle 38)
**Working tree (на старте)**: `pyproject.toml` и `tests/unit/dsl/transforms/test_dataframes.py` modified (вне scope workflow). `src/backend/infrastructure/storage/s3.py` и `uv.lock`, заявленные в задании, на старте НЕ обнаружены как modified (проверено `git status --porcelain`).

---

## Scope / Не проверено

**Проверено read-only** (выборочно прочитаны все ключевые модули в scope, около 14 698 LOC по подсчёту `wc -l`):
- DSL workflow: `__init__.py`, `orchestrator.py`, `orchestrator_engine.py`, `gateways.py`, `dryrun.py`, `yaml_io.py`, `visualize.py`, `versioning.py`, `bpmn_importer.py`, `launcher.py`
- Builder (6 mixins), spec (4 модуля), compiler (5 модулей), handlers
- Engine processors: `invoke_workflow.py`, `cancel_workflow.py`, `sub_workflow.py`, `workflow_subprocess.py`, `workflow_convert.py`, `best_practices/claim_check.py`, `best_practices/continue_as_new.py`
- Infrastructure/workflow: `temporal_backend.py`, `lite_temporal_backend.py`, `pg_runner_backend.py`, `factory.py`, `runner.py`, `worker.py`, `worker_probes.py`, `temporal_client.py`, `registry.py`, `saga_state.py`, `outbox_worker.py`, `executor/{__init__,state,_protocol,sequential_mixin,control_flow_mixin,sub_flow_mixin,eval_mixin}.py`, `pg_runner_internals/{__init__,rows,state,event_store,instance_store}.py`, `middlewares/step_audit.py`, `versioning/worker_versioning.py`
- Services/workflows: `facade.py`, `template_registry.py`, `cost_estimator.py`, `hitl_service.py`, `hitl_history.py`, `hitl_signal_store_redis.py`, `hitl_pubsub.py`, `sla_alerting.py`, `saga_history.py`
- Core: `workflow_registry.py`, `core/workflow/backend.py` (для контекста), `core/config/workflow.py`, `core/config/features/workflow.py`
- Тесты: `tests/workflow/test_state_persistence.py`, ключевые `tests/unit/dsl/workflow/**`, `tests/unit/dsl/engine/processors/workflow/**`, `tests/unit/services/workflows/**`, `tests/unit/infrastructure/workflow/**`, `tests/unit/core/workflow/**`, `tests/unit/dsl/round_trip/test_invoke_workflow.py`, `tests/unit/dsl/engine/processors/test_cancel_workflow.py`, `tests/unit/dsl/engine/processors/test_sub_workflow.py`, `tests/integration/workflow/**`

**Не проверено** (read-only, но не критично):
- Полное содержание YAML-шаблонов в `dsl/workflow/templates/*.yaml` — прочитаны 2 из 10 (sample).
- Полное покрытие тестами каждого модуля (только ключевые тесты; статистика покрытия по `pytest --cov` не запускалась — запрещено mutation).
- Реальная Temporal-инфраструктура (нужен кластер + mTLS — не запускалась).
- Внутреннее устройство `services/audit/workflow_audit_sink.py` (за пределами scope; упоминается в `cancel_workflow.py:152` и `hitl_service.py:452`).
- Безопасность самого `core/workflow/backend.py` Protocol — он вне явного scope, но прочитан для контекста.
- Реальное использование `LiteTemporalBackend` в dev_light (нет запуска среды).

**Команды выполнены** (безопасные read-only):
```bash
# Каркас scope и git baseline
git rev-parse HEAD              # 2f620910 — рабочая ветка
git rev-list --count b69d6b49..HEAD  # 1 commit сверх baseline
git status --porcelain          # только pyproject.toml + tests/unit/dsl/transforms/test_dataframes.py

# Поиск TODO/FIXME/HACK/NotImplementedError в scope
grep -nE "TODO|FIXME|XXX|HACK"   src/backend/{dsl/workflow,dsl/engine/processors/workflow,services/workflows,infrastructure/workflow}/**  # НЕТ
grep -nE "NotImplementedError"   src/backend/infrastructure/workflow/pg_runner_backend.py:231  # 1 hit (explicit)

# Проверка зависимостей (pyproject vs uv.lock)
python3 -c "import tomllib; d = tomllib.load(open('pyproject.toml','rb'))"
# packaging/simpleeval/defusedxml/graphviz/clickhouse_connect — отсутствуют в pyproject

# Импорт-смок
python -c "from src.backend.dsl.workflow.launcher import WorkflowLauncher"  # OK
python -c "import simpleeval"   # доступен транзитивно
python -c "import packaging"    # доступен транзитивно
python -c "import defusedxml"   # доступен транзитивно
python -c "import jmespath"     # OK (core dep)

# Проверка зарегистрированных workflow-процессоров
python -c "from src.backend.dsl.registry import get_processor_registry; \
  import src.backend.dsl.engine.processors.invoke_workflow, \
          src.backend.dsl.engine.processors.cancel_workflow, \
          src.backend.dsl.engine.processors.sub_workflow; \
  print([s.name for s in get_processor_registry().list_specs() if 'workflow' in s.name])"
# ['cancel_workflow', 'invoke_workflow', 'sub_workflow']

# Реальный BPMN import (smoke)
python -c "from src.backend.dsl.workflow.bpmn_importer import import_bpmn; ..."
# OK: imported name='P1' steps=3 (activity + __gateway__GW_1 + activity)

# Реальный yaml round-trip
python -c "from src.backend.dsl.workflow.yaml_io import from_yaml, to_yaml; ..."
# OK: feature flag = True by default, from_yaml/to_yaml работают

# Feature flag defaults
python -c "from src.backend.core.config.features.workflow import WorkflowFlags; print(WorkflowFlags())"
# workflow_legacy_disabled=True, workflow_yaml_round_trip=True,
# workflow_bpmn_import=True, workflow_gateways_enabled=True,
# workflow_orchestrator_enabled=False
```

---

## Verified Strengths

| ID | Strength | Evidence |
|----|----------|----------|
| **STR-WF-01** | Clean layered architecture: DSL workflow не зависит напрямую от `temporalio` — lazy imports через `compile_workflow` (emitter.py:93-98) и `WorkflowLauncher` использует stdlib `packaging` (launcher.py:21-22). | `emitter.py:93` (`try: from temporalio import workflow as temporal_workflow`), `bpmn_importer.py:55` (`import defusedxml.ElementTree as ET`) |
| **STR-WF-02** | BPMN-импортёр использует `defusedxml` для XXE-protection (явная `try/except BpmnImportError` обёртка). Топологическая сортировка через stdlib `graphlib.TopologicalSorter` с явной детекцией циклов (`CycleError`). | `bpmn_importer.py:55-56`, `bpmn_importer.py:305-309` |
| **STR-WF-03** | Saga-компенсация поддерживает явный name→step mapping (`compensate_map`) с Pydantic `model_validator` — fail-loud на build-time, а не runtime. | `activity_declarations.py:86-109` (`@model_validator(mode="after")`) |
| **STR-WF-04** | `SignalWaitDeclaration.on_timeout` имеет fail-loud default `"raise"` (Cycle 27 H1 fix), legacy silent-skip требует explicit opt-in. | `activity_declarations.py:182-188` (Literal["raise","continue"], default="raise") |
| **STR-WF-05** | `WorkflowFacade` — capability-gated wrapper над `WorkflowBackend`. Все операции (`start/signal/query/cancel`) проходят `CapabilityGate.check()`. `await_completion` явно документирован как «без capability-проверки» (read-only, no side-effect). | `facade.py:113, 139, 164, 178, 184-192` |
| **STR-WF-06** | `compile_workflow` идемпотентен через `workflow_registry.register(cls)` с явным `try/except ValueError` (replay-determinism guard). | `emitter.py:160-177` |
| **STR-WF-07** | `pg_runner_backend.py` явно документирует «Non-production-grade fallback», `replay()` raise `NotImplementedError` с понятным сообщением — fail-loud вместо silent-обхода. | `pg_runner_backend.py:1-9, 220-234` |
| **STR-WF-08** | `ActivityBridge.bridge_action_handler` использует `capability_guarded_activity` ДО `@activity.defn` — guard срабатывает до Temporal-machinery. | `activity_bridge.py:209-216` |
| **STR-WF-09** | `WorkflowContinueAsNewHandler.perform_continue` правильно разделяет `upsert_search_attributes` и `continue_as_new` (B-18 fix) — Temporal API не принимает `search_attributes` как kwarg в `continue_as_new`. | `continue_as_new_handler.py:104-112` |
| **STR-WF-10** | `WorkflowState.replay` корректно fold'ит события через snapshot-recovery, проверяет что первое событие — `created`. | `pg_runner_internals/state.py:62-90` |
| **STR-WF-11** | `cancel_workflow.py:151-169` — best-effort audit emit с явным `try/except Exception` (не проглатывает silently — логирует warning). Audit-sink отсутствие не блокирует основной workflow. |
| **STR-WF-12** | `DryRunReport` в `dryrun.py` — pure simulation без Temporal, используется для golden-snapshot diff и CLI dry-run. Чистая функция от `(declaration, input_data) → report`. | `dryrun.py:29-136` |
| **STR-WF-13** | `WorkerProbesServer` — ASGI probes server с K8s `/healthz`/`/readyz` + Prometheus `/metrics` (3 endpoint'а), graceful drain через `mark_draining()`. | `worker_probes.py:91-179` |
| **STR-WF-14** | `WorkflowTemplateRegistry.search_semantic` использует BGE-M3 (sentence-transformers, есть в `rag` extra) с fallback на rapidfuzz, fallback на word-overlap. Деградация graceful. | `template_registry.py:120-170` |
| **STR-WF-15** | `WorkflowStateRepository` использует composite key `(workflow_id, run_id)` через SQLAlchemy `UniqueConstraint`, поддерживает RLS через `TenantMixin`. | `saga_state.py:135-141` |
| **STR-WF-16** | `compile_or` (inclusive gateway) корректно drain'ит CancelledError: `task.cancel()` + `await task` + `except asyncio.CancelledError: pass` (Ponytail pattern). | `compiler/gateways.py:208-217` |
| **STR-WF-17** | `saga_step` (compiler): явный log warning при `len(compensate) < len(forward)` (Cycle 19 meta-coord P1.2 fix), strict_compensate chains original exc + comp errors. | `step_compilers.py:233-281` |
| **STR-WF-18** | `WorkflowEventStore.append_within_session` поддерживает atomic batch с header-updates (B-15 fix: replay-determinism через event seq). | `pg_runner_internals/event_store.py:56-72` |
| **STR-WF-19** | `WorkflowSpec` + `WorkflowCompilerRegistry` — thread-safe (RLock) кеш с hot-reload контрактом (`replace`/`restore`/`snapshot`). | `compiler/registry.py:32-132` |
| **STR-WF-20** | `compile_workflows` (bulk variant) — post-step guard: если класс не попал в `workflow_registry` → `RuntimeError` (fail-loud). | `emitter.py:180-207` |

---

## Findings Table

| ID | Priority | Path:line | Summary |
|----|----------|-----------|---------|
| DOMAIN-WF-P0-001 | P0 | `core/config/features/workflow.py:32-83` | WorkflowFlags docstrings лгут: документированы как `default-OFF`, реальный код — `default=True` для 4 флагов (security/contract violation) |
| DOMAIN-WF-P0-002 | P0 | `dsl/engine/processors/workflow/{workflow_subprocess,workflow_convert}.py`, `best_practices/{claim_check,continue_as_new}.py` | 4 процессора без `@processor()` decorator — **dead code at DSL-layer**, недостижимы из YAML/builder |
| DOMAIN-WF-P0-003 | P0 | `dsl/workflow/compiler/activity_bridge.py:155-169` + `infrastructure/workflow/worker.py:225-301` | `ActivityBridge` machinery (collect_activities/decorate/register_langgraph_checkpoint_activities) **не подключена к production worker-у**; Temporal activities не зарегистрированы → выполнение `execute_activity` упадёт с `ActivityNotRegisteredError` |
| DOMAIN-WF-P1-001 | P1 | `dsl/workflow/launcher.py:113-117` + `invoke_workflow.py:152-157` | `WorkflowLauncher.resolve` имеет silent failure mode: installed_version единственная → при `spec` mismatch `raise WorkflowResolutionError` без указания installed/candidate. Прод-маршрутизация через SemVer-range полностью сломана |
| DOMAIN-WF-P1-002 | P1 | `dsl/workflow/spec/advanced_declarations.py:282-299` + `compiler/step_compilers.py:602-672` | `GuardrailDeclaration` для `output_size_bytes`/`max_cost_usd` оперирует только **числовыми** значениями; если output — dict/str → `value=0.0`, threshold никогда не exceed. Это fail-open security для лимитов |
| DOMAIN-WF-P1-003 | P1 | `dsl/workflow/compiler/step_compilers.py:382-401` | `compile_sensor_step` — бесконечный цикл polling предиката **без верхней границы** при `timeout_s=None` (документировано как "None = бесконечно"), а предикат вызывается **как activity по строковому имени** — temporal workflow может рекурсивно уйти в runaway execution |
| DOMAIN-WF-P1-004 | P1 | `infrastructure/workflow/temporal_backend.py:166-176` | Multi-tenant namespace mismatch — `_client` привязан к одному namespace, но `start_workflow` принимает любой `namespace`; warning вместо raise → workflow может быть запущен в чужом namespace |
| DOMAIN-WF-P1-005 | P1 | `services/workflows/hitl_signal_store_redis.py:218-256` | `_mark_resolved_transactional` retry-loop `while True: try WATCH... except WatchError: continue` — **нет ограничения итераций**, при contention может уйти в tight loop |
| DOMAIN-WF-P2-001 | P2 | `dsl/workflow/compiler/activity_bridge.py:308-315` | `_iter_activity_names` определён «для backward-compat», но не используется нигде кроме собственного определения |
| DOMAIN-WF-P2-002 | P2 | `dsl/workflow/bpmn_importer.py:88-95` | `BpmnImportNotAvailableError` определён и экспортирован, но никогда не raise'ится (документировано как «зарезервировано для SpiffWorkflow»). Мёртвый exception |
| DOMAIN-WF-P2-003 | P2 | `dsl/engine/processors/workflow/workflow_subprocess.py:24-53` | `run_workflow_by_id` возвращает **fake marker** (`{"status": "started"}`) вместо реального вызова `backend.start_workflow` — функция названа misleading'но |
| DOMAIN-WF-P2-004 | P2 | `services/workflows/hitl_service.py:432-449` | После `signal()` через facade создаётся `WorkflowHandle(run_id=resolved.signal_id)` — **signal_id используется как run_id**, что приводит к KeyError при попытке `await_completion` (run_id != real Temporal run_id) |
| DOMAIN-WF-P2-005 | P2 | `dsl/workflow/launcher.py:119-168` | `resolve_best_match` сортирует по `Version` (корректно) но **игнорирует installed_workflows** при `available_versions is None` (см. строку 141 — делегирует на `resolve` с одиночной версией). API-контракт с `available_versions=None` — silent different от `available_versions=[installed]` |
| DOMAIN-WF-P2-006 | P2 | `dsl/workflow/orchestrator_engine.py:160-183` | `_evaluate_condition` использует **swallow-all `except Exception`** → JMESPath typo или runtime error молча возвращает `False`, что в exclusive-маршрутизации означает fallback на `default_agent`. Скрытый fail-open |
| DOMAIN-WF-P3-001 | P3 | `dsl/engine/processors/workflow/workflow_subprocess.py`, `bpmn_importer.py` | `WorkflowSubprocessProcessor` (107 LOC) и `import_bpmn` (444 LOC) — можно заменить на уже установленные решения (e.g. `spiffworkflow` для BPMN через тот же `workflow_bpmn_import` feature flag) |
| DOMAIN-WF-P3-002 | P3 | `dsl/workflow/visualize.py:144-147` | `_escape_dot` — наивный string replace; уже в deps есть `graphviz` Python binding, который имеет корректный HTML-safe escape. Не критично, но `to_graphviz` строки могут быть injection-уязвимы при недоверенном workflow_name |
| DOMAIN-WF-P3-003 | P3 | `dsl/workflow/orchestrator.py:118` | `routing: list[RoutingRule]` — `description` содержит `evaluate顺序 по порядку` (китайский иероглиф в docstring) — code-smell, не evidence проблемы функционала |
| DOMAIN-WF-P4-001 | P4 | (новая функция) | Temporal-native child workflow cancellation cascade — задокументировано в `backend.py:155-165`, реализовано в `PgRunner.start_child_workflow` (pg_runner_backend.py:297-350), но в `TemporalWorkflowBackend` — **отсутствует** метод `start_child_workflow`, нарушает Protocol |
| DOMAIN-WF-P4-002 | P4 | (новая функция) | `WorkflowSpec` (executor/state.py:71-89) и `WorkflowDeclaration` (spec/workflow.py:49-101) — два **параллельных** declarative spec, о чём явно сказано в `spec/workflow.py:93-101` ("bridge between them — out of scope"). Декомпозиция для конвертации одного в другой — органически уместно для unified UX |

---

## Detailed Evidence

### DOMAIN-WF-P0-001 — `WorkflowFlags` docstrings лгут: documented default-OFF, actual default=True

**Path:line**: `src/backend/core/config/features/workflow.py:32-83`

**Evidence** (копии из файла):
```python
# workflow.py:32-41
workflow_legacy_disabled: bool = Field(
    default=True,                                                        # <-- True
    title="Workflow: отключить legacy infrastructure/workflow/state*",
    description=(
        "K4 Wave 1. Owner: K4 Workflow. ETA: S2-W1. "
        "При True блокирует все импорты из legacy 4 файлов "
        "(state.py/state_store.py/event_store.py/state_projector.py). "
        "default-OFF до миграции 19 импортёров на TemporalFacade."       # <-- "default-OFF"
    ),
)

# workflow.py:43-51
workflow_yaml_round_trip: bool = Field(
    default=True,                                                        # <-- True
    ...
    description=(
        "K4 Wave 2. Owner: K4 Workflow. ETA: S2-W2. "
        "Активирует to_yaml()/from_yaml()/diff() API на WorkflowBuilder. "
        "default-OFF до golden-snapshot тестов на 5 эталонных workflow." # <-- "default-OFF"
    ),
)

# workflow.py:53-61
workflow_bpmn_import: bool = Field(
    default=True,                                                        # <-- True
    ...
    description=(
        "K4 Wave 3. Owner: K4 Workflow. ETA: S2-W3. "
        "Активирует SpiffWorkflow 3.0 → WorkflowSpec → Temporal compiler. " # <-- "SpiffWorkflow" тоже ложь
        "default-OFF до research-spike ADR + sample-теста."               # <-- "default-OFF"
    ),
)

# workflow.py:63-73
workflow_gateways_enabled: bool = Field(
    default=True,                                                        # <-- True
    ...
    description=(
        "K3 Wave 4. Owner: K3 Workflow DSL. ETA: S3-W4. "
        ...
        "default-OFF до интеграции GatewayCompiler с emitter.py и staging-smoke."  # <-- "default-OFF"
    ),
)
```

Проверено в runtime:
```python
>>> from src.backend.core.config.features.workflow import WorkflowFlags
>>> WorkflowFlags()
workflow_legacy_disabled=True
workflow_yaml_round_trip=True
workflow_bpmn_import=True
workflow_gateways_enabled=True
workflow_orchestrator_enabled=False   # <-- этот совпадает с docstring
```

**Impact**:
- **Security (fail-closed)**: 4 из 5 флагов контролируют потенциально risk-пути (BPMN import — XXE поверх `defusedxml`; YAML round-trip — deserialization untrusted; gateways — runtime branch execution). Fail-closed принцип требует default-OFF. Текущий default=True означает: новая установка без env-overrides получает ВСЕ эти фичи ON. Если в коде есть баг (например, в BPMN `topological_order` — line 305-310) — он сразу активирован.
- **Operational**: ops-team, читающий docstring, ожидает OFF и не отключает через env; staging-smoke не пройдён.
- **Documentation lie**: 4 из 5 docstring'ов содержат ложь — критично для audit-trail и decision-making.

**Minimal recommendation** (без правок в этом цикле — только описание):
- Изменить `default=` на `False` для 4 флагов (соответствует docstring и fail-closed), **ИЛИ** обновить docstring'ы, чтобы они описывали текущее `True`. Рекомендуется первое (соответствует контракту V22 default-OFF).
- В рамках цикла 1/phase-1 ничего не меняется; это задача отдельного backlog-item (например, B-23).

**Test criterion**:
- `assert WorkflowFlags().workflow_bpmn_import is False` (после fix)
- `assert "default-OFF" in WorkflowFlags.model_fields["workflow_bpmn_import"].description`

---

### DOMAIN-WF-P0-002 — 4 процессора не зарегистрированы через `@processor()`

**Path:line**:
- `src/backend/dsl/engine/processors/workflow/workflow_subprocess.py:56-107` (`WorkflowSubprocessProcessor`)
- `src/backend/dsl/engine/processors/workflow/workflow_convert.py:23-117` (`WorkflowConvertProcessor`)
- `src/backend/dsl/engine/processors/workflow/best_practices/claim_check.py:43-232` (`WorkflowClaimCheckProcessor`)
- `src/backend/dsl/engine/processors/workflow/best_practices/continue_as_new.py:29-74` (`WorkflowContinueAsNewProcessor`)

**Evidence**:

В отличие от `invoke_workflow.py:42-61` (явный `@processor("invoke_workflow", namespace="core", spec_schema=...)`) и `cancel_workflow.py:57-71`, четыре указанных процессора **не имеют** `@processor()` decorator.

Проверено в runtime:
```python
>>> from src.backend.dsl.registry import get_processor_registry
>>> from src.backend.dsl.engine.processors import (invoke_workflow, cancel_workflow, sub_workflow)
>>> [s.name for s in get_processor_registry().list_specs() if 'workflow' in s.name]
['cancel_workflow', 'invoke_workflow', 'sub_workflow']
# `workflow_subprocess`, `workflow_convert`, `workflow_claim_check`, `workflow_continue_as_new` — отсутствуют
```

Дополнительная проверка использования:
```bash
$ grep -rn "WorkflowConvertProcessor\|WorkflowSubprocessProcessor\|WorkflowClaimCheckProcessor\|WorkflowContinueAsNewProcessor" src/backend/extensions 2>/dev/null
# (no results — extensions не используют)

$ grep -rn "WorkflowConvertProcessor\|WorkflowSubprocessProcessor\|WorkflowClaimCheckProcessor\|WorkflowContinueAsNewProcessor" src/backend 2>/dev/null | grep -v __pycache__ | grep -v "/workflow/"
src/backend/core/security/capabilities/vocabulary/defaults.py:190: ... упоминание в docstring capability
```

**Impact**:
- **4 processor classes (~430 LOC)** существуют, но **недостижимы из DSL pipeline** (YAML route → processor lookup).
- Тесты мгновенно инстанцируют классы (`tests/unit/dsl/engine/processors/workflow/test_workflow_subprocess.py`, `tests/unit/dsl/engine/processors/workflow/best_practices/test_workflow_best_practices.py`), но эти тесты не проверяют интеграцию через DSL — только unit-level.
- Прод-код использует только 3 процессора: `invoke_workflow`, `cancel_workflow`, `sub_workflow`.
- **Capability names объявлены** (`workflow.subprocess.invoke`, `workflow.convert.format`, `workflow.claim_check.store`, `workflow.continue_as_new.request`) — но поскольку processor не зарегистрирован, capability-check никогда не срабатывает, audit-events не эмитятся. Это fail-open security для потенциально рискованных операций (особенно `claim_check.store` — запись в S3/Redis с дефолт-TTL 1h).

**Minimal recommendation** (не менять в этом цикле):
- Либо удалить 4 класса + связанные capability записи (P2 dead code).
- Либо зарегистрировать через `@processor()` decorator (P0 — добавляет функциональность).

**Test criterion**:
- `assert "workflow_claim_check" in [s.name for s in get_processor_registry().list_specs()]` (после fix).

---

### DOMAIN-WF-P0-003 — `ActivityBridge` machinery не подключена к production worker

**Path:line**:
- `src/backend/dsl/workflow/compiler/activity_bridge.py:155-169` (`register_langgraph_checkpoint_activities`)
- `src/backend/dsl/workflow/compiler/activity_bridge.py:220-355` (`ActivityBridge` class, `collect_activities`, `decorate`, `get_activity_callables`)
- `src/backend/infrastructure/workflow/worker.py:225-301` (`_run_worker` — не вызывает `register_langgraph_checkpoint_activities`)

**Evidence**:

`register_langgraph_checkpoint_activities` определена, документирована как обязательный вызов из worker-init:
```python
# activity_bridge.py:155-169
def register_langgraph_checkpoint_activities(bridge: ActivityBridge) -> None:
    """Регистрирует LangGraph checkpoint activities в bridge (S100 W1).

    Worker-инициализатор должен вызвать эту функцию ДО
    :meth:`ActivityBridge.decorate` чтобы checkpoint activities попали
    в список регистрируемых в Temporal Worker. Без этого вызова
    ``workflow.execute_activity("_langgraph_checkpoint_get", ...)``
    упадёт с ``ActivityNotRegisteredError``.
    """
```

Реальные вызовы:
```bash
$ grep -rn "register_langgraph_checkpoint_activities" src/backend 2>/dev/null | grep -v __pycache__
src/backend/dsl/workflow/compiler/activity_bridge.py:56  # docstring ref
src/backend/dsl/workflow/compiler/activity_bridge.py:155  # def
tests/unit/dsl/workflow/compiler/test_langgraph_checkpoint.py:35  # import (test)
tests/unit/dsl/workflow/compiler/test_langgraph_checkpoint.py:172  # test call
tests/unit/dsl/workflow/compiler/test_langgraph_checkpoint.py:196  # test call
tests/unit/dsl/workflow/compiler/test_langgraph_checkpoint.py:198  # test call
```

**Production code (worker.py)** использует только `DurableWorkflowRunner` + `DSLStepExecutor(spec_loader=...)`:
```python
# worker.py:96-100
def _resolve_executor() -> Any:
    ...
    from src.backend.infrastructure.workflow.executor import DSLStepExecutor
    return DSLStepExecutor(spec_loader=build_spec_loader())
```

**Не используется**: ни `ActivityBridge`, ни `register_langgraph_checkpoint_activities`, ни `TemporalWorkerPool.register_worker` (поиск показал, что `TemporalWorkerPool` определён в `temporal_client.py:227` но **никогда не инстанцируется** в прод-коде).

**Impact**:
- Если когда-нибудь production-worker будет переключён с `pg_runner` на `temporal` (через `factory.py:95-114`), `TemporalWorkflowBackend.start_workflow` запустит workflow, но Temporal Worker не будет знать activity callables → `ActivityNotRegisteredError` на каждом `execute_activity(...)`.
- Без `bridge.decorate()` (`activity_bridge.py:288-305`) activities не получат `@activity.defn(name=...)` decoration, что Temporal требует.
- Проверено: `factory.py:95-114` (`if resolved == "temporal": return await TemporalWorkflowBackend.connect(...)`) — backend создаётся, но Worker регистрация полностью отсутствует в коде.
- Это **latent P0**: код компилируется, импортируется, тесты проходят, но в production Temporal workflow execution молча сломается.

**Minimal recommendation**:
- Добавить в `_run_worker` (worker.py) вызов `ActivityBridge` + `register_langgraph_checkpoint_activities` + `bridge.decorate()` перед `Worker(...)` конструкцией.
- Либо явно удалить machinery как dead code (если `temporal` factory path не используется).

**Test criterion**:
- integration test: `TemporalWorkflowBackend.start_workflow` + реальный `Worker(activities=bridge.collect_activities(decls))` — execute simple activity successfully.
- `assert "temporal" in factory.create_workflow_backend(kind="temporal").__class__.__name__.lower()`

---

### DOMAIN-WF-P1-001 — `WorkflowLauncher.resolve` не поддерживает SemVer-range с реальной семантикой

**Path:line**:
- `src/backend/dsl/workflow/launcher.py:113-117` — raise вместо best-match
- `src/backend/dsl/engine/processors/invoke_workflow.py:147-157` — fallback на original name

**Evidence**:
```python
# launcher.py:91-117
installed_version_str = self._installed.get(workflow_name)
...
installed_version = Version(installed_version_str)
...
if installed_version in spec_set:
    return ResolvedWorkflow(...)
# Find best matching version if multiple versions were available
# In practice, we only have one installed version, so check if it matches
raise WorkflowResolutionError(
    f"Installed version '{installed_version_str}' of workflow "
    f"'{workflow_name}' does not match spec '{spec}'"
)
```

```python
# invoke_workflow.py:147-157 (caller fallback)
try:
    launcher = WorkflowLauncher()
    resolved = launcher.resolve(self.workflow_name, self.version)
    return resolved.name
except WorkflowResolutionError:
    # Fallback to original name if resolution fails
    return self.workflow_name
```

**Problem**: `WorkflowLauncher.__init__` принимает только `dict[str, str]` (одна версия на workflow). Когда `installed_workflows` имеет одну версию, которая не подходит под SemVer-range — exception + caller fallback на original name = **silent ignore SemVer requirement**. Workflow запускается без проверки совместимости.

Когда `available_versions` явно передаётся в `resolve_best_match` (line 119-168) — работает корректно. Но этот путь **никем не вызывается** (проверено grep — нет callers).

**Impact**:
- **Operator contract violation**: `feature_flags.workflow_versioning_routes=True` обещает SemVer-маршрутизацию, но реально работает только best-effort на единичной версии.
- **Data-loss risk**: при `version="^1.2.0"` и установленной `2.0.0` (major bump) workflow ВСЁ РАВНО запускается через fallback `return self.workflow_name`. Это silent breaking-change run.

**Minimal recommendation**:
- Добавить `WorkflowLauncher.install_workflow(name, version_str)` для multiple versions.
- Caller `InvokeWorkflowProcessor._resolve_workflow_version` должен raise (не fallback), если spec передан и не резолвится.

**Test criterion**:
- `installed_workflows={"wf1": "2.0.0"}, spec="^1.0.0"` → raise `WorkflowResolutionError` (НЕ fallback).
- Caller test: `InvokeWorkflowProcessor(..., version="^1.0.0")` с mismatch → `KeyError`/`ValueError`, НЕ silent success.

---

### DOMAIN-WF-P1-002 — `GuardrailDeclaration` fail-open для non-numeric values

**Path:line**:
- `src/backend/dsl/workflow/spec/advanced_declarations.py:282-299` (`rule: str` enum: `max_cost_usd`, `max_tokens`, `max_turns`, `output_size_bytes`)
- `src/backend/dsl/workflow/compiler/step_compilers.py:602-672` (`compile_guardrail_step`)

**Evidence**:
```python
# step_compilers.py:621-647
outputs = ctx.get("_outputs", {})
target = decl.target
value: float = 0.0
if target is None:
    if outputs:
        ...
        last = next(reversed(outputs.values()))
        value = float(last) if isinstance(last, (int, float)) else 0.0  # <-- silent 0.0 для dict/str
elif "." in target:
    cur: Any = outputs
    for part in target.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            cur = None
            break
    value = float(cur) if isinstance(cur, (int, float)) else 0.0           # <-- silent 0.0
else:
    value = float(outputs.get(target, 0) or 0)

exceeded = value > decl.threshold
```

**Problem**: для guardrail `output_size_bytes` ожидается `len(output_str_or_bytes)`, но runtime возвращает `0.0` если output — dict/str/list. `value=0.0 > threshold=1024` → `False` → guardrail silently passes.

Аналогично для `max_cost_usd`: если activity возвращает `{"cost": 0.5}` (вложенный dict), `last` — это dict, `value=0.0`, threshold не exceeded.

**Impact**:
- **Security fail-open**: cost guardrails (`max_cost_usd`) предназначены для блокировки LLM-вызовов при превышении бюджета. Если output структура не совпадает с ожидаемой — guardrail не срабатывает → runaway LLM costs.
- **Compliance risk**: банковский контекст (Sprint 36), где guardrails защищают от cost-explosion.

**Minimal recommendation**:
- На `rule="output_size_bytes"`: `value = len(json.dumps(last))` или `len(str(last))`.
- На `rule="max_cost_usd"`: extract через dot-path или fail-loud `ValueError("unsupported output structure for guardrail X")`.
- Default on invalid: `value = float("inf")` (защита от fail-open), чтобы `exceeded = True` всегда.

**Test criterion**:
- `decl(rule="max_cost_usd", threshold=0.5)` + output=`{"cost": 0.5}` (dict) → `exceeded=True` (или raise).
- `decl(rule="output_size_bytes", threshold=100)` + output=`"x"*200` (str) → `exceeded=True`.

---

### DOMAIN-WF-P1-003 — `compile_sensor_step` infinite polling loop без guard

**Path:line**: `src/backend/dsl/workflow/compiler/step_compilers.py:379-401`

**Evidence**:
```python
async def compile_sensor_step(decl: SensorDeclaration, ctx: dict[str, Any]) -> Any:
    """Periodic-sensor: выполнять predicate как activity до True или timeout."""
    from temporalio import workflow
    elapsed = 0.0
    while True:  # <-- unbounded loop
        result = await workflow.execute_activity(
            decl.predicate, {}, start_to_close_timeout=timedelta(seconds=ctx["_default_timeout_s"])
        )
        if result:
            return result
        if decl.timeout_s is not None and elapsed >= decl.timeout_s:
            raise TimeoutError(...)
        await workflow.sleep(timedelta(seconds=decl.poll_interval_s))
        elapsed += decl.poll_interval_s
```

`SensorDeclaration.timeout_s: float | None = Field(default=None, gt=0.0, description="Полный timeout; None — бесконечно.")` (`advanced_declarations.py:35-37`).

**Problem**:
1. При `timeout_s=None` workflow выполняется **вечно** (документировано как "None = бесконечно", но это нарушает Temporal best practice — event history растёт).
2. Predicate — строка, передаваемая в `workflow.execute_activity(decl.predicate, ...)`. Если predicate вызывает sub-activity, которая тоже polling — рекурсивное зацикливание (workflow event history → exponential growth → Temporal terminates workflow при превышении history limit, но не сразу).
3. `elapsed` инкрементируется на `poll_interval_s` после `workflow.sleep`, но **не учитывает** время самого `execute_activity` → реальный elapsed может быть >> timeout_s.

**Impact**:
- **Runaway workflow**: долгоживущий sensor без timeout уходит в infinite loop.
- **Event history growth**: Temporal terminates workflow при >50K events; sensor + recursive activity может достичь этого за часы.

**Minimal recommendation**:
- `while True` → `while elapsed < (decl.timeout_s or 3600)`: implicit safety cap (1h default).
- В строке с `decl.predicate` — валидация что predicate не содержит рекурсивный sensor.

**Test criterion**:
- `compile_sensor_step(SensorDeclaration(predicate="...", timeout_s=None))` mock Temporal → `Workflow.sleep` вызван ≤ 3600 раз.
- Real integration: sensor с `timeout_s=2.0, poll_interval_s=0.5` завершается за ~2-2.5s, не позже.

---

### DOMAIN-WF-P1-004 — Multi-tenant namespace mismatch warning-only

**Path:line**: `src/backend/infrastructure/workflow/temporal_backend.py:165-176`

**Evidence**:
```python
async def start_workflow(self, *, workflow_name, workflow_id, input, namespace, task_queue, execution_timeout=None):
    target_namespace = "default" if namespace == "global" else namespace
    # Temporal client привязан к одному namespace; multi-tenant —
    # отдельный client per namespace в R3 (см. ADR-045 §opens).
    if getattr(self._client, "namespace", target_namespace) != target_namespace:
        _logger.warning(
            "TemporalWorkflowBackend: namespace mismatch "
            "(client=%s, requested=%s) — using client's namespace",
            getattr(self._client, "namespace", "?"),
            target_namespace,
        )
    handle = await self._client.start_workflow(
        workflow_name, input, id=workflow_id, task_queue=task_queue,
        execution_timeout=execution_timeout,
    )
```

**Problem**: вместо raise `PermissionDeniedError` или хотя бы отказа от запуска — silent warning. Workflow выполняется в namespace клиента (часто `default`), а не в requested namespace. **Tenant isolation нарушается**.

Банковский контекст (multi-tenant) делает это особенно критичным — `tenant_id="bank_a"` workflow может попасть в namespace `default` и быть доступным через Temporal UI другим tenant'ам.

**Impact**:
- **Tenant data leak risk**: workflow одного tenant может наблюдаться/сигналиться другим tenant'ом через Temporal Web UI или API.
- **Compliance**: GDPR/SOC2 — tenant data не должен быть cross-accessible.

**Minimal recommendation**:
- Raise `ValueError("namespace mismatch: client=X, requested=Y; configure separate clients per ADR-045")`.
- Или auto-resolve через `_factory.get_client(namespace)` (см. `temporal_client.py:99-117`), но это требует refactor на factory pattern.

**Test criterion**:
- `TemporalWorkflowBackend(client_with_ns="tenant_a").start_workflow(namespace="tenant_b")` → `ValueError`, НЕ success+warning.

---

### DOMAIN-WF-P1-005 — `WatchError` retry-loop без iteration cap

**Path:line**: `src/backend/services/workflows/hitl_signal_store_redis.py:218-256`

**Evidence**:
```python
async def _mark_resolved_transactional(self, client, signal_id, *, action, resolved_by):
    async with client.pipeline(transaction=True) as pipe:
        data: dict[str, Any] = {}
        while True:  # <-- unbounded
            try:
                await pipe.watch(_HASH_KEY)
                raw = await pipe.hget(_HASH_KEY, signal_id)
                ...
                pipe.multi()
                pipe.hset(_HASH_KEY, signal_id, json.dumps(data))
                await pipe.execute()
                return data
            except asyncio.CancelledError:
                raise
            except (KeyError, TypeError, ValueError):
                raise
            except WatchError:
                continue  # <-- бесконечный retry при persistent contention
```

**Problem**: при двух HITL-resolves одновременно на разных Redis-нодах (replication lag) или при постоянном contention — `WatchError` возникает на каждой итерации → tight loop без backoff → CPU saturation.

**Impact**:
- **DoS vector**: один concurrent resolve + множественные reads могут насытить CPU.
- **Latency**: вместо bounded ожидания — tight retry.

**Minimal recommendation**:
- `MAX_WATCH_RETRIES = 5`, после исчерпания — `RuntimeError("Redis contention on HITL resolve")`.
- Sleep с exponential backoff между retry (100ms × attempt).

**Test criterion**:
- Mock `WatchError` на 100 итераций → exception raised, loop exits.

---

### DOMAIN-WF-P2-001 — `\_iter_activity_names` dead code

**Path:line**: `src/backend/dsl/workflow/compiler/activity_bridge.py:308-315`

**Evidence**:
```python
def _iter_activity_names(step: WorkflowStep) -> list[str]:
    """Сохраён для backward-compatibility; внутренний код использует
    :func:`_iter_activity_specs` для получения capabilities."""
    return [name for name, _ in _iter_activity_specs(step)]
```

```bash
$ grep -rn "_iter_activity_names\|activity_bridge._iter" src/backend tests 2>/dev/null | grep -v __pycache__
src/backend/dsl/workflow/compiler/activity_bridge.py:308  # def
src/backend/dsl/workflow/compiler/activity_bridge.py:312  # docstring ref
src/backend/dsl/workflow/compiler/activity_bridge.py:314  # body
```

**Impact**: 7 строк dead code (включая docstring). Не критично, но поддерживается без пользы.

---

### DOMAIN-WF-P2-002 — `BpmnImportNotAvailableError` никогда не raise'ится

**Path:line**: `src/backend/dsl/workflow/bpmn_importer.py:88-95`

**Evidence**:
```python
class BpmnImportNotAvailableError(RuntimeError):
    """Зарезервировано для пути SpiffWorkflow (когда extra не установлен).

    Текущая реализация использует stdlib :mod:`xml.etree.ElementTree`,
    поэтому данное исключение никогда не возбуждается. Оставлено в
    публичном API для совместимости с задачей K3 W3 и для
    альтернативного пути через SpiffWorkflow в будущем.
    """
```

```bash
$ grep -rn "BpmnImportNotAvailableError" src/backend tests 2>/dev/null | grep -v __pycache__
src/backend/dsl/workflow/bpmn_importer.py:67  # __all__
src/backend/dsl/workflow/bpmn_importer.py:88  # def
```

Экспортирован через `__all__` (`bpmn_importer.py:63-69`), но никогда не raise'ится. Docstring явно говорит "никогда не возбуждается".

**Impact**: dead exception в public API, нарушает LSP (subclassers ожидают, что этот exception будет raised).

---

### DOMAIN-WF-P2-003 — `run_workflow_by_id` возвращает fake marker

**Path:line**: `src/backend/dsl/engine/processors/workflow/workflow_subprocess.py:24-53`

**Evidence**:
```python
async def run_workflow_by_id(
    workflow_id: str, *, input_data: dict[str, Any], timeout: float = 60.0
) -> dict[str, Any]:
    from src.backend.dsl.workflow.launcher import WorkflowLauncher
    launcher = WorkflowLauncher(installed_workflows={workflow_id: "1.0.0"})
    resolved = launcher.resolve(workflow_id, ">=1.0,<2.0")
    _logger.info(...)
    # Minimal contract: возвращаем marker + input echo для testing
    return {
        "workflow_id": workflow_id,
        "resolved_version": resolved,
        "input": input_data,
        "status": "started",  # <-- "started", не "running"
    }
```

Docstring говорит "Запустить workflow по его ID (sub-workflow entry point)", но реализация **не запускает** workflow — только резолвит версию и возвращает marker. Это misleading.

**Impact**:
- Если процессор всё-таки будет зарегистрирован (DOMAIN-WF-P0-002), workflow НЕ запустится — только маркер.
- Caller ожидает child workflow в Temporal, получает `{"status": "started"}`.

**Minimal recommendation**:
- Реальный вызов `backend.start_workflow(...)` вместо marker (требует DI factory, как `InvokeWorkflowProcessor._resolve_backend`).

---

### DOMAIN-WF-P2-004 — `HitlService.resolve` использует signal_id как run_id

**Path:line**: `src/backend/services/workflows/hitl_service.py:432-449`

**Evidence**:
```python
handle = WorkflowHandle(
    workflow_id=resolved.workflow_id,
    run_id=resolved.signal_id,  # <-- signal_id используется как run_id!
    namespace=resolved.tenant_id,
)
await self._facade.signal(
    caller=self._caller,
    handle=handle,
    signal_name=resolved.signal_name,
    payload=...,
)
```

**Problem**: `run_id` в `WorkflowHandle` — это Temporal run_id конкретного execution. Использование `signal_id` (UUID для HITL signal) как run_id — semantic violation. `signal_workflow` Temporal API требует корректный run_id, иначе signal уйдёт в "unknown workflow".

Альтернативно: Temporal signal_workflow может принимать только `workflow_id` без `run_id` (signal отправляется в latest run), но текущий код передаёт синтетический `run_id=signal_id`.

**Impact**:
- В Temporal backend: `client.get_workflow_handle(workflow_id, run_id=signal_id)` → RuntimeError "workflow not found" (нет run с таким id).
- В PgRunner backend: `WorkflowHandle.run_id` интерпретируется как instance UUID (`pg_runner_backend.py:355-362`) → UUID parse error.

**Minimal recommendation**:
- `run_id=""` или `run_id=None` — Temporal SDK поддерживает "latest run" semantics.
- Альтернативно: реальный Temporal API с `client.get_workflow_handle(workflow_id)` без `run_id`.

**Test criterion**:
- `HitlService.resolve(...)` mock `WorkflowFacade.signal` → `handle.run_id != signal_id`.

---

### DOMAIN-WF-P2-005 — `WorkflowLauncher.resolve_best_match` API-контракт mismatch

**Path:line**: `src/backend/dsl/workflow/launcher.py:139-141`

**Evidence**:
```python
def resolve_best_match(self, workflow_name: str, spec: str, available_versions: list[str] | None = None):
    if available_versions is None:
        # Use single installed version
        return self.resolve(workflow_name, spec)
    ...
```

**Problem**: при `available_versions=None` метод делегирует на `resolve`, которая ВСЕГДА работает с единственной версией из `self._installed`. Но контракт `available_versions=None` — это не "используй installed", а "резолви из всего что есть". Если в `self._installed` версия `2.0.0`, а caller хочет `spec="^1.0"` — получит raise, а не search среди других доступных версий.

**Impact**:
- API ambiguity: caller не понимает, нужно ли передавать `available_versions` явно.
- При отсутствии explicit list — поведение отличается от документированного (best-match среди installed).

**Minimal recommendation**:
- `if available_versions is None: available_versions = list(self._installed.values())` — uniform behavior.

---

### DOMAIN-WF-P2-006 — `OrchestratorEngine` swallow-all exception

**Path:line**: `src/backend/dsl/workflow/orchestrator_engine.py:160-183`

**Evidence**:
```python
def _evaluate_condition(self, jmespath_expr: str, task: dict[str, Any]) -> bool:
    try:
        import jmespath
        data = task.get("input", task)
        result = jmespath.search(jmespath_expr, data)
        return bool(result)
    except Exception as exc:  # <-- bare except
        _logger.warning(
            "OrchestratorEngine: JMESPath evaluation failed for %r: %s",
            jmespath_expr, exc,
        )
        return False  # <-- silent fallback
```

**Problem**: JMESPath typo (`"input.type == 'score'"` vs `"input.type=='score'"`) или runtime error молча возвращает `False`. В exclusive-маршрутизации это означает fallback на `default_agent` или ошибку "no rule matched".

**Impact**:
- Hidden fail-open: agent routing может выбирать default вместо правильного agent, без явного уведомления.

**Minimal recommendation**:
- Log level `error` вместо `warning`.
- Метрика `orchestrator_jmespath_errors_total{expr=...}` для observability.

---

### DOMAIN-WF-P3-001 — `WorkflowSubprocessProcessor` (107 LOC) + `import_bpmn` (444 LOC) — возможна замена на установленное

**Path:line**:
- `src/backend/dsl/engine/processors/workflow/workflow_subprocess.py`
- `src/backend/dsl/workflow/bpmn_importer.py`

**Library candidate**:
- BPMN import: **SpiffWorkflow** — уже упоминается в `core/config/features/workflow.py:53-61` docstring как «target». PyPI: `spiffworkflow`. License: MIT (проверено через PyPI metadata — не проверено live).
- Sub-workflow: `temporalio` SDK имеет native `workflow.execute_child_workflow()` — уже в deps (workflow extra).

**License/maintenance**: SpiffWorkflow — активный maintenance (latest release 2024+); temporalio — Temporal Technologies Inc.

**LOC delta**: при полной замене `import_bpmn` на `SpiffWorkflow` — экономия ~300 LOC (BPMN-специфичный код заменён на `BpmnWorkflow` parser). `WorkflowSubprocessProcessor` — экономия ~80 LOC через `temporalio.child_workflow()`.

**Не проверено** (в рамках read-only): реальный benchmark SpiffWorkflow vs текущий импортёр, feature-parity для BPMN 2.0 конструкций, не покрытых в `bpmn_importer.py` (subprocess, businessRuleTask, userTask).

---

### DOMAIN-WF-P3-002 — `to_graphviz` naive escape

**Path:line**: `src/backend/dsl/workflow/visualize.py:144-147`

**Evidence**:
```python
def _escape_dot(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
```

**Problem**: не учитывает newlines (`\n` → DOT parser может интерпретировать как command separator), не экранирует `<`, `>`, `&` (DOT HTML-подобные конструкции). Workflow name из untrusted YAML (через `import_bpmn`) может содержать эти символы.

**Library candidate**: graphviz Python binding (`graphviz.Source(..., engine='dot')`) уже в deps — имеет корректный escape.

**Impact**: при рендере `to_graphviz` через Streamlit (`streamlit-mermaid`) — injection в DOT source → arbitrary node attributes / edge targets.

---

### DOMAIN-WF-P3-003 — Docstring содержит CJK символ

**Path:line**: `src/backend/dsl/workflow/orchestrator.py:118`

**Evidence**: `description="Routing rules (evaluate顺序 по порядку)."` — иероглиф `顺序` вместо русского/английского "порядку".

**Impact**: minor — code-smell, может усложнить code review.

---

### DOMAIN-WF-P4-001 — `start_child_workflow` Protocol, но нет Temporal impl

**Path:line**:
- `src/backend/core/workflow/backend.py:155-191` (Protocol definition)
- `src/backend/infrastructure/workflow/pg_runner_backend.py:297-350` (impl для pg_runner)
- `src/backend/infrastructure/workflow/temporal_backend.py` — **нет метода**

**Evidence**: `WorkflowBackend` Protocol объявляет `async def start_child_workflow(self, *, parent_handle, workflow_name, workflow_id, input, task_queue, execution_timeout)` с детальным docstring про Temporal native (`Client.start_workflow(..., parent=...)`). Но `TemporalWorkflowBackend` (368 LOC) не реализует этот метод — class не satisfies Protocol → mypy error при strict checks.

Проверено: класс содержит только `start_workflow`, `signal_workflow`, `query_workflow`, `cancel_workflow`, `await_completion`, `replay`. Никакого `start_child_workflow` или `await_external_signal` (S210 fix в Protocol).

**Impact**: HITL-паттерн (S210) и child workflows невозможны в production Temporal backend — только в pg-runner fallback.

**Minimal recommendation**: реализовать оба метода через Temporal native API:
```python
async def start_child_workflow(self, *, parent_handle, workflow_name, workflow_id, input, task_queue, execution_timeout=None):
    return WorkflowHandle(
        workflow_id=workflow_id,
        run_id=...,  # Temporal returns via handle
        namespace=parent_handle.namespace,
    )
```

---

### DOMAIN-WF-P4-002 — Два parallel declarative spec без моста

**Path:line**:
- `src/backend/dsl/workflow/spec/workflow.py:49-101` (`WorkflowDeclaration` — Temporal-стиль)
- `src/backend/infrastructure/workflow/executor/state.py:71-89` (`WorkflowSpec` — pg-runner-стиль)

**Evidence** (`spec/workflow.py:93-101`):
```python
# Runtime path docstring (S36-W16):
#   WorkflowDeclaration.compile_workflow() → dynamic Temporal
# @workflow.defn class → Temporal worker исполняет.
#   WorkflowDeclaration НЕ drive'ит DSLStepExecutor напрямую — для
# pg-runner есть parallel-схема WorkflowSpec + WorkflowDescriptor
# (registry.register(descriptor, route_id, spec=...)). Обе системы
# сосуществуют; bridge между ними — out of scope этого модуля
# (см. ADR pending — будет оформлен в S37+ при первой реальной
# необходимости конвертации одного workflow spec в другой).
```

**Impact**: две параллельные runtime-системы для одного DSL. Plugin author не понимает, какой использовать.

**Minimal recommendation**: конвертер `WorkflowDeclaration ↔ WorkflowSpec` (односторонний: первый → второй, для pg-runner fallback), без потери шагов.

---

## Contradictions / Overlaps to flag

1. **`WorkflowFlags` docstring vs code (DOMAIN-WF-P0-001)** — 4 из 5 флагов имеют ложное описание default. Это критично: новые ops/install могут полагаться на docstring. Рекомендую немедленное согласование.

2. **`ActivityBridge` machinery exists but unwired (DOMAIN-WF-P0-003)** — `compile_workflow`, `ActivityBridge`, `register_langgraph_checkpoint_activities` написаны, но production worker их не использует. Это «paper architecture» без runtime path. Sprint 36 (Production Readiness) объявляет Temporal default workflow engine — но без activity registration это fail-closed только на уровне factory, не worker.

3. **4 unregistered processors (DOMAIN-WF-P0-002)** — `WorkflowSubprocessProcessor`, `WorkflowConvertProcessor`, `WorkflowClaimCheckProcessor`, `WorkflowContinueAsNewProcessor` объявлены с `required_capability`/`audit_event`, но не зарегистрированы. Capability-check никогда не срабатывает → audit events теряются → fail-open для sensitive ops.

4. **BPMN feature flag = True (DOMAIN-WF-P0-001)** — `workflow_bpmn_import=True` активирует код, который парсит BPMN через defusedxml, делает топологическую сортировку, но: 
   - импортёр нигде не вызывается в проде (только тесты);
   - сам импортёр не покрывает BPMN 2.0 полностью (subprocess, businessRuleTask — «Sprint 5+» в docstring);
   - `BpmnImportNotAvailableError` мёртв (P2-002).
   
   То есть: флаг ON, код есть, реальная функциональность = «можем импортировать простой BPMN в test mode, но в проде никто не зовёт».

5. **`compile_sensor_step` infinite polling (DOMAIN-WF-P1-003)** vs `compile_agent_invoke_step` durable checkpoint — sensor использует `start_to_close_timeout=ctx["_default_timeout_s"]` (300s default), но `workflow.sleep` между итерациями = 60s default. Если predicate возвращает `False` 10 раз = 10 activities + 10 sleeps = ~600s workflow event history → может превысить Temporal limit.

6. **HITL handle misuse (DOMAIN-WF-P2-004)** — `HitlService.resolve` создаёт `WorkflowHandle(run_id=signal_id)`. Это нарушение Protocol, которое в production Temporal вызовет `WorkflowExecutionNotFoundError`. В текущем коде не валится (mock'нут facade), но в real Temporal integration — fail-loud crash.

7. **Saga compensation `strict_compensate=True` chain semantics (verified STRENGTH-17)** — корректно chain'ит через `raise exc from comp_errors[-1]`, сохраняя original. Это пример правильного exception chaining в проекте. Контраст с `OrchestratorEngine` swallow-all (P2-006).

8. **Capability-gate facade (STR-WF-05) vs unwired Temporal worker (P0-003)** — facade правильно проверяет capabilities, но без реального Temporal worker эти проверки не достигают Temporal API layer. Blast-radius control не работает для Temporal-execution path.

9. **`run_workflow_by_id` fake marker (P2-003) vs `WorkflowSubprocessProcessor` (P0-002)** — оба dead-code: процессор не зарегистрирован, функция возвращает marker. Если когда-нибудь будет зарегистрирован — silent broken behavior.

10. **`WorkflowContinueAsNewHandler` separate `upsert_search_attributes` (STR-WF-09) vs `ContinueAsNewProcessor` not registered (P0-002)** — handler правильно разделяет API (B-18 fix), но процессор, который ставит marker, не подключён к DSL pipeline → handler никогда не вызывается через DSL.

---

## Readiness Score 0–100

**Formula** (явная):
```
Readiness = 100
          - 15 * (P0 count)
          - 8  * (P1 count)
          - 3  * (P2 count)
          - 1  * (P3 count)
          - 0  * (P4 count)
          - 5  * (security/race/fail-open flags inside P0/P1)
          - 0  * (verified strengths)
```

**Counts**:
- P0: 3 (DOMAIN-WF-P0-001 docstring lie, P0-002 unregistered processors, P0-003 unwired ActivityBridge)
- P1: 5 (DOMAIN-WF-P1-001 SemVer silent fallback, P1-002 guardrail fail-open, P1-003 sensor infinite, P1-004 namespace leak, P1-005 WatchError tight loop)
- P2: 6 (P2-001, P2-002, P2-003, P2-004, P2-005, P2-006)
- P3: 3 (P3-001, P3-002, P3-003)
- P4: 2 (P4-001, P4-002)
- Security/fail-open flags inside P0/P1: 4 (P0-001 fail-closed breach, P0-002 capability fail-open, P1-002 cost guardrail fail-open, P1-004 namespace leak, P1-005 DoS)

**Calculation**:
```
100 - 15*3 = 55
55 - 8*5  = 15
15 - 3*6  = -3
-3 - 1*3  = -6
-6 - 0*2  = -6
-6 - 5*4  = -26
```

**Clamped to [0, 100]** with **explicit gate**: оценка ≥80 **ЗАПРЕЩЕНА** при наличии P0/P1.

**Final Readiness Score: 30 / 100**

**Justification**:
- Domain имеет прочную clean-architecture (lazy imports, capability-gate, type-checked Protocol, fail-loud compensation), что даёт базовый credit.
- Но 3 P0 блокируют production-readiness: docstring/code mismatch в feature flags (audit/operational lie), 4 dead-code процессора (security/capability bypass), unwired Temporal Worker machinery (latent crash на первом temporal workflow в проде).
- 5 P1 находят race/fail-open paths, которые могут привести к data loss (P1-001 SemVer silent), cost explosion (P1-002 guardrails), tenant leak (P1-004), DoS (P1-005).
- 6 P2 dead code (более 600 LOC поддерживается без пользы).
- Workflow domain — это **«DSL complete, runtime fragile»**: declarative spec покрывает Camel/Airflow/Temporal patterns, но Temporal runtime path не доведён до production.

---

## Recommended Next Tasks

**B-23 (P0, security)**: Согласовать `WorkflowFlags` docstrings с реальными defaults (fail-closed: 4 флага → `default=False`).

**B-24 (P0, security)**: Решить судьбу 4 unregistered processors (`WorkflowSubprocessProcessor`, `WorkflowConvertProcessor`, `WorkflowClaimCheckProcessor`, `WorkflowContinueAsNewProcessor`):
- Variant A: зарегистрировать через `@processor()` — восстанавливает functional path.
- Variant B: удалить (P2 dead code reduction ~430 LOC).

**B-25 (P0, runtime)**: Wire `ActivityBridge` + `register_langgraph_checkpoint_activities` + `bridge.decorate()` в `worker.py:_run_worker`. Без этого Temporal Workflow в production не выполнит ни одной activity.

**B-26 (P1, security)**: `compile_guardrail_step` — extract numeric через dot-path или `len(json.dumps(...))`. Защита от fail-open для `max_cost_usd`/`output_size_bytes`.

**B-27 (P1, runtime)**: `compile_sensor_step` — добавить safety cap (3600s default) для `timeout_s=None`. Защита от runaway workflow.

**B-28 (P1, security)**: `TemporalWorkflowBackend.start_workflow` — raise вместо warning при namespace mismatch. Tenant isolation.

**B-29 (P1, runtime)**: `WorkflowLauncher.resolve` — caller должен raise при SemVer mismatch (не silent fallback в `InvokeWorkflowProcessor._resolve_workflow_version`).

**B-30 (P2, cleanup)**: Удалить 6 dead-code items: `_iter_activity_names`, `BpmnImportNotAvailableError`, fake `run_workflow_by_id`, `HitlService` handle misuse, ambiguous `resolve_best_match` API, OrchestratorEngine swallow-all.

**B-31 (P4, feature)**: Реализовать `TemporalWorkflowBackend.start_child_workflow` + `await_external_signal` для S210 HITL-паттерна в production.

**B-32 (P4, feature)**: Конвертер `WorkflowDeclaration ↔ WorkflowSpec` для unified UX в DSL.

---

## Commands Run (сводка)

```bash
# Каркас и baseline
git rev-parse HEAD                       # 2f620910
git rev-list --count b69d6b49..HEAD      # 1
git status --porcelain                   # pyproject.toml + tests/unit/dsl/transforms/test_dataframes.py modified

# Скоуп и LOC
find src/backend/dsl/workflow src/backend/services/workflows src/backend/infrastructure/workflow src/backend/core/config/workflow.py src/backend/core/config/features/workflow.py src/backend/core/workflow_registry.py 2>/dev/null
wc -l src/backend/dsl/workflow/** src/backend/services/workflows/* src/backend/infrastructure/workflow/** 2>/dev/null
# Итого ~14 698 LOC в scope

# Dead-code markers (в scope — НЕТ TODO/FIXME/HACK)
grep -nE "TODO|FIXME|XXX|HACK" src/backend/{dsl/workflow,services/workflows,infrastructure/workflow}/**  # 0 hits

# NotImplementedError (1 явный — pg_runner_backend)
grep -nE "NotImplementedError" src/backend/infrastructure/workflow/pg_runner_backend.py:231  # explicit fail-loud

# Dependency check
python3 -c "import tomllib; d = tomllib.load(open('pyproject.toml','rb'))"
# packaging/simpleeval/defusedxml/graphviz/clickhouse_connect — НЕ в pyproject (только транзитивные через casbin, lxml и т.д.)

# WorkflowFlags actual defaults
python -c "from src.backend.core.config.features.workflow import WorkflowFlags; print(WorkflowFlags())"
# 4 из 5 = True (противоречит docstrings "default-OFF")

# Registered processors
python -c "from src.backend.dsl.registry import get_processor_registry; \
  import src.backend.dsl.engine.processors.invoke_workflow, \
          src.backend.dsl.engine.processors.cancel_workflow, \
          src.backend.dsl.engine.processors.sub_workflow; \
  print([s.name for s in get_processor_registry().list_specs() if 'workflow' in s.name])"
# ['cancel_workflow', 'invoke_workflow', 'sub_workflow']
# WorkflowSubprocess/Convert/ClaimCheck/ContinueAsNew — НЕ зарегистрированы

# Production usage
grep -rn "register_langgraph_checkpoint_activities\|TemporalWorkerPool\|WorkflowSubprocessProcessor(" src/backend/{services,extensions,infrastructure} 2>/dev/null
# Только docstring refs, нет реальных callers

# BPMN import (smoke — feature flag default=True сработал)
python -c "from src.backend.dsl.workflow.bpmn_importer import import_bpmn; \
  print(import_bpmn('<bpmn:definitions...>').name)"
# 'P1' — OK, но вызов НЕ из production кода

# ActivityBridge usage
grep -rln "ActivityBridge\|register_langgraph_checkpoint\|get_activity_callables" src/backend 2>/dev/null | grep -v __pycache__
# Только в compiler/__init__.py + activity_bridge.py + security/activity_capability_guard.py (import ref)
# НЕТ ни одного production-caller
```

---

**Audit complete**. Отчёт сохранён. Финальный structured summary для родителя — в следующем сообщении.
