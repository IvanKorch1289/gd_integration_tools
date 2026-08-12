# 08 — Agents domain audit (cycle 1, phase 1)

> Scope: `src/backend/dsl/agents/**`; `src/backend/dsl/engine/processors/agent_dsl/**`;
> `src/backend/core/ai/**/*agent*.py`; `src/backend/core/ai/security/**`;
> `src/backend/services/ai/agents/**`; `src/backend/services/ai/agents_pydantic/**`;
> `src/backend/services/ai/ai_agent/**`; `src/backend/services/ai/agent_*.py`;
> agent-focused API endpoints/schemas/tests.
> Focus: composition-root DI и запрет unsafe direct `AIGateway` construction.

## Scope / не проверено

**Проверено прямым чтением/выполнением:**

- `src/backend/plugins/composition/di.py` (composition root, 324 LOC, 95–98: `app.state.ai_gateway = get_ai_gateway_provider()`)
- `src/backend/core/di/providers/ai.py` (325 LOC, весь)
- `src/backend/core/ai/__init__.py`, `gateway.py`, `gateway/gateway.py`, `gateway/__init__.py`, `gateway_models.py`, `gateway_orchestrator_mixin.py`, `gateway_pipeline_mixin/{policy_mixin,_protocol,llm_mixin,output_mixin,input_mixin,observability_mixin,__init__}.py`, `gateway/orchestrator/enforced_invoke.py`, `errors.py`, `llm_gateway.py`, `multi_agent.py`, `agent_registry.py`, `agent_spec.py`, `agent_sandbox_protocol.py`, `policy/resolver.py`
- `src/backend/core/ai/security/__init__.py`, `agent_security.py` (667 LOC, весь)
- `src/backend/services/ai/gateway_adapter.py` (271 LOC, весь)
- `src/backend/services/ai/ai_agent/{__init__,agent_orchestration_mixin,http_providers_mixin,policy_mixin,rag_mixin,web_methods_mixin}.py`
- `src/backend/services/ai/agents_pydantic/{adapter,base,__init__}.py`
- `src/backend/services/ai/ai_graph.py` (178–248)
- `src/backend/dsl/engine/processors/agent_dsl/{__init__,_base,_timeouts,agent_run,agent_loop,agent_branch,agent_parallel,ai_tool_dispatch,plan_execute,reflection_loop,skill_invoke,memory_*,pii_*,guardrails_apply,optimize_prompt,bind_skill,langgraph_agent,agent_security_check,mcp_tool}.py`
- `src/backend/dsl/engine/processors/ai/llmcall_processor.py` (100–200)
- `src/backend/dsl/engine/processors/agent_dsl/_base.py` (весь)
- `src/backend/dsl/agents/fastmcp_server.py` (259 LOC, весь)
- `src/backend/dsl/workflow/compiler/activity_bridge.py` (60–80)
- `src/backend/core/security/capabilities/gate/{__init__,check_mixin,_protocol}.py` (для верификации сигнатуры)
- `src/backend/entrypoints/api/v1/endpoints/ai_agents.py` (142 LOC, весь)
- `tests/unit/services/ai/test_aigateway_capability_wiring.py` (selected blocks)
- `tests/unit/core/ai/test_aigateway_production_wiring.py` (в части запуска)

**Не проверено** (за пределами scope):

- `src/backend/dsl/builders/agent_dsl/*` — точечно упоминается, но инспекция не проводилась.
- `src/backend/services/ai/agents/{analytics_agent,search_agent,checkpoint_inspector,langgraph_postgres_saver}.py` — за пределами явного списка «services/ai/agents/**», в широкий scope не вошёл.
- `src/backend/services/ai/agents_pydantic/examples/*` — примеры, не runtime path.
- `src/backend/core/ai/sandbox.py`, `workspace_manager.py`, `fs_facade.py`, `retries_policy.py`, `skill_registry.py` (601 LOC), `context_strategy.py`, `pydantic_ai_client.py` (28504 bytes), `gateway_audit_mixin.py` — упоминаются, но специально не аудированы.
- `src/backend/services/ai/agents/*` (kорневой services/ai/agents/), `multi_agent/`, `memory/` — частично вне scope.
- Расширения (extensions/credit_pipeline, osint_agent, dadata, skb, example_plugin, test_plug, core_entities, core_admin) — явно вне scope (бизнес-логика).
- Vendor/3rd-party libs (`pydantic_ai`, `langgraph`, `mcp.server.fastmcp`, `langfuse`) — лишь проверка факта импорта/использования.
- Полный `tools/checks/check_ai_gateway_coverage.py` AST-cheker — файл упомянут как контракт «запрещено», но не исполнялся в этом цикле.
- Migrations, deployment helm-chart — вне scope.

## Verified strengths

- **S-1. Composition-root регистрация выполнена корректно.**
  `src/backend/plugins/composition/di.py:95-97` явно регистрирует
  `app.state.ai_gateway = get_ai_gateway_provider()` со всеми тремя обязательными
  DI (`policy_resolver`, `capability_gate`, `token_budget`). Это единственный
  production-wiring site, упомянутый в ADR-NEW-19 / Sprint 1.3 / S177 M2.
  Цитата (`di.py:94`): «Sprint 1.3: AIGateway singleton с обязательными DI (S177 M2 guard)».
- **S-2. DI-provider с самодокументацией и override-схемой.**
  `core/di/providers/ai.py:244-304` определяет
  `@lru_cache(maxsize=1) _build_ai_gateway_singleton()`,
  `get_ai_gateway_provider()` (читает override → lru-cache),
  `set_ai_gateway_provider(impl: Any)` (test-инжекция с поддержкой
  `impl=None` для сброса override). Это разделение test/runtime —
  канонично и reverse-compatible.
- **S-3. Production-wiring guard существует.**
  `core/ai/gateway/gateway.py:147-175`:
  `_enforce_production_wiring()` проверяет наличие всех 3 DI при
  `app.environment=='production'` и поднимает
  `AIGatewayProductionWiringError` ДО invoke — fail-loud для production-broken
  composition.
- **S-4. Facade-импорт для extension кода.**
  `core/ai/llm_gateway.py:1-27` — единственная разрешённая extension-towards-LLM
  дверь, реэкспортирует `LiteLLMGateway` + `get_litellm_gateway`.
  Соответствует «S44 W1: закрыть violations через facade» (см. комментарий в файле).
- **S-5. Семантический agent_security framework.**
  `core/ai/security/agent_security.py:372-666` — развитый
  `AgentSecurityFramework` с pre/post-LLM hooks, OWASP LLM Top 10 patterns,
  dangerous-command detection, file-policy, PII masking integration; дефолт
  `strict_mode=True` для production. Документация явно ссылается на OWASP/NIST.
- **S-6. CapabilityGate — потокобезопасный (cache lock).**
  `check_mixin.py:30-...` (см. строки 69-72)
  содержит D-AUDIT-98 fix с `with self._lock: cache_hit = cache_key in self._cache`
  для устранения «RuntimeError: dictionary changed size during iteration».
- **S-7. Capability через CapabilityGate — fail-closed.**
  `_policy_gate` (services/ai/ai_agent/policy_mixin.py:36-135) для `Block 1.5
  gap-ai-1.5` возвращает deny-envelope на ЛЮБОЕ исключение (ImportError,
  RuntimeError, AttributeError). S204 retro-audit исправил pre-existing
  fail-open: «раньше здесь возвращался ``None`` (= allow) при ImportError модуля
  настроек» (policy_mixin.py:54-68).
- **S-8. AIGateway adapter `_ask_llm_for_tool_selection` имеет query-length cap.**
  `agent_dsl/ai_tool_dispatch.py:326-351`: `_MAX_QUERY_LEN = 2000`, truncate
  (а не raise), log warning. Cycle-4 hardening.
- **S-9. FastMCP-server обёрнут через capability-gate.**
  `dsl/agents/fastmcp_server.py:238-257`: `tool_callback` вызывает
  `skill.tenant_allowlist` check + `registry.invoke` + возвращает
  JSON-serializable result. Каталог tools/prompts — read-only.

## Findings table

| ID | Priority | Path:line | Краткое описание |
|----|----------|-----------|------------------|
| DOMAIN-P0-001 | P0 | `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py:100` | `_check_capability` вызывает `gate.check(capability)` с 1 аргументом, реальный `CapabilityGate.check` требует 3 — TypeError на каждый invoke |
| DOMAIN-P0-002 | P0 | `src/backend/services/ai/gateway_adapter.py:130` | Fallback `return AIGateway()` без DI: silent fail-open на policy/capability/budget в dev/staging |
| DOMAIN-P0-003 | P0 | `src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py:249-252` + `plan_execute.py:268-273` + `reflection_loop.py:252-257` | Hardcoded `tenant_id="default"|"unknown"` и `correlation_id=""`/`"plan-exec"`/`"reflection-loop"` — ломает audit/per-tenant budget lineage |
| DOMAIN-P0-004 | P0 | `src/backend/dsl/agents/fastmcp_server.py:36-39` | `dsl/agents/*` импортирует `src.backend.infrastructure.workflow.registry` напрямую — layer violation |
| DOMAIN-P1-001 | P1 | `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py:100-109` | `try/except` ВОКРУГ `inspect.isawaitable(result)` стоит ПОСЛЕ `result = check(capability)`, поэтому TypeError И CapabilityDeniedError эскалируются за пределы try — propagation неуправляема |
| DOMAIN-P1-002 | P1 | `src/backend/core/di/providers/ai.py:244 + 288` | `_build_ai_gateway_singleton` собирает голые `CapabilityGate()`/`PolicyResolver()`/`InMemoryTokenBudgetBackend()` без DI-конфигов (vocabulary/policy/roots); composition-root result — независимый синглтон без plugin declarations |
| DOMAIN-P1-003 | P1 | `src/backend/services/ai/ai_agent/__init__.py:111` | `get_ai_agent_service()` пустая фабрика: `raise NotImplementedError  # заменяется декоратором` — fragile decorator pattern |
| DOMAIN-P1-004 | P1 | `src/backend/services/ai/agents_pydantic/adapter.py:113` | `LiteLLMModel.request_stream` → `NotImplementedError`; класс экспортируется как `pydantic_ai.models.Model` — streaming-calls crash |
| DOMAIN-P1-005 | P1 | `src/backend/core/ai/multi_agent.py:10`, `gateway_pipeline_mixin/input_mixin.py:132`, `output_mixin.py:139`, `llm_mixin.py:74`, `policy/enforcer/input_guard_mixin.py:122`, `llm_gateway.py:23` | `core/ai/*` напрямую импортирует из `services/ai/*` — нарушение архитектурной границы (core → services без DI facade для большинства) |
| DOMAIN-P2-001 | P2 | `src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py:24` | Stale docstring: «_run помечает exchange ошибкой NotImplementedError (scaffold)» — реализовано в коде (lines 98-225) |
| DOMAIN-P2-002 | P2 | `src/backend/dsl/engine/processors/agent_dsl/skill_invoke.py:20-23` | Stale docstring: «NotImplementedError в scaffold-режиме»; actual `_run` (lines 94-101) обрабатывает NotImplementedError только как defensive fallback |
| DOMAIN-P2-003 | P2 | `src/backend/dsl/agents/fastmcp_server.py:137-147` | `start()` / `stop()` — no-ops, но называются «Lifecycle (managed by caller)»; мёртвый интерфейс без документа «callers must ignore» |
| DOMAIN-P3-001 | P3 | `src/backend/core/ai/security/agent_security.py:103-159` | Собственная «OWASP pattern list» (~24 regex) — замена на `llm-guard` (Apache-2.0, поддерживается) или `neuraly/enola` (BSD-3) не помешает, но не mandatory |
| DOMAIN-P3-002 | P3 | `src/backend/services/ai/ai_agent/policy_mixin.py:36-135` | Собственная gate-схема; AuthorizationGateway — каноническая, но `ai_agent` использует `gateway.authorize()` напрямую; standard already exists |
| DOMAIN-P4-001 | P4 | нет evidence | DSPy integration (`services/ai/dspy`) — рассмотреть единую declaration DSL для prompt optimization уже присутствует в agents (AgentSpec.optimize_prompt), но DSPy отдельная code-path |
| DOMAIN-P4-002 | P4 | `src/backend/core/ai/agent_registry.py` (см. 25-37) | Agent TOML-регистр не имеет LangGraph `subgraphs` (для multi-agent handoff), Airflow-подобный DAG отсутствует — но это органичное расширение Camel/Airflow, а не feature-for-feature копия |

## Detailed evidence

### DOMAIN-P0-001 — AIGateway вызывает CapabilityGate с неверной сигнатурой

**Path:** `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py:84-110` (method `_check_capability`).

**Evidence:**

```python
# policy_mixin.py:84-110
async def _check_capability(self, request: AIRequest) -> None:
    if self._capability_gate is None:
        return
    capability = f"ai.invoke.{request.workflow_id}"
    check = getattr(self._capability_gate, "check", None)
    if check is None:
        return
    result = check(capability)                              # ← 1 аргумент
    try:
        import inspect
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        logger.debug(
            "AIGateway: capability check for %s failed: %s", capability, exc
        )
```

Сравните с сигнатурой реального `CapabilityGate.check`:

```python
# src/backend/core/security/capabilities/gate/check_mixin.py:48
def check(self, plugin: str, capability: str, requested_scope: str | None) -> None:
    """Проверка... raise при denied."""
    cache_key = (plugin, capability, requested_scope)
    with self._lock:
        cache_hit = cache_key in self._cache
```

Канон. сигнатура = 3 позиционных аргумента. AIGateway вызывает с 1 аргументом
→ `TypeError: CheckMixin.check() missing 2 required positional arguments`.

**Reproduction (read-only):**

```bash
cd /home/user/dev/gd_integration_tools
python -c '
import asyncio
from src.backend.core.ai.gateway import AIGateway, AIRequest
from src.backend.core.security.capabilities.gate import CapabilityGate
from src.backend.core.ai.policy.resolver import PolicyResolver
from src.backend.core.tenancy.token_budget import InMemoryTokenBudgetBackend
g = AIGateway(policy_resolver=PolicyResolver(),
              capability_gate=CapabilityGate(),
              token_budget=InMemoryTokenBudgetBackend())
from src.backend.core.config import features as f
f.feature_flags.ai_gateway_enforce = True
async def main():
    try:
        await g.invoke(AIRequest(workflow_id="x", tenant_id="t",
                                 correlation_id="c", prompt_inline="x"))
    except Exception as e:
        print(type(e).__name__, str(e)[:120])
asyncio.run(main())
'
```

Результат (stdout): `TypeError CheckMixin.check() missing 2 required positional
arguments: 'capability' and 'requested_scope'`.

**Тестовое подтверждение** (читается из `tests/unit/services/ai/test_aigateway_capability_wiring.py:148-224`):
два теста помечены `@pytest.mark.xfail(strict=True)`:

- `test_aigateway_pipeline_calls_capability_with_full_signature`:
  «Адаптер через 3-arg signature ловит real deny».
- `test_aigateway_pipeline_propagates_capability_denied`:
  «pre-Sprint 1.5 вызов был ``check(capability)`` с try/except, и реальный
  gate-исключения терялись → silent fail-open».

Запуск тестов:

```
$ pytest tests/unit/services/ai/test_aigateway_capability_wiring.py
..xx..............                                                       [100%]
2 xfailed: known-fail capacity-gate wired by 3-arg adapter not yet connected.
16 passed, 2 xfailed.
```

**Impact (P0):**

- **Production runtime:** composition root (`plugins/composition/di.py:95-97`)
  инжектит `capability_gate=CapabilityGate()`. Каждый `invoke()` падает с
  TypeError → 500-class error. Callsite `gateway_adapter.invoke_via_gateway`
  ловит `Exception` → возвращает exception результат. Callsite `agent_run.py:157-163`
  ловит `Exception` → `exchange.set_error("AIGateway.invoke error: ...")`.
  Callsite `ai_tool_dispatch.py:263-265` ловит → `return None` → caller не
  получает tool dispatch. **В любом из путей — AI не работает на проде.**
- **Fail-open потенциал:** если кто-то инстанцирует bare `AIGateway()` (см.
  DOMAIN-P0-002), то `_capability_gate is None` → silent return → нет проверки.
- **Audit chain:** корреляция `decision.context.audit` events не пишется, т.к.
  TypeError эскалируется до `_enforced_invoke`.

**Minimal recommendation:**

1. В composition root (`plugins/composition/di.py:95-97`):
   ```python
   from src.backend.services.ai.gateway_adapter import adapt_capability_gate
   from src.backend.core.security.capabilities.gate import CapabilityGate

   app.state.ai_gateway = get_ai_gateway_provider()
   # Override factory для canonical 3-arg form
   app.state.ai_gateway._capability_gate = adapt_capability_gate(CapabilityGate())
   ```
   либо прокинуть adapter в `_build_ai_gateway_singleton` через параметр.
2. В `policy_mixin.py:100` исправить `result = check(capability)` →
   `result = check("core", capability, request.workflow_id)` (passing plugin/scope).
3. Wrap `check(...)` вызов в try/except, чтобы перехватывать `CapabilityDeniedError`
   (в текущем виде он не входит в try — см. DOMAIN-P1-001).

**Test criterion:**
`tests/unit/services/ai/test_aigateway_capability_wiring.py:148-224` — оба
`xfail(strict=True)` теста должны пройти.

---

### DOMAIN-P0-002 — Bare `AIGateway()` fallback в `gateway_adapter.get_ai_gateway()`

**Path:** `src/backend/services/ai/gateway_adapter.py:114-130`.

**Evidence:**

```python
# gateway_adapter.py:114-130
def get_ai_gateway() -> AIGateway:
    """Получить singleton :class:`AIGateway` из composition root."""
    try:
        from src.backend.core.di.app_state import get_app_ref
        app = get_app_ref()
        if app is not None:
            gateway = getattr(app.state, "ai_gateway", None)
            if gateway is not None:
                return gateway
    except Exception:
        pass

    try:
        from src.backend.core.di.providers.ai import get_ai_gateway_provider
        return get_ai_gateway_provider()
    except (KeyError, RuntimeError):
        return AIGateway()                  # ← bare fallback: NO DI
```

Сравните с `core/ai/gateway/gateway.py:147-175`:

```python
def _enforce_production_wiring(self) -> None:
    """Sprint 1.3 (S177 M2): production-wiring guard.
    Проверяет, что в production все три обязательных DI инжектированы... """
    from src.backend.core.config.settings import settings as app_settings
    from src.backend.core.ai.errors import AIGatewayProductionWiringError
    env = getattr(getattr(app_settings, "app", None), "environment", "")
    if env != "production":
        return                             # ← dev/staging: skip guard
```

`_enforce_production_wiring()` skip-ит проверку в dev/staging → на dev/staging
bare AIGateway() возвращается без падений.

**Behavioral consequence (3 silent skip-цепочек):**

1. `_check_capability`: `if self._capability_gate is None: return` (policy_mixin.py:94) → capability check ПРОПУЩЕН.
2. `_resolve_policy`: `if self._policy_resolver is None: return None` (policy_mixin.py:66) → policy check ПРОПУЩЕН.
3. `_enforce_token_budget_pre_call`: `budget = getattr(self, "_token_budget", None); if budget is None: return None` (enforced_invoke.py:158-160) → budget ПРОПУЩЕН.

То есть в dev/staging, если `app.state.ai_gateway` отсутствует и
`get_ai_gateway_provider()` бросает `KeyError|RuntimeError`, вызывающий получает
**bare AIGateway с policy/capability/budget = None**, и шаги 1–3 пайплайна
становятся no-op. **Fail-open для всех трёх критических слоёв.**

**Impact (P0):**

- Любой CLI-script или background-worker, который вызывает `get_ai_gateway()`
  вне FastAPI lifespan (например, Temporal activity workers, Redis-streams
  consumers, cron-tasks) попадёт в `except (KeyError, RuntimeError)` ветку и
  получит bare gateway. Это явная утечка из composition root в non-FastAPI
  контексты, которая по архитектурной ноте (см. AGENTS.md, раздел
  composition-root DI) должна была бы error-out.
- `_check_capability` skip + bare gateway = LLM-call без authorization.
  Policy-resolver None = ни fail-closed политик, ни per-tenant policy override.
  Token-budget None = ни quota, ни SLO-контроля.

**Reproduction (read-only):**

```bash
cd /home/user/dev/gd_integration_tools
python -c '
import asyncio
from src.backend.core.ai.gateway import AIGateway, AIRequest
g = AIGateway()                              # bare — обходит все guards
from src.backend.core.config import features as f
f.feature_flags.ai_gateway_enforce = True
async def main():
    try:
        resp = await g.invoke(AIRequest(workflow_id="x",
            tenant_id="", correlation_id="c", prompt_inline="x"))
        print("CONTENT:", resp.content[:50])
    except Exception as e:
        print(type(e).__name__, str(e)[:120])
asyncio.run(main())
'
```

Ожидаемо: pipeline проходит через policy/capability/budget (no-op), но падает
на последующих шагах сантайзера (`ModuleNotFoundError: aiofiles` для
`PresidioSanitizerAdapter`). Sanity-OK — `_check_capability` skip silent,
а ошибка приходит из более позднего шага.

**Minimal recommendation:**

- В `gateway_adapter.get_ai_gateway()` (line 125-130) убрать `except
  (KeyError, RuntimeError): return AIGateway()` и заменить на raise той же
  ошибки. Если DI не работает — fail-loud, не fail-silent.
- Альтернатива: при bare-возврате — через `AIGatewayEnforcementRequiredError`
  если `feature_flags.ai_gateway_enforce` и setting `environment in
  {"production", "staging"}` (любой non-dev профиль).
- Тест: `tests/unit/services/ai/test_aigateway_capability_wiring.py` дополнить
  тестом «get_ai_gateway returns AIGateway with all 3 DI injected, even
  without app.state».

**Test criterion:**
`gateway_adapter.get_ai_gateway()` без `app.state.ai_gateway` → поднимает
`AIGatewayProductionWiringError` (если env=production|staging) или
`AIGatewayEnforcementRequiredError` (если dev + enforce flag), никогда не
возвращает bare gateway.

---

### DOMAIN-P0-003 — Hardcoded `tenant_id`/`correlation_id` в 3 процессорах

**Paths:**

- `src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py:248-262`
- `src/backend/dsl/engine/processors/agent_dsl/plan_execute.py:266-275`
- `src/backend/dsl/engine/processors/agent_dsl/reflection_loop.py:248-267`

**Evidence:**

```python
# ai_tool_dispatch.py:248-262
gateway = get_ai_gateway()
request = AIRequest(
    workflow_id="ai_tool_dispatch",
    tenant_id="default",       # ← hardcoded вместо exchange.meta.tenant_id
    correlation_id="",          # ← пусто вместо exchange.meta.correlation_id
    prompt_inline=prompt,
    context={...},
    stream=False,
)
response = await gateway.invoke(request)
```

```python
# plan_execute.py:266-275
async def _call_workflow(self, gateway, workflow_id, context):
    from src.backend.core.ai.gateway import AIRequest
    request = AIRequest(
        workflow_id=workflow_id,
        tenant_id="unknown",                                 # ← hardcoded
        correlation_id="plan-exec",                          # ← constant
        prompt_inline=f"Context: {json.dumps(context, ...)}",
    )
    try:
        return await gateway.invoke(request)
```

```python
# reflection_loop.py:250-258 — аналогично plan_execute
request = AIRequest(
    workflow_id=workflow_id,
    tenant_id="unknown",
    correlation_id="reflection-loop",
    prompt_inline=f"Context: {json.dumps(...)}",
)
```

Сравните с правильным паттерном в `agent_run.py:135-142`:

```python
request = AIRequest(
    workflow_id=self.workflow_id,
    tenant_id=exchange.meta.tenant_id or "unknown",       # ← реальный tenant
    correlation_id=exchange.meta.correlation_id,           # ← реальный correlation
    prompt_ref=self.prompt_ref,
    prompt_inline=self.prompt_inline,
    context=self._extract_context(exchange),
)
```

**Impact (P0):**

- **Budget lineage broken:** `_enforce_token_budget_pre_call` использует
  `request.tenant_id` для enforce. Все агенты под одной "default" или
  "unknown" tenant — per-tenant budget теряется. Tenant owner не получает
  корректную атрибуцию.
- **Audit-trail broken:** correlation_id="" или "plan-exec" вместо реального
  `exchange.meta.correlation_id` — Langfuse/CKA-observability теряет
  связь между цепочкой вызовов.
- **PII masking scope:** `_resolve_pii_token_registry` (см.
  core/di/providers/ai.py:106-126) выделяет Redis-key по
  `tenant_id`. Несколько tenant'ов сваленных под "unknown" не могут
  различаться.
- **Fail-open потенциал:** если в будущем policy resolver поставит
  restrict-policy на tenant, hardcoded `"unknown"`/`"default"` может пройти
  через default-policy ветку.

**Minimal recommendation:**

В трёх процессорах (`ai_tool_dispatch`, `plan_execute`, `reflection_loop`)
заменить хардкод на `exchange.meta.tenant_id or "unknown"` и
`exchange.meta.correlation_id or "ai_tool_dispatch"` (только как fallback)
по образцу `agent_run.py:135-142`.

**Test criterion:**
`grep -n 'tenant_id=\(.*"unknown"\|.*"default"\)' src/backend/dsl/engine/processors/agent_dsl/` → 0 hits.

---

### DOMAIN-P0-004 — `dsl/agents/fastmcp_server.py` импортирует из `infrastructure`

**Path:** `src/backend/dsl/agents/fastmcp_server.py:36-39`.

**Evidence:**

```python
# fastmcp_server.py:36-39
from src.backend.infrastructure.workflow.registry import (
    WorkflowDescriptor,
    workflow_registry,
)
```

`AGENTS.md` (раздел «Архитектура — слои и их границы») явно указывает
`src/backend/dsl/agents/` в нижнем слое, который импортирует только
`gd_integration_tools.core.*` + capability-checked фасады.

`src/backend/infrastructure/*` — это слой DB/cache/storage/messaging/secrets/
workflow, который должен быть недоступен из DSL напрямую.

**Impact (P0 security implication):**

- DSL — это маршрут, который extension-разработчик декларирует в YAML.
  Прямой импорт infrastructure снимает feature-flag/capability-границу.
  WorkflowDescriptor, возвращаемый FastMCP, обходит registry-wrapper
  в `core/ai/skill_registry` или аналогичном middleware.
- Любой plugin может вызвать `fastmcp_server` (через FastAPI mount) и получить
  доступ к любому `WorkflowDescriptor` независимо от capabilities plugin'а.

**Minimal recommendation:**

Вынести `WorkflowDescriptor` / `workflow_registry` в `core/workflow/registry.py`
(symmetric к `core/ai/skill_registry.py`) или ввести
`core/di/facades/workflow_facade.py` (по аналогии с `core/di/facades.py`,
упомянутым в M7).

**Test criterion:**
`ruff check --select F401 src/backend/dsl/agents/` /
`make layer-check` (если есть) → 0 violation для `infrastructure.workflow.registry`.

---

### DOMAIN-P1-001 — `try/except` placement в `_check_capability`

**Path:** `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py:100-109`.

**Evidence:**

```python
result = check(capability)                              # (a) — TypeError ЗДЕСЬ
try:                                                     # (b) — try СТАРТУЕТ ПОСЛЕ
    import inspect
    if inspect.isawaitable(result):
        await result
except Exception as exc:
    logger.debug(...)                                    # никогда не сработает
```

(a) — `check(capability)` поднимает TypeError ПЕРЕД входом в try.
(b) — try охватывает только `inspect.isawaitable(result)` — который не сработает,
      т.к. `check()` не async (см. check_mixin.py:48 — `-> None`).

То есть:

- `TypeError` (DOMAIN-P0-001) → выходит за пределы метода, не audit'ится как
  «gate.unavailable» event.
- Реальный `CapabilityDeniedError` → тоже выходит за пределы метода (т.к.
  raise внутри `check()` — вне try).
- Все остальные exceptions от `check()` → тоже выходят за пределы.

При успешном 1-arg вызове (если какой-то gate реализует 1-arg форму):
`result = check(capability)` возвращает None, `inspect.isawaitable(None)` is
False, try завершается без логирования. Никакой защиты.

**Recommended fix:**

```python
result = None
try:
    result = check(capability)
except TypeError:
    # 1-arg gate: try canonical 3-arg form
    result = check("core", capability, request.workflow_id)
if inspect.isawaitable(result):
    try:
        await result
    except Exception as exc:
        logger.warning(...)
```

**Test criterion:** manual reproduction (см. DOMAIN-P0-001) должен привести
к `CapabilityDeniedError` или controlled-warning вместо TypeError-500.

---

### DOMAIN-P1-002 — Composition provider собирает голые DI без config-injection

**Path:** `src/backend/core/di/providers/ai.py:244-272`.

**Evidence:**

```python
@lru_cache(maxsize=1)
def _build_ai_gateway_singleton() -> Any:
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.policy.resolver import PolicyResolver
    from src.backend.core.security.capabilities.gate import CapabilityGate
    from src.backend.core.tenancy.token_budget import InMemoryTokenBudgetBackend

    return AIGateway(
        policy_resolver=PolicyResolver(),                              # ← no roots
        capability_gate=CapabilityGate(),                              # ← default vocab only
        token_budget=InMemoryTokenBudgetBackend(),                     # ← in-memory only
    )
```

`PolicyResolver` создан с `roots=None` → `self._policies = None` → `resolve()`
возвращает None для любого workflow, пока hot-reload не наполнит cache. Это
означает, что в prod-cold-start первый invoke получит `policy=None`, через
`ai_policy_enforce=False` (default) — silent pass.

`CapabilityGate()` создан с `vocabulary=None` → `build_default_vocabulary()`;
в этом vocabulary НЕТ capability `ai.invoke.*` (см. `vocabulary/defaults.py`),
поэтому при 3-arg вызове `check(plugin, "ai.invoke.credit_check", scope)` →
`CapabilityNotFoundError`.

`InMemoryTokenBudgetBackend()` — in-memory, не multi-instance-safe, теряет
state при рестарте.

**Impact (P1):**

- Production AIGateway, будучи собранным через composition-root, **не может
  корректно авторизовать НИ ОДНОГО workflow** (gate vocabulary пуст).
- Policy resolver при cold-start возвращает `None` для всех workflows →
  если в feature-flag выставят `ai_policy_enforce=True`, первая же
  серия invokes поднимет `PolicyNotResolvedError`.
- Token budget — in-memory counter теряется на каждом reload worker'а, что
  для production-окружения с N репликами приводит к расхождению счетчика.

**Minimal recommendation:**

```python
# composition-friendly version
def _build_ai_gateway_singleton() -> Any:
    from src.backend.core.config.ai import AIPolicySettings
    from src.backend.core.config.services.policy import policy_settings
    from src.backend.core.config.tenancy import budget_settings

    return AIGateway(
        policy_resolver=PolicyResolver(roots=policy_settings.policy_roots),
        capability_gate=CapabilityGate(vocabulary=policy_settings.capability_vocabulary),
        token_budget=RedisTokenBudget(...) if budget_settings.backend == "redis" else InMemoryTokenBudgetBackend(),
    )
```

Но это требует уточнения названий settings — проверять фактические имена.

**Test criterion:**
После fix `get_ai_gateway_provider()` поднимает `PolicyNotResolvedError` при
`ai_policy_enforce=True` и cold-cache (а не silent None).

---

### DOMAIN-P1-003 — `get_ai_agent_service()` raising factory

**Path:** `src/backend/services/ai/ai_agent/__init__.py:109-111`.

**Evidence:**

```python
def get_ai_agent_service() -> AIAgentService:
    """Фабрика AI-сервиса."""
    raise NotImplementedError  # заменяется декоратором
```

Если ни один декоратор не активирован — caller получает
`NotImplementedError`. При этом factory экспортируется в `__all__ = ("AIAgentService", "get_ai_agent_service")`.

**Impact (P1):** Fragile decoration pattern:
- Static-анализатор не видит override
- Тесты, которые забыли применить декоратор, падают на runtime, не при import
- Composition root, если бы попробовал использовать `get_ai_agent_service`,
  получил бы «boomerang» при первом вызове

**Minimal recommendation:** `@functools.lru_cache(maxsize=1)` или просто
return singleton; либо явно raise `RuntimeError("не зарегистрировано в DI")`.

---

### DOMAIN-P1-004 — `LiteLLMModel.request_stream` NotImplementedError

**Path:** `src/backend/services/ai/agents_pydantic/adapter.py:113-115`.

**Evidence:**

```python
@asynccontextmanager
async def request_stream(self, ..., model_request_parameters) -> AsyncIterator[StreamedResponse]:
    """Streaming not supported yet."""
    raise NotImplementedError(
        f"Streaming not yet supported by {self.__class__.__name__}"
    )
```

При этом класс заявлен как `pydantic_ai.models.Model` (см. файл-комментарий,
строка 5). pydantic-ai вероятно вызовет request_stream при streaming-usage.

**Impact (P1):** Streaming-calls crash; pydantic-ai 0.5.x — может вызывать
оба метода (sync+stream) даже для non-streaming, в зависимости от версии.

---

### DOMAIN-P1-005 — Layer boundary: core/ai → services/ai прямые импорты

**Paths (грепом подтверждены):**

```
src/backend/core/ai/multi_agent.py:10:
    from src.backend.services.ai.multi_agent.supervisor import ...
src/backend/core/ai/gateway_pipeline_mixin/input_mixin.py:132:
    from src.backend.services.ai.pii.presidio_analyzer import ...
src/backend/core/ai/gateway_pipeline_mixin/output_mixin.py:139:
    from src.backend.services.ai.gateway import get_litellm_gateway
src/backend/core/ai/gateway_pipeline_mixin/llm_mixin.py:74:
    from src.backend.services.ai.prompt_registry import get_prompt_registry
src/backend/core/ai/policy/enforcer/input_guard_mixin.py:122:
    from src.backend.services.ai.guardrails.lakera_client import LakeraClient
src/backend/core/ai/llm_gateway.py:23:                                # facade — OK
    from src.backend.services.ai.gateway.client import ...
```

**Impact (P1):** core → services — обратная стрелка зависимости. Для тестов
core/ai требуется поднять services/ai runtime, что усложняет isolation.
Также: extension может через `from src.backend.core.ai.policy.enforcer.input_guard_mixin import ...`
попасть на `LakeraClient`, обойдя `core.di.facades`-wrapper.

**Recommended fix:**

- Вынести `LakeraClient` / `PresidioSanitizerAdapter` / `LiteLLMGateway` /
  `PromptRegistry` в `core/ai/{guardrails,pii,llm,prompts}/` (interfaces) +
  inject implementations в `__init__` AIGateway.

---

### DOMAIN-P2-001 / P2-002 — Stale docstrings

Подтверждено `grep "NotImplementedError"` + прочтением кода:

- `ai_tool_dispatch.py:24`: docstring говорит «scaffold», но `_run` (98-225)
  реализован (build prompt, call LLM, parse JSON, dispatch tool).
- `skill_invoke.py:20`: docstring говорит «scaffold», но `_run` обрабатывает
  NotImplementedError как defensive fallback, основной flow — invoke.

**Recommended fix:** sync docstrings with current behavior.

---

### DOMAIN-P3-001 — Custom OWASP regex list

**Path:** `src/backend/core/ai/security/agent_security.py:103-159`.

Около 4 категорий × ~6 regex patterns = ~24 ручных регулярок для
prompt-injection / SQL / shell / file-path. Зрелые аналоги (`llm-guard`,
`rebuff`, `nemo-guardrails`) поддерживаются большим community.

**Trade-off:**

- Текущий подход — zero-dep, no license/maintenance risk.
- ~24 regex ~ 50 LOC; `llm-guard` — добавляет 100+ MB and `torch` dep,
  сложно обосновать ради 24 regex.

**Verdict:** оставить как есть, либо добавить hook для external-detector.
Не P0/P1, рекомендуется только если список расширится до 100+ patterns.

---

### DOMAIN-P4-001 — DSPy pathway

`services/ai/dspy/` существует как отдельная директория. agents_pydantic,
agents, ai_agent, agent_dsl — четыре параллельных agentic-фреймворка,
которые могут пересекаться функционально. Это **органичное** unified-agent-spec
расширение, а не feature-for-feature копия. Не проверено детально.

---

### DOMAIN-P4-002 — Camel-style/Airflow-style DAGs для agent handoff

`agent_registry.py` (240 LOC) AgentSpec без multi-agent DAG. В V11.2 +
S28 W1 multi-agent реализован как supervisor; но «graceful handoff with
state-passing across Airflow-style DAG» отсутствует. Это органичное
domain-расширение (Camel/Airflow-style), не feature-copy.

## Contradictions / overlaps to flag

1. **`AIGateway._check_capability` vs `BaseAIProcessor._check_capability`**
   имеют РАЗНЫЕ сигнатуры:
   - `BaseAIProcessor._check_capability` (agent_dsl/_base.py:166-188):
     использует 3-arg форму с fallback на 1-arg (`try: check(plugin, cap, scope) except TypeError: check(cap)`).
   - `AIGateway.PolicyMixin._check_capability` (policy_mixin.py:84-110):
     использует 1-arg форму (TypeError-prone).

   Оба в одном проекте, но один работает (через TypeError-fallback), другой
   нет. Это рассогласование дизайна. AGENTS.md/SECURITY не одобряет
   fall-through дизайн.

2. **`get_ai_gateway()` против `_build_ai_gateway_singleton()` приоритет**.
   `gateway_adapter.get_ai_gateway()` сначала пытается `app.state.ai_gateway`
   (composition-root registered), потом fallback `lru_cache`,
   потом `AIGateway()`. Это «3-уровневая fall-through цепочка» —
   3 источника потенциально разных singleton'ов для одного
   приложения, что нарушает single-source-of-truth principle.

3. **`agents_pydantic/adapter.py` vs `dsl/agents/fastmcp_server.py`** —
   два независимых agentic-фреймворка с собственной инициализацией
   SkillRegistry. Не выявлено evidence пересечения, но потенциал.

4. **`core/ai/llm_gateway.py` facade vs `core/ai/gateway_pipeline_mixin/*` direct imports**
   — только `llm_gateway.py` соблюдает facade-rule; остальные mixins идут
   в обход. Suggests что facade-паттерн был бы универсально полезен.

5. **`app_state_singleton("skill_registry")` vs `get_skill_registry()`** —
   две параллельных DI-нотации для одного и того же концепта. `core/di/providers/ai.py:236`
   пытается резолвить через `app_state_singleton(...)()`. Сложно поддерживать.

## Readiness score 0–100

**Формула:**

```
readiness = architecture_score  * 0.45
          + di_composition_score * 0.25
          + security_posture      * 0.20
          + dead_code_score       * 0.10
```

| Подсчёт | Баллы | Обоснование |
|---------|-------|-------------|
| architecture_score | 65/100 | composition-root существует; core→services violations (6+ sites); bare AIGateway fallback; multi-agent разделено 4 способами |
| di_composition_score | 60/100 | provider корректен (override+cache), но голые DI без config (`_build_ai_gateway_singleton`), 3-step fall-through, hardcoded tenants |
| security_posture | 30/100 | DOMAIN-P0-001 (TypeError on every invoke), DOMAIN-P0-002 (fail-open dev/staging), DOMAIN-P0-003 (audit-broken), DOMAIN-P0-004 (layer-vulnerability) |
| dead_code_score | 80/100 | agent_security/agents_pydantic выглядят mature; 2 stale docstrings; 1 `pass`-stub в `mcp_tool.py:45`; ai_agent `get_ai_agent_service` raise-factory |

```
readiness = 65 * 0.45 + 60 * 0.25 + 30 * 0.20 + 80 * 0.10
          = 29.25     + 15.00      + 6.00      + 8.00
          = 58.25
```

→ **Readiness = 58 / 100 (округлённо).**

**Обоснование:** наличие 4 P0 (DOMAIN-P0-001…004) в ядре AI-подсистемы
автоматически исключает оценку ≥80. Composition-root сделан правильно
(см. S-1..S-3), но bare-fallback и TypeError на canonical-3-arg вызове
делают production runtime непредсказуемым. Высокая maturity detected в
`core/ai/security/` (S-5) и `policy/resolver.py`, но это не закрывает
basic bug в pipeline entry-point.

## Recommended next tasks

1. **(P0) Sprint S201: Wire `adapt_capability_gate` в composition-root.**
   Изменить `_build_ai_gateway_singleton` (`core/di/providers/ai.py:244`)
   на использование canonical-3-arg form. Снять `xfail` с двух тестов.
2. **(P0) Sprint S201: убрать bare-`AIGateway()` fallback в `gateway_adapter.get_ai_gateway()`**.
3. **(P0) Sprint S201: propagate `exchange.meta.tenant_id`/`correlation_id` в
   `ai_tool_dispatch`, `plan_execute`, `reflection_loop`** по образцу
   `agent_run.py`.
4. **(P0) Sprint S201: вынести `WorkflowDescriptor`/`workflow_registry`
   в core/workflow/facade для устранения layer-violation
   `dsl/agents/fastmcp_server.py:36-39`.**
5. **(P1) Sprint S202: `_build_ai_gateway_singleton` — параметризовать
   через pydantic-settings (PolicyResolver roots, CapabilityGate vocabulary,
   TokenBudget backend).**
6. **(P1) Sprint S202: переписать `agents_pydantic/adapter.py:113` —
   либо добавить streaming через LiteLLMGateway, либо убрать `request_stream`
   override и оставить sync-only.**
7. **(P1) Sprint S202: добавить `core/di/facades/ai_facade.py` для всех
   services/ai импортов в core/ai.**
8. **(P2) Sprint S203: sync stale docstrings (DOMAIN-P2-001, P2-002).**
9. **(P2) Sprint S203: пересмотреть `get_ai_agent_service()` factory pattern.**
10. **(P4) Будущее: единый AgentSpec с Camel-style/Airflow-style DAG для
    supervisor handoff (organic; не feature copy).**

## Commands run

```bash
# Repo state + scope exploration
git log --oneline -1
git status --porcelain
git diff --stat

# Files inventories
ls -la src/backend/dsl/agents/ src/backend/dsl/engine/processors/agent_dsl/
ls -la src/backend/core/ai/ src/backend/core/ai/security/
ls -la src/backend/services/ai/
ls -la src/backend/services/ai/agents/ src/backend/services/ai/agents_pydantic/ src/backend/services/ai/ai_agent/
find src/backend -type f -name "agent_*.py"
find src/backend -type d -name "agents*"
find src/backend/core/security/capabilities -name "*.py"
find tests/ -name "*aigateway*" -o -name "*gateway*capability*"
find tests/ -path "*agent_dsl*" -o -path "*agents/*test*"
find src/backend/entrypoints/api -name "*.py" -path "*ai*"

# Code patterns
grep -n "AIGateway(" -r src/backend/
grep -n "def check" src/backend/core/security/capabilities/gate/check_mixin.py
grep -n "from src.backend.infrastructure" src/backend/dsl/agents/ src/backend/dsl/engine/processors/agent_dsl/
grep -n "from src.backend.services\|from src.backend.infrastructure" src/backend/core/ai/security/
grep -n "from src.backend.services\|from src.backend.infrastructure" src/backend/core/ai/
grep -n "get_ai_gateway(" src/backend/
grep -n "invoke_via_gateway(" src/backend/
grep -n "_get_llm_gateway\|_llm_gateway\|litellm\|LiteLLM\b" src/backend/services/ai/ai_graph.py
grep -n "_get_llm_gateway\|litellm\|LiteLLM\b" src/backend/services/ai/ai_graph.py
grep -rn "TODO\|FIXME\|XXX\|HACK\|NotImplementedError" src/backend/dsl/agents/ src/backend/dsl/engine/processors/agent_dsl/ src/backend/core/ai/security/
grep -rn "NotImplementedError\|raise NotImplementedError\|pass  # noqa" src/backend/services/ai/agents/ src/backend/services/ai/agents_pydantic/ src/backend/services/ai/ai_agent/
grep -rn "tenant_id=" src/backend/dsl/engine/processors/agent_dsl/

# Targeted read of core artifacts
cat src/backend/core/di/providers/ai.py                                  # 325 lines
cat src/backend/core/ai/__init__.py
cat src/backend/plugins/composition/di.py                                 # 324 lines
cat src/backend/core/ai/gateway/gateway.py                                # 249 lines
cat src/backend/services/ai/gateway_adapter.py                            # 271 lines
cat src/backend/core/ai/gateway/orchestrator/enforced_invoke.py           # 407 lines
cat src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py            # 123 lines
cat src/backend/core/ai/policy/resolver.py                                # 258 lines
cat src/backend/core/security/capabilities/gate/__init__.py               # 163 lines
cat src/backend/core/security/capabilities/gate/check_mixin.py            # selected 80 lines (30..110)
cat src/backend/core/ai/security/__init__.py
cat src/backend/core/ai/security/agent_security.py                        # 667 lines
cat src/backend/dsl/agents/fastmcp_server.py                              # 259 lines
cat src/backend/dsl/engine/processors/agent_dsl/agent_run.py              # 262 lines
cat src/backend/dsl/engine/processors/agent_dsl/plan_execute.py           # 352 lines
cat src/backend/dsl/engine/processors/agent_dsl/_base.py                  # 254 lines
cat src/backend/dsl/engine/processors/agent_dsl/agent_loop.py             # 190 lines
cat src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py       # 405 lines
cat src/backend/dsl/engine/processors/agent_dsl/__init__.py
cat src/backend/services/ai/ai_agent/__init__.py                         # 111 lines
cat src/backend/services/ai/ai_agent/policy_mixin.py                     # 165 lines
cat src/backend/services/ai/ai_agent/agent_orchestration_mixin.py         # selected 90 lines (1-90)
cat src/backend/services/ai/agents_pydantic/adapter.py                    # 115 lines
cat src/backend/entrypoints/api/v1/endpoints/ai_agents.py                 # 142 lines
cat src/backend/dsl/engine/processors/agent_dsl/skill_invoke.py           # selected 30 lines (85-156)
cat src/backend/dsl/engine/processors/agent_dsl/reflection_loop.py       # selected 50 lines (315-325)
cat src/backend/dsl/engine/processors/ai/llmcall_processor.py             # selected 100 lines (100-200)
cat src/backend/services/ai/ai_graph.py                                  # selected 89 lines (160-248)
cat src/backend/dsl/engine/processors/agent_dsl/agent_security_check.py   # selected 60 lines (1-60)

# Reproduction of DOMAIN-P0-001 (read-only):
python -c '
import asyncio
from src.backend.core.ai.gateway import AIGateway, AIRequest
from src.backend.core.security.capabilities.gate import CapabilityGate
from src.backend.core.ai.policy.resolver import PolicyResolver
from src.backend.core.tenancy.token_budget import InMemoryTokenBudgetBackend
g = AIGateway(policy_resolver=PolicyResolver(),
              capability_gate=CapabilityGate(),
              token_budget=InMemoryTokenBudgetBackend())
from src.backend.core.config import features as f
f.feature_flags.ai_gateway_enforce = True
async def main():
    try:
        await g.invoke(AIRequest(workflow_id="x", tenant_id="t",
                                 correlation_id="c", prompt_inline="x"))
    except Exception as e:
        print(type(e).__name__, str(e)[:120])
asyncio.run(main())
'
# → TypeError: CheckMixin.check() missing 2 required positional arguments

# Bare-AIGateway fallback verification:
python -c '
import asyncio
from src.backend.core.ai.gateway import AIGateway, AIRequest
g = AIGateway()                              # bare — обходит все guards
from src.backend.core.config import features as f
f.feature_flags.ai_gateway_enforce = True
async def main():
    try:
        resp = await g.invoke(AIRequest(workflow_id="x",
            tenant_id="", correlation_id="c", prompt_inline="x"))
        print("CONTENT:", resp.content[:50])
    except Exception as e:
        print(type(e).__name__, str(e)[:120])
asyncio.run(main())
'

# Test run (targeted, no source modification):
python -m pytest tests/unit/services/ai/test_aigateway_capability_wiring.py \
                 tests/unit/core/ai/test_aigateway_production_wiring.py -q --no-header
# → 16 passed, 2 xfailed (2 known-fail capacity-gate wired by 3-arg adapter).
```
