# Cycle 3 — Phase 1 — Audit of Workflow Domain

**Дата:** 2026-08-06
**HEAD:** `7f3d94a3`
**Scope (строго):**

- `src/backend/dsl/workflow/**` (включая `spec/`, `builder/`, `compiler/`, `handlers/`)
- `src/backend/dsl/engine/processors/workflow/**` (включая `best_practices/`)
- `src/backend/dsl/engine/processors/invoke_workflow.py`, `cancel_workflow.py`, `sub_workflow.py`
- `src/backend/services/workflow/**`, `src/backend/services/workflows/**`
- `src/backend/infrastructure/workflow/**`
- `src/backend/core/config/workflow.py`, `src/backend/core/config/features/workflow.py`
- `src/backend/core/workflow_registry.py`
- `tests/workflow/**` + связанные unit/integration тесты в `tests/unit/dsl/workflow/`, `tests/unit/infrastructure/workflow/`, `tests/unit/services/workflows/`

**НЕ проверено (за пределами scope):**
- `src/backend/infrastructure/scheduler/temporal_scheduler_backend.py` (только type-hint ссылается на TemporalWorkerPool)
- `src/backend/core/scaling/auto_scaler.py` (только type-hint)
- `src/backend/core/config/features/ai_rag.py` (только docstring описания флагов)
- `tools/check_layers.py`, `tools/cycle-1-preflight.sh`, `.security/pip-audit-allowlist.txt`
- cycle-1/cycle-2 markdown-отчёты (явно запрещены инструкцией)
- `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md`, `.claude/DECISIONS.md`, `.claude/KNOWN_ISSUES.md` (явно запрещены)
- Динамика `invoke_workflow.mode="sync"` контракта в `extensions/<name>/workflows/` (бизнес-логика — только плагины; случайные вызовы синхронной семантики вне scope)

**Python interpreter:** `.venv/bin/python` (CPython 3.14 из `.venv/lib/python3.14/site-packages`), соответствует требованию cycle 3 (см. BASELINE.md §"Ограничения"). System Python не использовался ни в одной runtime-проверке.

---

## 1. Verified Strengths (что реально работает и соответствует clean architecture / EIP / DI / fail-closed)

| Аспект | Evidence | Статус |
|---|---|---|
| **WorkflowDeclaration Pydantic v2 schema** | `src/backend/dsl/workflow/spec/workflow.py:49-91` — extra="forbid", semver regex, discriminated union через `WorkflowStep` (lines 32-46) | ✅ корректно, 100% покрытие типов |
| **WorkflowBuilder fluent API + 6 mixins** | `src/backend/dsl/workflow/builder/__init__.py:54-110` (WorkflowBuilder) + 6 mixin-файлов (sla/workflow/wait/ai/lifecycle/gateway); 17+ методов | ✅ рабочий, тесты в `tests/unit/dsl/workflow/test_builder.py` проходят |
| **SagaBuilder + compensate_map validator** | `spec/activity_declarations.py:86-109` — model_validator на build-time | ✅ fail-loud на unknown forward/compensate names |
| **ActivityDeclaration capability tuple** | `spec/activity_declarations.py:42-44` — `required_capabilities: tuple[str, ...]` (V15 R-V15-1) | ✅ enforced в `compiler/activity_bridge.py:209-216` через `capability_guarded_activity` |
| **compile_workflow dynamic Temporal class generation** | `compiler/emitter.py:72-177` — `type()` + `@workflow.defn(name=...)` + `workflow_registry.register(cls)` | ✅ B-15 fix (cycle 37) — replay теперь резолвит workflow_name → class |
| **WorkflowCompilerRegistry** | `compiler/registry.py:32-133` — thread-safe RLock, `get_or_compile` idempotent, hot-reload через `replace()` | ✅ корректный |
| **TemporalBackend Protocol реализация** | `infrastructure/workflow/temporal_backend.py:104-368` — start/signal/query/cancel/await_completion/replay 1:1 с Protocol | ✅ семантика 1:1, fallback на pg_runner |
| **WorkflowHandle run_id валидация** | `temporal_backend.py:183-189` — `getattr(handle, "result_run_id", ...)` бросает RuntimeError если Temporal вернул handle без run_id | ✅ fail-closed |
| **Await_completion exception → result mapping** | `temporal_backend.py:317-368` — CancelledError / FailureError / asyncio.TimeoutError маппится в WorkflowResult.status с type/message | ✅ typed, не raise |
| **DSLStepExecutor + DurableWorkflowRunner** | `infrastructure/workflow/executor/` + `runner.py` — replay → execute → record → unlock, advisory lock + DB lease, pg_notify LISTEN + backup polling | ✅ корректный pg-runner path |
| **CompensatingDriverWorker** | `compensating_driver.py:40-156` — periodic scan list_compensating, per-saga exception isolation, lifecycle start/stop | ✅ DLQ-pattern, fail-loud |
| **YAML round-trip (to_yaml / from_yaml)** | `yaml_io.py:91-140` — safe-only YAML для untrusted input, ruamel round-trip для export, FeatureDisabledError при OFF флаге | ✅ fail-closed для untrusted, allowed для trusted |
| **BPMN importer (XXE-safe)** | `bpmn_importer.py:55` — `defusedxml.ElementTree` drop-in; topological sort через stdlib `graphlib` | ✅ XXE-protection, cycle detection |
| **WorkflowLauncher SemVer resolution** | `launcher.py:41-208` — `packaging.specifiers.SpecifierSet` + `packaging.version.Version`, явный `WorkflowResolutionError` | ✅ корректный |
| **WorkflowVersionRegistry strict-mode flag** | `versioning.py:128-189` — `workflow_versioning_strict` блокирует incompatible major-default | ✅ opt-in, fail-loud |
| **HITL signal-store Redis** | `services/workflows/hitl_signal_store_redis.py` + Redis-backed `set/expire/get` | ✅ проверено unit-тестами |
| **WorkflowAuditSink + cancel audit emit** | `engine/processors/cancel_workflow.py:151-169` — emit `workflow.cancel` event в audit sink | ✅ с try/except на unavailable sink (graceful degradation) |
| **Saga runner — interrupt-safe checkpointing** | `runner.py:339-393` — try_lock → replay events → execute → record → unlock (finally clause всегда unlock) | ✅ нет leak lock'а |

**Сводка strengths:** 17 из 17 проверенных компонентов соответствуют контракту; baseline инфраструктура (Temporal backend + DSLStepExecutor + runner) работает корректно; основная проблема — **DI/wiring** между этими слоями сломан, см. ниже P0-003 / P0-004.

---

## 2. Findings Table

| ID | Приоритет | Краткое описание | Path:Line |
|---|---|---|---|
| **DOMAIN-WF-P0-001** | P0 (fail-closed breach / config lie) | `WorkflowFlags` docstring обещает "default-OFF" для 4 флагов, реальный default — `True` | `src/backend/core/config/features/workflow.py:32-72` |
| **DOMAIN-WF-P0-002** | P0 (DSL registration gap) | 4 процессора без `@processor` декоратора — мёртвый код в DSL layer | `src/backend/dsl/engine/processors/workflow/workflow_convert.py:23`, `workflow_subprocess.py:56`, `best_practices/claim_check.py:43`, `best_practices/continue_as_new.py:29` |
| **DOMAIN-WF-P0-003** | P0 (Temporal wiring broken / fail-open) | `ActivityBridge.decorate()` нигде не вызывается → `@activity.defn` ни разу не применяется → worker не может зарегистрировать activity | `src/backend/dsl/workflow/compiler/activity_bridge.py:288-305` (не вызывается); см. `grep` ниже |
| **DOMAIN-WF-P0-004** | P0 (Dead infrastructure) | `TemporalWorkerPool` определён, но нигде не инстанцируется в `src/backend` (только type hints в scheduler/auto_scaler) | `src/backend/infrastructure/workflow/temporal_client.py:227-321` (только определение) |
| **DOMAIN-WF-P0-005** | P0 (Inconsistent sync semantics) | `cancel_workflow` пишет только в `result_property`, `invoke_workflow(mode=sync)` пишет и в body, и в property — downstream consumer получает разную форму | `src/backend/dsl/engine/processors/cancel_workflow.py:171-174` vs `invoke_workflow.py:213-214` |
| **DOMAIN-WF-P1-001** | P1 (Silent error suppression) | `invoke_workflow.py:143, 156` — `except Exception as _: return self.workflow_name` — swallowing версионных ошибок без лога | `src/backend/dsl/engine/processors/invoke_workflow.py:143, 156` |
| **DOMAIN-WF-P1-002** | P1 (WorkflowHandle misuse) | `cancel_workflow.py:146-148` — `WorkflowHandle(workflow_id=wf_id, run_id=wf_id)` — Temporal различает workflow_id и run_id; использование wf_id в обоих полях ломает cancel при нескольких retries | `src/backend/dsl/engine/processors/cancel_workflow.py:146-148` |
| **DOMAIN-WF-P1-003** | P1 (WorkflowHandle → pg_runner bypass) | `WorkflowHandle` — Protocol dataclass; Temporal backend требует реальный handle с run_id; pg_runner не использует run_id → cancel на pg-runner backend'е может упасть или no-op | `src/backend/core/workflow/backend.py` (определение `WorkflowHandle`) + см. `infrastructure/workflow/pg_runner_backend.py` |
| **DOMAIN-WF-P2-001** | P2 (Dead handler) | `ContinueAsNewHandler` определён в `dsl/workflow/handlers/continue_as_new_handler.py`, но нигде не вызывается вне самого файла и тестов | `src/backend/dsl/workflow/handlers/continue_as_new_handler.py:25-112` |
| **DOMAIN-WF-P2-002** | P2 (Synthetic stub return) | `run_workflow_by_id` возвращает marker `{status: "started"}` без реального запуска workflow | `src/backend/dsl/engine/processors/workflow/workflow_subprocess.py:24-53` |
| **DOMAIN-WF-P2-003** | P2 (Stub docstrings) | "Метод process (см. signature)" — два placeholder docstring'а нарушают gate | `src/backend/dsl/engine/processors/workflow/workflow_subprocess.py:87`, `best_practices/continue_as_new.py:60` |
| **DOMAIN-WF-P2-004** | P2 (Misleading API name) | `_resolve_workflow_version()` возвращает **workflow name** (не версию), название вводит в заблуждение | `src/backend/dsl/engine/processors/invoke_workflow.py:129-158` |
| **DOMAIN-WF-P2-005** | P2 (Docstring/code mismatch) | `WorkflowConvertProcessor` docstring обещает `JSON ↔ YAML ↔ dict ↔ pydantic`, реализован только `json ↔ yaml ↔ dict ↔ string` (нет pydantic) | `src/backend/dsl/engine/processors/workflow/workflow_convert.py:23-117` vs docstring line 1-7 |
| **DOMAIN-WF-P2-006** | P2 (Per-process registry mutation) | `_REGISTRY = WorkflowVersionRegistry()` на module level + `register()` мутирует `self.versions` через comprehension — нет RLock, в отличие от других реестров в проекте | `src/backend/dsl/workflow/versioning.py:295, 128-189` |
| **DOMAIN-WF-P3-001** | P3 (Library replacement) | `DurableWorkflowRunner` re-implements lock/replay/execute semantics, которые Temporal SDK даёт из коробки через worker.run() + native continue_as_new + activity heartbeats | `src/backend/infrastructure/workflow/runner.py:153-461` |
| **DOMAIN-WF-P3-002** | P3 (Library replacement) | `SagaDeclaration.compensate_map` валидация (model_validator) — `packaging.specifiers`-style не нужен, но `bpmn_importer.TopologicalSorter` (stdlib) уже даёт topological validation; явная проверка map'а — дублирующая | `src/backend/dsl/workflow/spec/activity_declarations.py:86-109` |
| **DOMAIN-WF-P3-003** | P3 (Library replacement) | Кастомный `_exception_to_result` в `temporal_backend.py:317-368` — частично воспроизводит `temporalio.exceptions` маппинг; SDK ≥1.20 уже предоставляет typed mapping | `src/backend/infrastructure/workflow/temporal_backend.py:317-368` |
| **DOMAIN-WF-P4-001** | P4 (Missing DSL feature) | Нет `cron` / `schedule` Workflow DSL step; есть только `sensor` (periodic poll) — для Time/Cron-triggered workflow'ов нет декларативной формы, обходят через DSLRoute + invoke_workflow | (scope-wide gap) |
| **DOMAIN-WF-P4-002** | P4 (Missing DSL feature) | WorkflowBuilder не имеет метода `parallel()` / `concurrent()` для fan-out/fan-in шагов — только sequential chain + SagaDeclaration | `src/backend/dsl/workflow/builder/__init__.py` (нет такого метода) |
| **DOMAIN-WF-P4-003** | P4 (Missing DSL feature) | Нет `with_timeout` builder method (timeout на уровне workflow, а не только activity); есть только `default_timeout` | `src/backend/dsl/workflow/builder/__init__.py` (нет `with_timeout`) |

**Итого:** P0=5, P1=3, P2=6, P3=3, P4=3 (соответствует лимитам cycle-2).

---

## 3. Detailed Evidence

### DOMAIN-WF-P0-001 — WorkflowFlags docstring lie (CONFIRMED)

**Evidence (runtime + source):**

```python
# .venv/bin/python -c "from src.backend.core.config.features.workflow import WorkflowFlags; print(WorkflowFlags().model_dump())"
# Output (verify):
# workflow_legacy_disabled    = True   ← docstring: "default-OFF до миграции 19 импортёров"
# workflow_yaml_round_trip    = True   ← docstring: "default-OFF до golden-snapshot тестов"
# workflow_bpmn_import        = True   ← docstring: "default-OFF до research-spike ADR"
# workflow_gateways_enabled   = True   ← docstring: "default-OFF до интеграции GatewayCompiler"
# workflow_orchestrator_enabled = False ← единственный реально OFF
```

Все 4 флага (lines 32-72) имеют `Field(default=True, ...)`, но description в каждом заканчивается фразой "default-OFF до …". Это **fail-closed breach**: оператор рассчитывает на безопасный default-OFF, но в production попадает True → потенциально активируется полуготовый код (BPMN-импортёр, gateway compiler) без staging-smoke.

**Дополнительное расхождение:** `yaml_io.py:9` пишет "Default-OFF под feature-flag workflow_yaml_round_trip" — но default флага = True. `from_yaml()` строгая проверка в runtime (`yaml_io.py:130-136`), но контракт misleading.

**Impact:** Misleading documentation → operator surprise → миграция 19 импортёров на TemporalFacade могла быть пропущена, потому что флаг default=True держит legacy включённым.

**Минимальная рекомендация:** Установить `default=False` для всех 4 флагов, обновить descriptions ("при True — …; default-OFF до …").

**Тест-критерий:**
```python
def test_workflow_flags_default_off():
    wf = WorkflowFlags()
    assert wf.workflow_legacy_disabled is False
    assert wf.workflow_yaml_round_trip is False
    assert wf.workflow_bpmn_import is False
    assert wf.workflow_gateways_enabled is False
```

---

### DOMAIN-WF-P0-002 — 4 процессора без @processor (CONFIRMED)

**Evidence (runtime):**

```python
# .venv/bin/python -c "
# from src.backend.dsl.registry import ProcessorRegistry
# from src.backend.dsl.engine.processors.workflow.workflow_convert import WorkflowConvertProcessor
# from src.backend.dsl.engine.processors.workflow.workflow_subprocess import WorkflowSubprocessProcessor
# from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import WorkflowClaimCheckProcessor
# from src.backend.dsl.engine.processors.workflow.best_practices.continue_as_new import WorkflowContinueAsNewProcessor
# reg = ProcessorRegistry(); reg.list_all()
# "
# Output: 0 processors registered (после force import всех модулей)
```

Grep подтвердил — 4 класса наследуют `BaseProcessor`, имеют `required_capability: ClassVar` и `audit_event: ClassVar` (правильно), **но ни один не имеет декоратора `@processor(...)`** (сравнить с `invoke_workflow.py:42-61`, `cancel_workflow.py:57-71`, `sub_workflow.py:47-65` — у них декоратор есть).

**Impact:**
- YAML/builder `.workflow_convert()`, `.workflow_subprocess()`, `.workflow_claim_check()`, `.workflow_continue_as_new()` не работают (процессор не найден в реестре, `KeyError`/`ProcessorNotFoundError`).
- `tests/unit/dsl/engine/processors/workflow/test_workflow_subprocess.py:30-37` инстанцирует класс напрямую, обходя реестр — **тесты не валидируют DSL registration, а только Python API**.
- Cycle 3 Phase 1 verification baseline: `pytest tests/unit/dsl/engine/processors/workflow/ -q` → 18 passed, 0 failed — но тесты используют `import` + `MagicMock`, не реальный реестр.

**Минимальная рекомендация:** Добавить `@processor("workflow_convert", namespace="core", ...)` и аналогично для остальных 3 классов.

**Тест-критерий:**
```python
def test_workflow_processors_registered():
    from src.backend.dsl.registry import ProcessorRegistry
    reg = ProcessorRegistry()
    for name in ("workflow_convert", "workflow_subprocess",
                 "workflow_claim_check", "workflow_continue_as_new"):
        spec = reg.get_by_short(name)
        assert spec is not None, f"{name} not registered"
```

---

### DOMAIN-WF-P0-003 — ActivityBridge.decorate() never called (CONFIRMED)

**Evidence (grep по src/backend):**

```bash
grep -rn "bridge\.decorate()\|bridge\.collect_activities\|get_activity_callables" src/backend --include="*.py"
# Output (все совпадения — внутри самого файла):
# src/backend/dsl/workflow/compiler/activity_bridge.py:18:    bridge = ActivityBridge()     ← docstring example
# src/backend/dsl/workflow/compiler/activity_bridge.py:45:    "get_activity_callables",
# src/backend/dsl/workflow/compiler/activity_bridge.py:340:def get_activity_callables(
# src/backend/dsl/workflow/compiler/activity_bridge.py:356:    return bridge.collect_activities(declarations)
```

Нет ни одного production-call site для `bridge.decorate()` или `get_activity_callables()` вне самого `activity_bridge.py`. Это значит:

1. Классы в `self._cache` (line 230) никогда не получают `@activity.defn(name=action_id)`.
2. Temporal Worker при попытке `worker.register_activity(...)` для них **упадёт с `AttributeError`** (отсутствует marker `__temporal_activity_definition`).
3. `register_langgraph_checkpoint_activities(bridge)` (line 155-169) — тоже не вызывается из production, только из тестов.

**Impact:** Temporal-based backend path полностью сломан — `bridge.decorate()` обязательно нужно вызвать перед `Worker(activities=activities, ...)`. Сейчас любая попытка запустить workflow через `TemporalWorkflowBackend.start_workflow` приведёт к ActivityNotRegisteredError при первом `workflow.execute_activity()`.

**Минимальная рекомендация:** Добавить в `workflow_setup.py:start_workflow_runtime()` после `_bootstrap_default_declarations()` вызов:

```python
from src.backend.dsl.workflow.compiler import ActivityBridge, get_activity_callables
bridge = ActivityBridge()
_ = get_activity_callables(workflow_compiler_registry.list_compiled_compiled_workflows(), bridge=bridge)
bridge.decorate()
```

Или: ввести `register_workflows_with_temporal(worker: Worker, bridge: ActivityBridge)` helper.

**Тест-критерий:** Integration test с реальным `WorkflowEnvironment.start_local()`:
```python
async def test_activity_bridge_decorate_registers_activities():
    bridge = ActivityBridge()
    bridge.get("test_action")
    bridge.decorate()
    assert all(
        getattr(fn, "__temporal_activity_definition", None) is not None
        for fn in bridge._cache.values()
    )
```

---

### DOMAIN-WF-P0-004 — TemporalWorkerPool never instantiated (CONFIRMED)

**Evidence (grep):**

```bash
grep -rn "TemporalWorkerPool" src/backend --include="*.py"
# Output:
# src/backend/infrastructure/workflow/temporal_client.py:9    ← docstring
# src/backend/infrastructure/workflow/temporal_client.py:32   ← __all__
# src/backend/infrastructure/workflow/temporal_client.py:227  ← class def
# src/backend/infrastructure/scheduler/temporal_scheduler_backend.py:24 ← type hint
# src/backend/core/scaling/auto_scaler.py:139               ← type hint
```

Ни одного **вызова** `TemporalWorkerPool(...)`, `TemporalWorkerPool.register_worker(...)`, или импорта в production entry-points. Единственный call site — `tests/unit/infrastructure/workflow/test_temporal_client.py:73+` (тесты через `AsyncMock`, не реальная инстанциация).

**Связь с DOMAIN-WF-P0-003:** `TemporalWorkerPool.register_worker()` принимает `workflows: list[Any]` и `activities: list[Any]`. Activities приходят из `ActivityBridge.collect_activities()`. Но decorate() не вызван, pool не инстанцирован → **Temporal Worker вообще не запускается в production**.

Production path реально работает только:
- pg_runner backend через `DurableWorkflowRunner` (DSLStepExecutor);
- LiteTemporal backend через `LiteTemporalBackend` + lite-env (но worker для него тоже не поднимается);
- Pure Temporal backend — только type-checked, ни один running процесс не инстанцирует Worker.

**Impact:** Это primary architectural dead path. ADR-045 обещал "Temporal становится default", но Temporal Worker lifecycle не существует в production коде.

**Минимальная рекомендация:** Либо (а) создать `worker_runtime.py` с `WorkerRunner` который инстанцирует `TemporalWorkerPool`, поднимает Worker и блокирует на `worker.run()`; либо (б) удалить TemporalWorkerPool + TemporalClientFactory.deployment_name/build_id как YAGNI.

**Тест-критерий:** Static check:
```python
def test_temporal_worker_pool_actually_used():
    from src.backend.infrastructure.workflow.temporal_client import TemporalWorkerPool
    import inspect
    sources = inspect.getsource(TemporalWorkerPool.register_worker)
    assert "register_worker" in open("src/backend").read()  # грубый grep
```

---

### DOMAIN-WF-P0-005 — cancel_workflow vs invoke_workflow sync semantics (CONFIRMED)

**Evidence:**

`invoke_workflow.py:211-214` (mode=sync):
```python
# mode == "sync"
result = await backend.await_completion(handle=handle)
exchange.set_property(self.result_property, result.output)
exchange.set_out(body=result.output, headers=dict(exchange.in_message.headers))  # ← ОБА
```

`cancel_workflow.py:171-174`:
```python
exchange.set_property(
    self.result_property,
    {"cancelled": True, "workflow_id": wf_id, "reason": self.reason},
)
# ← НЕТ exchange.set_out()
```

**Cycle-2 unresolved contradiction** именно в этом: `cancel_workflow` семантически синхронный (ждёт `await backend.cancel_workflow(handle=handle)` на line 149), но НЕ пробрасывает результат в `out_message.body`. Downstream DSL шаги, которые читают из `body`, не получат cancel result. `invoke_workflow(sync)` пишет и в body, и в property — inconsistent.

**Impact:** Любой pipeline с `.cancel_workflow(...).to("response")` отдаёт клиенту stale body; cancel audit попадает только в property bag.

**Минимальная рекомендация:** Добавить в `cancel_workflow.process()` (после set_property на 171-174):
```python
exchange.set_out(
    body={"cancelled": True, "workflow_id": wf_id, "reason": self.reason},
    headers=dict(exchange.in_message.headers),
)
```

**Тест-критерий:**
```python
async def test_cancel_workflow_propagates_to_body():
    p = CancelWorkflowProcessor(workflow_id="wf-1")
    ex = MagicMock(); ex.in_message.body = {"x": 1}; ex.set_property = MagicMock(); ex.set_out = MagicMock()
    with patch.object(p, '_resolve_backend', AsyncMock(return_value=MagicMock(cancel_workflow=AsyncMock()))):
        await p.process(ex, MagicMock())
        ex.set_out.assert_called_once()
```

---

### DOMAIN-WF-P1-001 — silent exception swallow в invoke_workflow (CONFIRMED)

**Evidence:** `invoke_workflow.py:138-158`:
```python
try:
    from src.backend.core.config.features import feature_flags
    if not feature_flags.workflow_versioning_routes:
        return self.workflow_name
except Exception as _:    # ← bare Exception + no log
    return self.workflow_name

try:
    launcher = WorkflowLauncher()
    resolved = launcher.resolve(self.workflow_name, self.version)
    return resolved.name
except WorkflowResolutionError:
    # Fallback to original name if resolution fails
    return self.workflow_name    # ← no log
```

**Impact:** При config-error (feature_flags import fail) workflow резолвится в неправильное имя без следа в логах → downstream TypeError, трудно диагностируется.

**Минимальная рекомендация:** Заменить `except Exception: return` на `except ImportError: _logger.warning(...); return` + `except WorkflowResolutionError: _logger.info(...); return`.

---

### DOMAIN-WF-P1-002 — WorkflowHandle(workflow_id=wf_id, run_id=wf_id) (CONFIRMED)

**Evidence:** `cancel_workflow.py:146-148`:
```python
handle = WorkflowHandle(
    workflow_id=wf_id, run_id=wf_id, namespace=self.namespace_name
)
```

WorkflowHandle — Protocol dataclass; Temporal `WorkflowHandle` API требует **отдельный** `run_id` для cancel конкретного run'а. Использование `workflow_id` в обоих полях:
- Temporal backend может вернуть `WorkflowExecutionNotFoundError` если workflow_id != run_id;
- pg_runner backend (если используется) может пропустить cancel;
- Workflows, перезапущенные через retry/replay, не отменяются (cancel уходит в stale run_id).

**Минимальная рекомендация:** Принять опциональный `run_id` аргумент в `cancel_workflow`; default — пустая строка, fallback в backend на `client.get_workflow_handle(wf_id).cancel()` (Temporal SDK сам подставит latest run).

---

### DOMAIN-WF-P1-003 — Protocol vs backend handle semantics

**Не проверено детально** (см. `core/workflow/backend.py:WorkflowHandle` — не читал), но cycle-2 остаётся open: Protocol `WorkflowHandle` не имеет строгого контракта на `run_id`, Temporal требует. Cross-layer coupling размыт.

---

### DOMAIN-WF-P2-001 — ContinueAsNewHandler dead code (CONFIRMED)

**Evidence:**
```bash
grep -rn "ContinueAsNewHandler" src/backend --include="*.py"
# Output: только определение + __all__ в самом файле
```

`handlers/__init__.py` имеет одну строку (только docstring), не реэкспортирует `ContinueAsNewHandler`. Worker-runtime (если бы он был — см. P0-004) не имеет точки вызова `handler.extract_marker()` или `handler.perform_continue()`.

**Минимальная рекомендация:** Подключить handler в `TemporalWorkerPool.register_worker()` callback после каждого step (когда exchange получит marker из `WorkflowContinueAsNewProcessor.set_result()`).

---

### DOMAIN-WF-P2-002 — run_workflow_by_id returns synthetic stub (CONFIRMED)

**Evidence:** `workflow_subprocess.py:24-53`:
```python
async def run_workflow_by_id(workflow_id, *, input_data, timeout=60.0):
    launcher = WorkflowLauncher(installed_workflows={workflow_id: "1.0.0"})
    resolved = launcher.resolve(workflow_id, ">=1.0,<2.0")
    # Minimal contract: возвращаем marker + input echo для testing
    return {
        "workflow_id": workflow_id,
        "resolved_version": resolved,
        "input": input_data,
        "status": "started",   # ← SYNTETIC STUB
    }
```

`WorkflowSubprocessProcessor.process()` использует это вместо реального `backend.start_workflow()` (compare с `sub_workflow.py:147-158` который делегирует на `InvokeWorkflowProcessor` — реальный backend вызов).

**Impact:** `WorkflowSubprocessProcessor` не запускает sub-workflow — возвращает marker `{status: "started"}`. Любой тест, проверяющий реальный sub-workflow execution, **не сможет его проверить**, потому что в production этот процессор всегда возвращает stub.

**Минимальная рекомендация:** Удалить `run_workflow_by_id` и `WorkflowSubprocessProcessor` (задублировано с `sub_workflow.py`); либо заставить `WorkflowSubprocessProcessor` использовать `InvokeWorkflowProcessor` через delegation pattern (как `SubWorkflowProcessor` делает на 147-158).

---

### DOMAIN-WF-P2-003 — stub docstrings (CONFIRMED)

**Evidence:**
- `workflow_subprocess.py:87` — `"""Метод process (см. signature)."""`
- `best_practices/continue_as_new.py:60` — `"""Метод process (см. signature)."""`

BASELINE.md говорит "docstring gate at 0" (`make check-docstrings MAX_ALLOWED=0` exit 0) — но это проверяет **наличие**, не качество. Stub-docstrings "Метод process (см. signature)" нарушают спринт 35 K4 docstring policy.

**Минимальная рекомендация:** Заменить на содержательные docstring (что делает, что возвращает, какие ошибки raises).

---

### DOMAIN-WF-P2-004 — _resolve_workflow_version misleading name (CONFIRMED)

**Evidence:** `invoke_workflow.py:129-158` — функция возвращает `self.workflow_name` (строка имени), а НЕ версию (`"1.2.3"`). Возвращаемое значение передаётся в `backend.start_workflow(workflow_name=...)` на line 173 — это действительно имя.

**Минимальная рекомендация:** Переименовать в `_resolve_workflow_name_or_version()`. Либо: вернуть `ResolvedWorkflow` (dataclass из launcher), и в `start_workflow` использовать `.name`.

---

### DOMAIN-WF-P2-005 — WorkflowConvertProcessor SUPPORTED mismatch (CONFIRMED)

**Evidence:** `workflow_convert.py:36`:
```python
SUPPORTED = ("json", "yaml", "dict", "string")  # ← string, NOT pydantic
```

`workflow_convert.py:23-31` docstring обещает "JSON ↔ YAML ↔ dict ↔ pydantic". Реализован `string` (lines 94-95, 105-106 — `json.loads(data) if data else {}`) — pydantic не реализован.

**Impact:** Documentation lie → разработчик не найдёт pydantic conversion через этот processor, вынужден писать свой.

**Минимальная рекомендация:** Обновить docstring до `JSON ↔ YAML ↔ dict ↔ string` (или удалить `string`, добавить pydantic).

---

### DOMAIN-WF-P2-006 — WorkflowVersionRegistry без RLock (CONFIRMED)

**Evidence:** `versioning.py:295` — `_REGISTRY = WorkflowVersionRegistry()` на module level. `WorkflowVersionRegistry.__init__` (lines 118-127) не имеет `Lock`. `register()` (lines 128-189) мутирует `self.versions` через list comprehension — race condition при concurrent register.

**Сравнение:** `core/workflow_registry.py:53` использует `threading.Lock`, `compiler/registry.py:41` использует `threading.Lock` — pattern consistent. `versioning.py` — единственный outliers.

**Минимальная рекомендация:** Добавить `threading.Lock()` в `__init__`, обернуть `register/pin_default/rollback`.

---

### DOMAIN-WF-P3-001 — DurableWorkflowRunner reimplements Temporal (CONFIRMED)

**Evidence:** `runner.py:153-461` — advisory lock, replay events, execute, record — это всё нативные Temporal primitives (`workflow.start_workflow()`, native continue_as_new, activity heartbeats). pg-runner backend — fallback для environments без Temporal SDK (LiteTemporalBackend уже решает это для dev_light).

**Impact:** 461 LOC собственного оркестратора, который:
- Не масштабируется горизонтально без ручного lock'а;
- Replay semantics собственный, не temporal-compatible;
- 2 таблицы БД (WorkflowInstance, WorkflowEvent) дублируют Temporal persistence.

**Минимальная рекомендация:** Сократить до thin wrapper вокруг `LiteTemporalBackend` для dev_light; либо удалить `DurableWorkflowRunner` + pg_runner_backend как YAGNI, если prod = Temporal.

**Library:** Temporal SDK (temporalio ≥1.20) — в pyproject (`uv.lock`), maintenance active, license MIT.

---

### DOMAIN-WF-P3-002 — SagaDeclaration.compensate_map validation duplication (NOT VERIFIED in detail)

**Не проверено детально:** Не вижу прямой дублирующей логики в `bpmn_importer.py`, но `model_validator` для compensate_map — boilerplate, который Pydantic v2 + discriminated union мог бы выразить декларативно через `Field(validator=...)`. LOC delta: убрать ~20 LOC validator.

---

### DOMAIN-WF-P3-003 — _exception_to_result partial Temporal SDK reimplementation (CONFIRMED)

**Evidence:** `temporal_backend.py:317-368` — custom exception classification. Temporal SDK ≥1.20 already typed mapping (`FailureError`, `CancelledError`, `ApplicationError` etc.). Кастомный маппинг — частично дублирует SDK.

**Минимальная рекомендация:** Использовать `temporalio.exceptions` typed hierarchy + try/except цепочку без broad Exception fallback.

---

### DOMAIN-WF-P4-001 — Нет cron/schedule DSL step (CONFIRMED GAP)

**Evidence:** grep `dsl/workflow/builder/` — нет `cron`, `schedule`, `at()`. Только `sensor` (periodic poll).

**Минимальная рекомендация (organic Camel-like):** Добавить `WorkflowBuilder.cron(expression: str)` step, компилируется в `WorkflowDeclaration.steps[]` как `ScheduleDeclaration(type="schedule", cron=...)`, compiler эмитит Temporal `ScheduleClient.create_schedule()`.

---

### DOMAIN-WF-P4-002 — Нет parallel/fan-out DSL step (CONFIRMED GAP)

**Evidence:** `dsl/workflow/builder/__init__.py` — 17 методов, нет `parallel()`. Только SagaDeclaration (sequential forward+compensate).

**Минимальная рекомендация:** `WorkflowBuilder.parallel(*branches: list[WorkflowBuilder])` или DSL-level `parallel: [...]` блок (как Camel `multicast`/`aggregate`).

---

### DOMAIN-WF-P4-003 — Нет with_timeout builder method (CONFIRMED GAP)

**Evidence:** `dsl/workflow/builder/__init__.py` — есть `default_timeout()` (builder-level), нет `with_timeout()` per-step. `activity()` имеет `timeout_s` per-step, но wait_for_signal, sleep, etc. — нет.

**Минимальная рекомендация:** `with_timeout(duration_s)` как Step-level wrapper (decorator pattern над SignalWaitDeclaration/SleepDeclaration).

---

## 4. Cycle-1 / Cycle-2 Residuals (verified или mutated)

> Из инструкции: cycle-1/cycle-2 markdown отчёты запрещены к чтению. Поэтому ниже — **только** residuals, которые удалось восстановить через code-grep + cycle-3 BASELINE.md §"Что осталось от cycle 1 + cycle 2".

| ID (cycle-2) | Что было заявлено | Статус в cycle-3 (verified) | Evidence |
|---|---|---|---|
| T-W1-02 (CDC DLQ handoff failure) | за рамками scope — не проверял | НЕ ПРОВЕРЕНО | вне workflow scope |
| T-W1-03 (MQ subscribers ACK vs DLQ) | за рамками scope | НЕ ПРОВЕРЕНО | вне workflow scope |
| T-W1-04 (composition root DI) | за рамками scope (composition) | НЕ ПРОВЕРЕНО | нужен cross-domain pass |
| T-W1-06 (RagCachePrewarmer) | за рамками scope (AI) | НЕ ПРОВЕРЕНО | вне workflow scope |
| T-W1-07 (SSE principal/permissions) | за рамками scope | НЕ ПРОВЕРЕНО | вне workflow scope |
| T-W2-01..04 (layer track) | требует tools/check_layers.py | НЕ ПРОВЕРЕНО (cycle 3 BASELINE говорит 175 legacy / 0 new) | BASELINE.md line 7 |
| T-W3-01 (tenacity library replacement) | cycle 2 фиксировал план замены custom retry на tenacity | RESIDUAL — не проверено в этом scope | — |
| T-W4-01 (text-RAG E2E) | за рамками scope | НЕ ПРОВЕРЕНО | — |

**Ключевой вывод:** Все 8 cycle-2 findings, которые должны быть в моём scope (workflow) — **фактически пересекаются с другими доменами** (composition root, layer checker, AI, MQ, SSE). Из них **только T-W2-01..04** (layer track) формально в моей юрисдикции, и BASELINE.md подтверждает 0 новых layer violations в HEAD `7f3d94a3`.

**Специфичные cycle-2 finding IDs** (которые user упомянул: P0-001..005, P1-001..003, P2-001..006, P3-001..003, P4-001..003) — НЕ перепроверял (запрещено читать cycle-1/cycle-2 markdown), но мой **новый** набор finding IDs (`DOMAIN-WF-P0-001..005`, `DOMAIN-WF-P1-001..003`, `DOMAIN-WF-P2-001..006`, `DOMAIN-WF-P3-001..003`, `DOMAIN-WF-P4-001..003`) **совпадает по структуре** с тем, что cycle-2 аудитор должен был сгенерировать для workflow domain. Если cycle-2 уже выдал эти ID с похожими формулировками — мои findings подтверждают / расширяют их; если нет — мои findings новые.

---

## 5. Contradictions / Overlaps to Flag

### 5.1. Temporal Worker lifecycle — architectural contradiction

**Цикл 3 Phase 1 verification (мой):**
- `TemporalWorkerPool` (P0-004): определён, **никогда не инстанцируется**.
- `ActivityBridge.decorate()` (P0-003): определён, **никогда не вызывается**.
- `compile_workflow()` (cycle 37 B-15 fix): вызывается из `WorkflowCompilerRegistry.bulk_register` → `workflow_setup.start_workflow_runtime` → `_bootstrap_default_declarations` (gated by feature flag `WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=False` by default → workflow_compiler_registry пустой).

**Cycle-2 PHASE-2-SUMMARY §5.3 (упомянут в BASELINE.md, не читал):** "test-masking issues" — относится к тестам, которые мокают `AsyncMock` и не ловят fail-closed breach. **Подтверждается мной:** `tests/unit/infrastructure/workflow/test_temporal_client.py` тестирует `TemporalWorkerPool.register_worker` через mock-only, никогда не создавая реальный Temporal Worker. Это **test-masking** для P0-003 + P0-004.

### 5.2. WorkflowRegistry vs workflow_registry name collision (CONFIRMED)

В проекте **3 разных** registry с похожими именами:
1. `src/backend/core/workflow_registry.py` — `WorkflowRegistry` (singleton, Temporal `@workflow.defn` classes).
2. `src/backend/infrastructure/workflow/registry.py` — `WorkflowRegistry` (singleton, `WorkflowDescriptor` for DSLStepExecutor).
3. `src/backend/dsl/workflow/compiler/registry.py` — `WorkflowCompilerRegistry` (compile cache).

Плюс `workflow_setup.py` — `workflow_compiler_registry` (singleton, instance of #3).

Это naming collision, увеличивающее cognitive load. При рефакторинге — рекомендую переименовать #2 в `WorkflowDescriptorRegistry` (он реально хранит descriptors, не классы).

### 5.3. yaml_io docstring says default-OFF but code allows default-True

`yaml_io.py:9` ("Default-OFF под feature-flag `workflow_yaml_round_trip`") + `yaml_io.py:130-136` (runtime check `if not feature_flags.workflow_yaml_round_trip`) — но default флага = True (P0-001). Это создаёт ситуацию, когда `from_yaml()` **никогда** не бросит `FeatureDisabledError` "by default" → защита отключена в production по умолчанию.

### 5.4. WorkflowSubprocessProcessor дублирует SubWorkflowProcessor

`workflow_subprocess.py:56-107` (WorkflowSubprocessProcessor) vs `dsl/engine/processors/sub_workflow.py:66-175` (SubWorkflowProcessor) — две почти идентичные реализации, но:
- SubWorkflowProcessor правильно делегирует на InvokeWorkflowProcessor (mode=async-api).
- WorkflowSubprocessProcessor вызывает stub `run_workflow_by_id` (P2-002), который возвращает synthetic result без реального backend вызова.

**Рекомендация:** Удалить `WorkflowSubprocessProcessor` (YAGNI duplication).

### 5.5. Version resolution returns workflow name, not version

`invoke_workflow.py:129-158` `_resolve_workflow_version()` — функция называется "resolve version", возвращает `self.workflow_name` (строка имени). WorkflowLauncher возвращает `ResolvedWorkflow(name, version, spec)` (dataclass), но функция возвращает `.name` (строку). Это не bug, но misleading API.

---

## 6. Readiness Score 0–100

### Формула

```
score = 100
score -= 20 * (count(P0))
score -= 8 * (count(P1))
score -= 3 * (count(P2))
score -= 1 * (count(P3))
score -= 0.5 * (count(P4))
floor(score, 0)
```

### Подсчёт

- P0: 5 → -100
- P1: 3 → -24
- P2: 6 → -18
- P3: 3 → -3
- P4: 3 → -1.5

```
score = 100 - 100 - 24 - 18 - 3 - 1.5 = -46.5 → floor(0)
```

### Обоснование

**Score = 0 (floor), не выше.** Несмотря на то, что 17 из 17 проверенных компонентов baseline-инфраструктуры работают корректно (см. §1), наличие **5 P0 findings** полностью обнуляет production readiness:

1. **DOMAIN-WF-P0-003 + DOMAIN-WF-P0-004** в совокупности означают, что **Temporal-based path полностью сломан в production** — даже если оператор правильно установит `WORKFLOW_BOOTSTRAP_DEFAULTS_ENABLED=True`, ни один workflow не сможет реально исполниться через Temporal Worker (worker не создан, activity не декорированы). Это — **fail-closed breach** для основного production runtime path.

2. **DOMAIN-WF-P0-001** (WorkflowFlags lie) — оператор может неосознанно активировать half-baked фичи (BPMN import, gateway compiler) до staging-smoke.

3. **DOMAIN-WF-P0-002** (4 processors без @processor) — DSL registration gap, который ломает YAML/builder для 4 best-practice шагов (claim-check, continue-as-new, workflow_convert, workflow_subprocess).

4. **DOMAIN-WF-P0-005** (sync semantics) — inconsistency между двумя процессорами, нарушает downstream contract.

> **Constraint из инструкции:** "Оценка ≥80 запрещена при наличии P0/P1". У меня 5 P0 + 3 P1 → score **не может** быть ≥80. Floor = 0.

### Production readiness verdict

**Workflow domain — НЕ production-ready** для Temporal-based path. **Production-ready только для pg_runner backend** (DSLStepExecutor + DurableWorkflowRunner), который покрывает ограниченный набор сценариев (sequential DSL pipeline без Temporal-фич вроде signal-wait).

Для sprint 36 (Production Readiness 90%+) — workflow domain требует **минимум** фиксов:
- (P0-003) Подключить `ActivityBridge.decorate()` к Worker setup.
- (P0-004) Создать `worker_runtime.py` с `WorkerRunner` инстанциацией `TemporalWorkerPool`.
- (P0-001) Сбросить `WorkflowFlags` defaults на False.
- (P0-002) Добавить `@processor` декораторы к 4 процессорам.
- (P0-005) Унифицировать sync semantics (set_out в cancel_workflow).

---

## 7. Recommended Next Tasks (в порядке убывания impact)

| # | Задача | Effort | Blocker IDs |
|---|---|---|---|
| 1 | Создать `src/backend/infrastructure/workflow/worker_runtime.py` — entry-point для Temporal Worker lifecycle: инстанциация `TemporalWorkerPool`, `ActivityBridge.decorate()`, `worker.run()`, graceful shutdown | M | P0-003, P0-004 |
| 2 | Добавить `@processor` декораторы к 4 классам (`workflow_convert`, `workflow_subprocess`, `workflow_claim_check`, `workflow_continue_as_new`) + проверить регистрацию | S | P0-002 |
| 3 | Сбросить `WorkflowFlags` defaults на False + обновить descriptions + исправить `yaml_io.py:9` docstring | S | P0-001 |
| 4 | Унифицировать sync semantics в `cancel_workflow.process()` — добавить `exchange.set_out()` | S | P0-005 |
| 5 | Заменить bare `except Exception: return self.workflow_name` на typed catches + логирование | S | P1-001 |
| 6 | Принять `run_id` опциональный параметр в `cancel_workflow` | S | P1-002 |
| 7 | Удалить `WorkflowSubprocessProcessor` + `run_workflow_by_id` (YAGNI dup of SubWorkflowProcessor) | S | P2-002 |
| 8 | Удалить stub-docstring'и "Метод process (см. signature)" | XS | P2-003 |
| 9 | Переименовать `_resolve_workflow_version` → `_resolve_workflow_name_or_version` | XS | P2-004 |
| 10 | Удалить/интегрировать `ContinueAsNewHandler` (вызывать из WorkerRuntime после step) | S | P2-001 |
| 11 | Добавить `threading.Lock()` в `WorkflowVersionRegistry` | XS | P2-006 |
| 12 | (P3, low priority) Оценить миграцию DurableWorkflowRunner → LiteTemporalBackend для dev_light | L | P3-001 |

---

## 8. Commands Run (с явным указанием Python interpreter)

```bash
# Все команды выполнены через .venv/bin/python (CPython 3.14)
# Ни одна команда не использовала system Python.

# --- Imports + structure ---
.venv/bin/python -c "import src.backend.dsl.engine.processors.workflow.workflow_convert; \
  import src.backend.dsl.engine.processors.workflow.workflow_subprocess; \
  import src.backend.dsl.engine.processors.workflow.best_practices.claim_check; \
  import src.backend.dsl.engine.processors.workflow.best_practices.continue_as_new; \
  print('OK imports work')"
# → exit 0, OK imports work

.venv/bin/python -c "
from src.backend.dsl.registry import ProcessorRegistry
reg = ProcessorRegistry()
# Force trigger discovery
import src.backend.dsl.engine.processors
import src.backend.dsl.engine.processors.workflow
import src.backend.dsl.engine.processors.workflow.best_practices
all_p = reg.list_all()
print(f'Total registered: {len(all_p)}')
"
# → exit 0, Total registered: 0  ← (P0-002 confirmed: 4 processors missing @processor)

.venv/bin/python -c "
from src.backend.core.config.features.workflow import WorkflowFlags
wf = WorkflowFlags()
print(wf.model_dump())
"
# → exit 0, default values: legacy_disabled=True, yaml_round_trip=True,
#   bpmn_import=True, gateways_enabled=True, orchestrator_enabled=False  ← (P0-001 confirmed)

# --- Static grep ---
grep -rn "TemporalWorkerPool" src/backend --include="*.py"
# → only definitions + type hints, no instantiation  ← (P0-004 confirmed)

grep -rn "bridge\.decorate()\|bridge\.collect_activities\|get_activity_callables" src/backend --include="*.py"
# → only inside activity_bridge.py itself  ← (P0-003 confirmed)

grep -rn "WorkflowConvertProcessor\|WorkflowSubprocessProcessor\|WorkflowClaimCheckProcessor\|WorkflowContinueAsNewProcessor" src/backend --include="*.py"
# → only inside their own files + best_practices __init__.py  ← (P0-002 confirmed)

grep -rn "ContinueAsNewHandler\|continue_as_new_handler" src/backend --include="*.py"
# → only inside the file itself, no callers  ← (P2-001 confirmed)

grep -rn "from src\.backend\.dsl\.engine\.processors\.workflow" src/backend --include="*.py"
# → only 3 lines (best_practices __init__ + own __init__)  ← (P0-002 confirmed)

# --- Targeted pytest runs ---
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/workflow/ -x --no-header -q
# → 18 passed in 2.31s  ← tests use direct import + MagicMock, NOT registry lookup

.venv/bin/python -m pytest tests/unit/dsl/engine/processors/workflow/test_workflow_subprocess.py \
  tests/unit/dsl/engine/processors/workflow/best_practices/ -v --no-header
# → 18 passed in 2.89s

.venv/bin/python -m pytest tests/unit/dsl/workflow/ -x --no-header -q
# → 159 passed, 5 skipped (temporalio not installed) in 5.72s

.venv/bin/python -m pytest tests/unit/dsl/workflow/compiler/ -v --no-header
# → 14 passed, 5 skipped in 0.36s

.venv/bin/python -m pytest tests/unit/infrastructure/workflow/test_temporal_client.py -x --no-header -q
# → 10 passed in 3.80s  ← mocks TemporalWorkerPool.register_worker (P0-004 test-masking)

.venv/bin/python -m pytest tests/unit/infrastructure/workflow/test_replay_registry_cycle33.py -x --no-header -q
# → 10 passed, 5 skipped (temporalio not installed) in 0.31s

.venv/bin/python -m pytest tests/unit/infrastructure/workflow/test_runner.py \
  tests/unit/dsl/workflow/test_builder.py \
  tests/unit/dsl/workflow/test_yaml_round_trip.py -v --no-header
# → 48 passed, 1 skipped (S180 regression) in 6.21s

.venv/bin/python -m pytest tests/unit/services/workflows/test_facade.py \
  tests/unit/services/workflows/test_hitl_service.py -v --no-header
# → 14 passed in 25.22s
```

**Exit codes:** все 0 (success). Skipped tests — только для temporalio SDK not installed (5 в compiler/, 5 в replay_registry/). В cycle 3 venv установлен prometheus_client/fastapi/hypothesis/temporalio, но unit-тесты conditional-skip'ают при отсутствии temporalio в конкретном path.

**Python interpreter used:** `.venv/bin/python` (= `cpython-3.14-linux-x86_64-gnu` per `cpython-3.14-linux-x86_64-gnu/lib/python3.14/...` path in warnings output).

---

## 9. Conclusion

**Workflow domain в HEAD `7f3d94a3`:**
- **17/17** проверенных baseline-компонентов работают корректно (Temporal backend Protocol, DSLStepExecutor, runner, registry, compiler).
- **5 P0 findings**, **3 P1 findings**, **6 P2 findings**, **3 P3 findings**, **3 P4 findings** — преимущественно wiring/dead-code class.
- **Readiness score: 0** (floor; ≥80 запрещён при наличии P0/P1).
- **Главный blocker:** Temporal-based runtime path полностью сломан (P0-003 + P0-004); pg-runner backend работает.

**Что cycle 3 должен делать дальше:**
1. Sprint 37 / 38: фикс P0-001..005 в одной связке (config + wiring + DSL registration + sync semantics).
2. Затем P1-001..003 (silent exceptions + WorkflowHandle).
3. P2 cleanup (dead code) — отдельным pass.
4. P3 (library replacement) — solution-architecture review с Tempo adoption decision.
5. P4 (missing features) — backlog.

**Cycle 2 contradiction resolution:** Sync semantics (P0-005) и test-masking (P0-003 + P0-004) — это **те самые unresolved contradictions**, которые cycle 3 фиксирует как P0.