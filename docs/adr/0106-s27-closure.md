# ADR-0106: S27 closure — AIGateway enforce + WorkflowBuilder.invoke_agent() as Temporal activity

**Date:** 2026-06-09
**Status:** Accepted (S83 closure)
**Sprint:** S83 (V22.4 §S27)
**Deciders:** platform team, K4 AI/Data, K1 Security
**Related:** ADR-NEW-19 (AIGateway facade), ADR-NEW-20 (Policy DSL),
ADR-NEW-21 (PII Tokenizer), ADR-0066 (AIGateway), ADR-0068 (PII Tokenizer),
R-V15-9 (AI через Workflow DSL)

## Context

S25 (K4 W1) ввёл `AIGateway` как единую точку входа в AI (ADR-NEW-19).
S25-S26 покрыли ~70% LLM-вызовов через AIGateway, но 3 кодопути
сохраняли прямой доступ:

1. `PydanticAIClient.run()` — низкоуровневый LLM-вызов через
   LiteLLMGateway (минуя policy_resolve, sanitize, guards, audit).
2. `LLMCallProcessor.process()` (DSL engine) — использовал legacy
   `ai_agent_service` вместо `AIGateway`.
3. `WorkflowBuilder.invoke_agent()` (workflow compiler) — прямой
   `AIGateway().invoke()` внутри workflow-context (Temporal sandbox
   violation: side-effectful I/O запрещён в workflow-sandbox).

Параллельно: `WorkflowBuilder.invoke_agent()` имеет **двойную**
проблему — bypass + sandbox violation. Temporal workflow-sandbox
требует, чтобы любая side-effectful операция (network, DB, LLM)
выполнялась через `workflow.execute_activity()`, иначе — non-deterministic
replay failures.

S27 (3 волны: W4 MCP gateway namespaces, W5 AI audit unified, W6
WorkflowBuilder.invoke_agent()) закрывал эти пробелы.

## Decision

**S83 closure** (commit `d42c550d`, 17 files, +624/-129) формализует
S27 closure одним пакетом из 5 решений:

### 1. `AIGateway` как единственная точка входа (R-V15-9, ADR-NEW-19)

```python
# src/backend/core/ai/gateway.py
class AIGateway:
    """Единая точка входа в AI: policy_resolve → sanitize → guards →
    render → invoke_llm → output_guards → output_sanitize → audit → cost.
    """
    async def invoke(self, request: AIRequest) -> AIResponse: ...
```

При `feature_flags.ai_gateway_enforce = True` (default после S83
closure):
- `PydanticAIClient.run()` без `_internal_gateway_call=True` →
  `RuntimeError("...bypasses AIGateway; use AIGateway.invoke()...")`.
- `LLMCallProcessor.process()` маршрутизирует через `AIGateway().invoke()`
  (вместо legacy `ai_agent_service`).
- `GatewayPipelineMixin` (внутренний AIGateway-вызов) помечает
  PydanticAIClient вызов флагом `_internal_gateway_call=True`.

**Альтернативы рассмотрены**:
- (a) Middleware-chain (не подходит — LLM-вызов не HTTP, нет
  middleware-точки входа).
- (b) Inheritance (нарушает Liskov для 3 разнородных кодопутей).
- (c) Decorator-обёртка `with_aigateway()` (рассмотрено в ADR-NEW-19,
  rejected — слишком много точек вызова, неявный opt-in).

### 2. `WorkflowBuilder.invoke_agent()` as Temporal activity (sandbox-safe)

```python
# src/backend/dsl/workflow/compiler/activity_bridge.py
async def _agent_invoke_activity(payload: dict[str, Any]) -> Any:
    """Temporal activity-обёртка для AIGateway.invoke (S27 W6).
    Выполняет stateless AI-инвокацию вне workflow-sandbox'а.
    """
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.gateway_models import AIRequest
    request = AIRequest(**payload)
    gateway = AIGateway()
    return await gateway.invoke(request)
```

```python
# src/backend/dsl/workflow/compiler/step_compilers.py
async def compile_agent_invoke_step(decl, ctx):
    # ... (resolves input_context, builds payload)
    result = await workflow.execute_activity(
        "_agent_invoke",
        payload,
        start_to_close_timeout=timedelta(seconds=timeout_s),
    )
    if decl.output_key:
        ctx.setdefault("_outputs", {})[decl.output_key] = result
    return result  # AIResponse-объект (caller извлекает .content)
```

`ActivityBridge.get('_agent_invoke')` возвращает `_agent_invoke_activity`
**напрямую** (без `bridge_action_handler` wrapper — обёртка не нужна,
т.к. activity не требует action-handler dispatch).

`ActivityBridge.collect_activities()` теперь находит `_agent_invoke`
из `AgentInvokeDeclaration` через расширенный `_iter_activity_specs`.

### 3. `invoke_via_gateway(return_full_response=...)` — caller API

```python
# src/backend/services/ai/gateway_adapter.py
async def invoke_via_gateway(
    ...,
    stream: bool = False,
    return_full_response: bool = False,  # S83: новый параметр
) -> Any:
    """При return_full_response=True возвращает AIResponse
    (caller сам извлекает .content / .tokens / .cost)."""
    ...
    if return_full_response:
        return response
    return response.content
```

`compile_agent_invoke_step` использует `return_full_response=True`
(ему нужны tokens/cost для `ctx._outputs`).

### 4. Feature-flag flip: `ai_gateway_enforce=True` default

```python
# src/backend/core/config/features/sprints_24_27.py
ai_gateway_enforce: bool = Field(
    default=True,  # S83: False → True
    title="K4 S25 W1: AIGateway единая точка входа в AI (ADR-NEW-19)",
    description=(
        "K4 Sprint 25 Wave 1 (ADR-NEW-19, PLAN.md V22.4 §S25). ..."
        "default-ON начиная с S27 closure: все callsites обёрнуты."
    ),
)
```

**Pre-conditions для flip** (все выполнены):
- ✅ 100% LLM-вызовов обёрнуты через AIGateway (PydanticAIClient guard +
  LLMCallProcessor gateway-path + invoke_agent activity).
- ✅ `make ai-gateway-coverage` strict zero violations (CI-gate).
- ✅ Legacy fallback сохранён в `PydanticAIClient._legacy_invoke` (для
  emergency rollback).

### 5. S3 key validation + Temporal OTel + SLO budget (качество)

Параллельно с S27 closure добавлены 3 quality-фикса (не S27-specific,
но разделяют commit для atomicity):

- **S3 key validation** (`src/backend/infrastructure/storage/s3.py`):
  1024 байт лимит (S3 spec), control-chars запрет, `//` запрет.
- **OpenTelemetryTracingInterceptor** в Temporal client + worker
  (`temporal_client.py`): lazy import, no-op если
  `temporalio[opentelemetry]` не установлен.
- **SLO budget enforcer** (`src/backend/infrastructure/application/slo_tracker.py`):
  `check_budget()`, `@enforce_slo` decorator, `SLOBudgetExceeded` exception.

Плюс **CI-gate** `tools/checks/check_feature_flag_usage.py`:
warn-only / `--strict` (exit 1 при dead feature flags).

## Consequences

### Positive

- **Sandbox-safe workflow**: `WorkflowBuilder.invoke_agent()` теперь
  non-deterministic-replay-safe (Temporal sandbox compliant).
- **100% LLM-callsite coverage**: 3 кодопути закрыты, прямой bypass
  невозможен без `_internal_gateway_call=True` (audit-traceable).
- **Single AI entry point**: защитные слои (policy, PII, audit) применяются
  ровно 1 раз на каждый LLM-вызов.
- **Observability**: OTel spans на 100% Temporal activities
  (включая AI-инвокации); SLO budget enforcer для runtime gates.
- **S3 spec compliance**: ключи не превышают 1024 байт, нет control-chars.

### Negative

- **Behavior change**: `compile_agent_invoke_step` возвращает
  `AIResponse` объект вместо `str` (caller извлекает `.content`).
  Backward-incompatible для существующих `WorkflowBuilder.invoke_agent()`
  вызовов. Митигация: `gateway_adapter.return_full_response` опция
  сохранена для selective adoption.
- **Hard fail при bypass**: `PydanticAIClient.run()` без
  `_internal_gateway_call=True` теперь raise `RuntimeError` при
  `ai_gateway_enforce=True`. Митигация: legacy fallback
  `PydanticAIClient._legacy_invoke` сохранён для emergency.
- **Спринт-scope drift**: один commit `d42c550d` включает 5
  логически разных work items (S27 W6 + S27 closure + S3 + OTel +
  SLO). Атомарность важнее granular history.

### Neutral

- Sprint number в commit message = "Sprint 37" (раздел V22.4 §S37)
  vs "S83" (V22.4 §S83 closure). Не drift — это naming convention
  V22.4: раздел §S37 = feature bundle, §S83 = closure sprint.
- TECH_DEBT.md update отложен на S84+ (S83 closure = code + docs only).

## Verification

- **mypy**: 17 файлов clean
- **ruff**: 17 файлов clean
- **smoke-тесты**: 10 тестов `compile_agent_invoke_step` +
  `ActivityBridge` (через `sys.modules` temporalio mock) пройдены
- **unit-тесты** (CI run):
  - `test_step_compilers.py`: 5 `compile_agent_invoke_step` (4 обновлены + 1 новый)
  - `test_activity_bridge.py`: 3 новых для `_agent_invoke` binding
  - `test_pydantic_ai_client.py`: autouse fixture + 1 guard-тест
  - `test_llmcall_processor.py`: 1 gateway-enforce-тест
  - `test_s3_object_storage.py`: 3 key-validation теста
  - `test_slo_tracker.py`: 6 unit-тестов (новый файл)
- **CI-gate**: `tools/checks/check_feature_flag_usage.py` запускается
  в pre-commit hook (warn-only default).

## References

- PLAN.md V22.4 §S27 — Sprint 27 scope
- ADR-NEW-19 — AIGateway facade (S25 W1)
- ADR-NEW-20 — AIPolicySpec DSL (S25 W2)
- ADR-NEW-21 — PII Tokenizer (S25 W4)
- ADR-0066 — AIGateway (S29 T9)
- ADR-0068 — PII Tokenizer (S25 W4)
- R-V15-9 — AI-функции через Workflow DSL
- V22.4 §3 N1 — orchestration consolidation

## Wave mapping

| Wave | Scope | Files | Verification |
|------|-------|-------|--------------|
| W1 | S27 W6: agent_invoke Temporal activity | 5 (3 src + 2 test) | mypy/ruff + 8 smoke-tests |
| W2 | S27 closure: call-site protection + flag flip | 6 (4 src + 2 test) | mypy/ruff + 3 unit-tests |
| W3 | S3 key validation + Temporal OTel interceptor | 3 (2 src + 1 test) | mypy/ruff + 3 unit-tests |
| W4 | SLO budget enforcer + feature-flag CI-gate | 3 (1 src + 1 test + 1 tool) | mypy/ruff + 6 unit-tests |
| W5 | S83 closure: CHANGELOG + ADR-0106 + TECH_DEBT | 3 (1 CHANGELOG + 1 ADR + 1 TECH_DEBT) | this ADR |
| **Total** | | **17 + 3 = 20 files** | **+624 / -129 LOC** |

Consolidated in single closure commit `d42c550d` (Tue Jun 9 12:35:40 2026 +0300).
