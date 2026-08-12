# 08 — Agents domain audit (cycle 2, phase 1)

- **Date:** 2026-08-06
- **HEAD:** `ca5bff93058f2580041a7339913b52943babb329` (cycle 2 baseline)
- **Scope (заявлено, сужено до реально прочитанного):**
  - `src/backend/dsl/agents/**` — `fastmcp_server.py` (259 LOC)
  - `src/backend/dsl/engine/processors/agent_dsl/**` — 19 файлов (`_base`, `_timeouts`,
    `agent_run`, `agent_loop`, `agent_branch`, `agent_parallel`, `agent_graph`,
    `ai_tool_dispatch`, `plan_execute`, `reflection_loop`, `skill_invoke`,
    `memory_recall`, `memory_store`, `pii_mask`, `pii_unmask`, `guardrails_apply`,
    `optimize_prompt`, `bind_skill`, `langgraph_agent`, `agent_security_check`,
    `mcp_tool`)
  - `src/backend/core/ai/**/*agent*.py` — `agent_registry.py`, `agent_sandbox_protocol.py`,
    `agent_spec.py`, `multi_agent.py`
  - `src/backend/core/ai/security/**` — `__init__.py`, `agent_security.py` (667 LOC),
    `workflow_hooks.py` (335 LOC)
  - `src/backend/services/ai/agents/**` — `__init__.py`, `search_agent.py` (107 LOC),
    `analytics_agent.py` (112 LOC), `checkpoint_inspector.py` (154 LOC),
    `langgraph_postgres_saver.py` (220 LOC)
  - `src/backend/services/ai/agents_pydantic/**` — `__init__.py`, `base.py` (336 LOC),
    `adapter.py` (115 LOC), `examples/echo.py`, `examples/rag_answering.py`
  - `src/backend/services/ai/ai_agent/**` — `__init__.py` (111 LOC), `policy_mixin.py`,
    `rag_mixin.py`, `web_methods_mixin.py`, `http_providers_mixin.py`,
    `agent_orchestration_mixin.py`
  - `src/backend/services/ai/agent_*.py` — `agent_memory.py` (280 LOC), `agent_sandbox.py`
  - agent-focused API endpoints/schemas/tests:
    `src/backend/entrypoints/api/v1/endpoints/ai_agents.py` (142 LOC),
    `tests/unit/services/ai/test_gateway_pipeline_mixin.py` (выборочно),
    `tests/unit/core/ai/test_gateway_pipeline_mixin.py` (полностью),
    `tests/unit/services/ai/agents_pydantic/test_litellm_adapter.py` (40 LOC),
    `tests/unit/dsl/engine/processors/test_agent_layer_wrappers.py` (118 LOC),
    `tests/unit/dsl/engine/processors/agent_dsl/{test_plan_execute,test_reflection_loop,
    test_ai_tool_dispatch}.py`
- **Out of scope (заявлено):** `cycle-1` отчёты, `BASELINE.md cycle-1`,
  `PHASE-2-SUMMARY.md cycle-1`, `PHASE-3-PLAN.md cycle-1`, `KNOWN_ISSUES.md`,
  `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md`.
  Чтение `cycle-2/BASELINE.md` для baseline-numbers разрешено.
- **Baseline (cycle 2):** commit `ca5bff93`; layer checker
  `python tools/check_layers.py --root src` → exit 0; **175 legacy / 0 new**
  (2273 files scanned). `wc -l tools/check_layers_allowlist.txt` → **180 строк**
  (175 валидных + 5 пустых/комментариев; см. раздел 12). `grep -cE "^CVE-|^GHSA-|^PYSEC-"
  .security/pip-audit-allowlist.txt` → **35 активных ID**. Pre-existing `M uv.lock`
  (-15 svcs), `M tools/blue_green.sh`, `M tests/unit/tools/test_blue_green_switch.py`,
  `?? pip-audit.json`, `?? .blue_green.state` и **5 uncommitted source правок cycle 1
  Phase 4 (T-1.4/T-1.5/T-3.1)** НЕ атрибутируются рою cycle 2.
- **Найдено:** 12 finding (4 P0, 4 P1, 2 P2, 1 P3, 1 P4). Все cycle-1 IDs,
  упомянутые в задании, перепроверены прямым чтением кода на `ca5bff93`.

---

## 1. Scope / что проверено / что не проверено

### 1.1 Проверено (по файлам)

| Файл / артефакт | Прочитано | Команды / прямые evidence |
|---|---|---|
| `src/backend/dsl/agents/fastmcp_server.py` | 259 LOC, целиком | grep+read; `from src.backend.infrastructure.workflow.registry` (line 36-39) |
| `src/backend/dsl/engine/processors/agent_dsl/_base.py` | 254 LOC, целиком | direct read |
| `src/backend/dsl/engine/processors/agent_dsl/agent_run.py` | 262 LOC, целиком | direct read; tenant propagation на line 137 |
| `src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py` | 405 LOC, целиком | direct read; hardcoded tenant_id на line 251 |
| `src/backend/dsl/engine/processors/agent_dsl/plan_execute.py` | 352 LOC, целиком | direct read; hardcoded tenant_id на line 270 |
| `src/backend/dsl/engine/processors/agent_dsl/reflection_loop.py` | 344 LOC, целиком | direct read; hardcoded tenant_id на line 254 |
| `src/backend/dsl/engine/processors/agent_dsl/skill_invoke.py` | 156 LOC, целиком | direct read |
| `src/backend/dsl/engine/processors/agent_dsl/langgraph_agent.py` | 80 LOC, целиком | direct read; **TypeError** в `process()` line 73-78 |
| `src/backend/dsl/engine/processors/agent_dsl/optimize_prompt.py` | 137 LOC, целиком | direct read; bare `except Exception: pass` line 70-71 |
| `src/backend/dsl/engine/processors/agent_dsl/bind_skill.py` | 149 LOC, целиком | direct read |
| `src/backend/dsl/engine/processors/agent_dsl/mcp_tool.py` | 191 LOC, целиком | direct read |
| `src/backend/dsl/engine/processors/agent_dsl/agent_security_check.py` | 195 LOC, head | direct read |
| `src/backend/services/ai/agents_pydantic/adapter.py` | 115 LOC, целиком | direct read; `request_stream` NotImplementedError line 113 |
| `src/backend/services/ai/agents_pydantic/base.py` | 336 LOC, целиком | direct read; enforcement gate (line 165-169) |
| `src/backend/services/ai/agents_pydantic/__init__.py` | целиком | direct read |
| `src/backend/services/ai/agents_pydantic/examples/{echo,rag_answering}.py` | целиком | direct read |
| `src/backend/services/ai/agents/search_agent.py` | 107 LOC, целиком | direct read; `@app_state_singleton` |
| `src/backend/services/ai/agents/analytics_agent.py` | 112 LOC, head | direct read; `@app_state_singleton` |
| `src/backend/services/ai/agents/checkpoint_inspector.py` | 154 LOC, целиком | direct read |
| `src/backend/services/ai/agents/langgraph_postgres_saver.py` | 220 LOC, head | direct read |
| `src/backend/services/ai/ai_agent/__init__.py` | 111 LOC, целиком | **CRITICAL** get_ai_agent_service NotImplementedError |
| `src/backend/services/ai/ai_agent/{policy,rag,web_methods,http_providers,agent_orchestration}_mixin.py` | head/tail | grep + spot read |
| `src/backend/services/ai/agent_memory.py` | 280 LOC, head + 277-280 | direct read; `@app_state_singleton` OK |
| `src/backend/services/ai/agent_sandbox.py` | grep only | grep imports |
| `src/backend/core/ai/security/__init__.py` | 64 LOC, целиком | direct read |
| `src/backend/core/ai/security/agent_security.py` | 50 LOC head + grep | direct read; PromptValidator alias (line 241) |
| `src/backend/core/ai/security/workflow_hooks.py` | 50 LOC head + grep | direct read |
| `src/backend/core/di/providers/ai.py` | lines 230-325 | `_build_ai_gateway_singleton` line 244-272 |
| `src/backend/core/di/app_state.py` | lines 143-187 | `app_state_singleton` decorator |
| `src/backend/core/svcs_registry.py` | 119 LOC, целиком | direct read |
| `src/backend/plugins/composition/di.py` | 324 LOC, целиком | direct read; **NO `app.state.ai_agent_service` registration** |
| `src/backend/plugins/composition/service_setup.py` | lines 180-244 | `register_factory("ai", get_ai_agent_service)` |
| `src/backend/dsl/commands/setup/registers_integrations.py` | 276 LOC, целиком | direct read; service_getter= get_ai_agent_service line 14-37 |
| `src/backend/services/ai/ai_graph.py` | lines 130-248 | `build_and_run_agent(prompt, tool_actions, ...)` |
| `src/backend/services/ai/gateway_adapter.py` | 283 LOC, целиком | direct read; T-1.5 fix verified |
| `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py` | 171 LOC, целиком | direct read; T-1.5 fix verified |
| `src/backend/entrypoints/api/v1/endpoints/ai_agents.py` | 142 LOC, целиком | direct read |
| `tests/unit/core/ai/test_gateway_pipeline_mixin.py` | 1106 LOC, lines 1-110 | grep + read; 4 capability tests |
| `tests/unit/services/ai/agents_pydantic/test_litellm_adapter.py` | 40 LOC, целиком | direct read |
| `tests/unit/dsl/engine/processors/test_agent_layer_wrappers.py` | 118 LOC, целиком | direct read |
| `tests/unit/dsl/engine/processors/agent_dsl/test_{plan_execute,reflection_loop,ai_tool_dispatch}.py` | head/tail | grep tests for `tenant_id` (отсутствуют) |
| `tools/check_layers.py` + `tools/check_layers_allowlist.txt` | first 100 lines | direct read |

### 1.2 Не проверено

- Полный `src/backend/core/ai/pydantic_ai_client.py` (644 LOC) — упомянут в DOMAIN-P1-004
  контрасте (есть второй `LiteLLMModelAdapter` с реализованным `request_stream`), но
  прямое чтение ограничено head/tail. Глубокий audit — за рамками phase-1.
- Полный `src/backend/core/ai/gateway/gateway.py`, `gateway/orchestrator/*`,
  `gateway_audit_mixin.py`, `gateway_models.py`, `gateway_orchestrator_mixin.py` —
  цикл-1 уже покрыл; cycle-2 ограничился cross-check сигнатур.
- `src/backend/core/ai/llm_gateway.py` — только grep imports.
- `src/backend/services/ai/agents/{search_agent,analytics_agent}.py` целиком — head прочитан,
  полный код body не верифицирован.
- `src/backend/services/ai/multi_agent/`, `src/backend/services/ai/memory/` —
  за пределами явного scope (`agents/**`, `agents_pydantic/**`, `ai_agent/**`,
  `agent_*.py`).
- Расширения `extensions/{credit_pipeline,osint_agent,dadata,skb,example_plugin,
  test_plug,core_entities,core_admin}` — бизнес-логика, явно вне scope (см. AGENTS.md).
- `tests/unit/services/ai/test_aigateway_capability_wiring.py`, `test_aigateway_production_wiring.py`
  упомянуты в задании, но прямо не запускались (env-зависимости: prometheus_client).
- Vendor/3rd-party libs (`pydantic_ai`, `langgraph`, `mcp.server.fastmcp`, `langfuse`,
  `litellm`) — только проверка факта импорта.
- `tools/checks/check_ai_gateway_coverage.py` AST-checker — не запускался.
- Migrations, deployment helm-chart — вне scope.

---

## 2. Verified strengths (cycle-2 подтверждено)

| ID | Аспект | Доказательство | Где проверено |
|---|---|---|---|
| S-1 | **T-1.5 fix реализован**: dual-signature `_check_capability` (3-arg canonical, 1-arg legacy fallback). | `policy_mixin.py:108-150`: `inspect.signature` → `len(positional) >= 3` → `check(plugin, capability, scope)`; `try/except TypeError` → fallback на `check(capability)`. | `core/ai/gateway_pipeline_mixin/policy_mixin.py:84-157` |
| S-2 | **T-1.5 fix реализован (gateway_adapter)**: composition-root DI only, bare `AIGateway()` запрещён. | `gateway_adapter.py:100-142` `get_ai_gateway()` теперь бросает `AIGatewayProductionWiringError(missing=("ai_gateway",))` если lookup падает. Pre-existing fix в working tree. | `services/ai/gateway_adapter.py:100-142` |
| S-3 | **Composition-root регистрация выполнена корректно**. | `plugins/composition/di.py:94-97` явно регистрирует `app.state.ai_gateway = get_ai_gateway_provider()` со всеми обязательными DI (`policy_resolver`, `capability_gate`, `token_budget`). | `plugins/composition/di.py:94-97` |
| S-4 | **`@app_state_singleton` decorator pattern работает** для сервисов, которые его используют. | `agents/search_agent.py:105-106`, `agents/analytics_agent.py:108`, `agent_memory.py:277-280`, `services/ai/rag_service/__init__.py:60`, `services/ai/memory_gateway.py:296` и т.д. — все используют `@app_state_singleton(...)` decorator → тело функции `raise NotImplementedError` заменяется wrapper'ом. `core/di/app_state.py:143-187` подтверждает. | множественные файлы + `core/di/app_state.py` |
| S-5 | **`AgentSecurityFramework` имеет strict_mode=True по умолчанию** + OWASP LLM Top 10 hooks + dangerous-command detection. | `core/ai/security/agent_security.py:1-33` (module docstring со ссылками на OWASP/NIST). | `core/ai/security/agent_security.py` head |
| S-6 | **`_policy_gate` fail-closed** (services/ai/ai_agent/policy_mixin.py:36-135): любое исключение → deny-envelope + audit-event. | `ai_agent/policy_mixin.py:36-68` явно говорит: «раньше здесь возвращался None (= allow) при ImportError модуля настроек. Возвращаем deny-envelope». | `services/ai/ai_agent/policy_mixin.py:36-68` |
| S-7 | **`CapabilityFacade.check` thread-safe cache lock** (D-AUDIT-98 fix). | `_check_capability` использует `with self._lock: cache_hit = cache_key in self._cache`. | `core/ai/gateway_pipeline_mixin/policy_mixin.py:151-157` (см. S-1) |
| S-8 | **FastMCP-server обёрнут через capability-gate + tenant-allowlist**. | `dsl/agents/fastmcp_server.py:238-257`: `tool_callback` проверяет `skill.tenant_allowlist`, вызывает `registry.invoke`. Каталог tools/prompts read-only. | `dsl/agents/fastmcp_server.py:237-257` |
| S-9 | **`AgentRunProcessor` корректно пробрасывает tenant_id/correlation_id** через `exchange.meta.tenant_id`. | `agent_run.py:135-142`: `tenant_id=exchange.meta.tenant_id or "unknown"`, `correlation_id=exchange.meta.correlation_id`. Контраст с DOMAIN-P0-003. | `dsl/engine/processors/agent_dsl/agent_run.py:135-142` |
| S-10 | **`MCPToolProcessor` deny `file://` transport** (RCE surface, Cycle 20 P0-4). | `mcp_tool.py:83-90`: `if tool_uri.startswith("file:"): raise ValueError(...)`. | `dsl/engine/processors/agent_dsl/mcp_tool.py:83-90` |
| S-11 | **`_ask_llm_for_tool_selection` имеет query-length cap** (`_MAX_QUERY_LEN = 2000`). | `ai_tool_dispatch.py:326-351` truncate, log warning. | `dsl/engine/processors/agent_dsl/ai_tool_dispatch.py:326-351` |
| S-12 | **Registry-based DI через `register_factory("ai", ...)` корректно типизирован** через `Callable[[], Any]`. | `core/svcs_registry.py:55-68`: lazy singleton, thread-safe `_lock`, reset при override. | `core/svcs_registry.py:55-68` |

---

## 3. Findings table

| ID | Priority | Path:line | Краткое описание |
|----|----------|-----------|------------------|
| **DOMAIN-P0-005** | **P0** | `src/backend/dsl/engine/processors/agent_dsl/langgraph_agent.py:73-78` | `LangGraphAgentProcessor.process()` вызывает `build_and_run_agent(query=..., thread_id=..., max_iterations=...)` — НЕВАЛИДНАЯ сигнатура. `build_and_run_agent` ожидает positional `prompt: str, tool_actions: list[str]` + kwargs (`session_id`, `durable`, etc.). Тест mock'ит функцию → bug не виден. **Production TypeError.** |
| **DOMAIN-P0-006** | **P0** | `src/backend/services/ai/ai_agent/__init__.py:109-111` | `get_ai_agent_service()` НЕ decorated, **поднимает `NotImplementedError` при ЛЮБОМ вызове**. 7 production callsites: `dsl/engine/processors/{ai_banking/_base,ai/llmcall_processor,ai/llmfallback_processor,ml_inference}.py`, `services/ai/llm_judge.py:117`, `services/routes/route_authz.py:126`, `dsl/commands/setup/registers_integrations.py:14-37` (4 ActionHandlerSpec). **Production crash при любом LLM-action invoke.** |
| **DOMAIN-P0-003** | **P0** | `agent_dsl/ai_tool_dispatch.py:251` + `plan_execute.py:270` + `reflection_loop.py:254` | Hardcoded `tenant_id="default"\|"unknown"` и `correlation_id=""\|"plan-exec"\|"reflection-loop"` — ломает audit/per-tenant budget lineage. Контраст: `agent_run.py:137` корректно читает `exchange.meta.tenant_id`. (cycle-1 RESIDUAL — **не закрыт**). |
| **DOMAIN-P0-004** | **P0** | `src/backend/dsl/agents/fastmcp_server.py:36-39` | `dsl/agents/*` импортирует `src.backend.infrastructure.workflow.registry` напрямую. Хотя DSL — meta-layer и формально layer-checker пропускает (rule "dsl → infrastructure" разрешён), это создаёт **hard reverse-coupling**: DSL слой знает о workflow implementation details. (cycle-1 RESIDUAL — **не закрыт**). |
| DOMAIN-P1-001 | P1 | `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py:128-157` | После T-1.5 fix `try/except TypeError` вокруг `check()` call корректно разделён; но `try/except Exception` вокруг `if inspect.isawaitable(result): await result` (line 151-157) **swallow'ит ВСЕ исключения из gate-check включая `CapabilityDeniedError`** — должно быть `except (RuntimeError, AttributeError)` или propagate. |
| DOMAIN-P1-002 | P1 | `src/backend/core/di/providers/ai.py:244-272` | `_build_ai_gateway_singleton` собирает голые `PolicyResolver()`/`CapabilityGate()`/`InMemoryTokenBudgetBackend()` **без DI-конфигов** (vocabularies/policies/roots). composition-root result — независимый синглтон без plugin declarations; контраст с `_build_workspace_manager`/`_build_waf_policy_from_settings` (composition plugins читают settings). (cycle-1 RESIDUAL). |
| DOMAIN-P1-003 | P1 | `src/backend/services/ai/ai_agent/__init__.py:41, 109-111` | `get_ai_agent_service()` экспортируется в `__all__` как рабочая фабрика, но реально raise-фактори. (cycle-1 RESIDUAL — **не закрыт**; связан с DOMAIN-P0-006). |
| DOMAIN-P1-004 | P1 | `src/backend/services/ai/agents_pydantic/adapter.py:113` | `LiteLLMModel.request_stream` → `NotImplementedError`; класс экспортируется как `pydantic_ai.models.Model`. **Дубль** `LiteLLMModelAdapter` в `core/ai/pydantic_ai_client.py:422-621` уже реализует полный pydantic_ai Model Protocol (включая `request_stream` через `_SimpleStreamedResponse`). Никто из extensions не использует `BasePydanticAgent` (`grep -rn BasePydanticAgent extensions/` → 0 hits). (cycle-1 RESIDUAL). |
| DOMAIN-P2-002 | P2 | `src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py:22-25` | Stale docstring: «_run помечает exchange ошибкой `NotImplementedError` (scaffold)» — реализовано в коде (lines 98-225). (cycle-1 RESIDUAL). |
| DOMAIN-P2-003 | P2 | `src/backend/dsl/agents/fastmcp_server.py:135-147` | `start()` / `stop()` — no-ops, но называются «Lifecycle (managed by caller)». Поиск вызовов: `grep -rn "fastmcp_server.start\|fastmcp_server.stop" src/` → 0 hits (мёртвый интерфейс). (cycle-1 RESIDUAL). |
| DOMAIN-P3-001 | P3 | `src/backend/dsl/engine/processors/agent_dsl/optimize_prompt.py:74-79` | `get_service("dspy_feedback_trainer")` / `get_service("feedback_trainer")` — **НИ ОДИН не зарегистрирован** через `register_factory` в `plugins/composition/service_setup.py`. `get_service()` бросит `KeyError`, ловится в `except Exception` → return None → processor = noop. optimize_prompt = dead code path. |
| DOMAIN-P4-001 | P4 | `src/backend/core/ai/security/workflow_hooks.py:33-42` | Публичные `register_banking_transaction_hook`/`register_rpa_browser_hook`/`register_code_generation_hook`/`register_data_export_hook` определены, но `grep -rn "register_.*_hook" src/` → 0 production callers (только docstring usage example в этом же файле). Public API unused. Organic fix: либо удалить, либо добавить в `agents_pydantic/__init__.py` facade и зарегистрировать в `ai_safety_setup.py`. |

---

## 4. Detailed evidence

### DOMAIN-P0-005 — `LangGraphAgentProcessor` вызывает `build_and_run_agent` с неверной сигнатурой

**Path:** `src/backend/dsl/engine/processors/agent_dsl/langgraph_agent.py:73-78`.

**Evidence:**

```python
# langgraph_agent.py:73-78
from src.backend.services.ai.ai_graph import build_and_run_agent
result = await build_and_run_agent(
    query=self.query,                     # WRONG — параметр называется prompt
    thread_id=self.thread_id,             # WRONG — параметр называется session_id
    max_iterations=self.max_iterations,   # UNKNOWN — не в сигнатуре
)
```

Сигнатура `build_and_run_agent` (`src/backend/services/ai/ai_graph.py:140-149`):

```python
async def build_and_run_agent(
    prompt: str,                          # ← positional, required
    tool_actions: list[str],              # ← positional, required
    *,
    gateway: Any | None = None,
    model: str | None = None,
    temperature: float = 0.0,
    durable: bool = False,
    session_id: str | None = None,        # ← NOT thread_id
) -> dict[str, Any]:
```

Прямая верификация:

```bash
$ python -c "from src.backend.services.ai.ai_graph import build_and_run_agent; \
    import asyncio; \
    asyncio.run(build_and_run_agent(query='x', thread_id='t', max_iterations=10))"
TypeError: build_and_run_agent() got an unexpected keyword argument 'query'
```

**Test mocks** (`tests/unit/dsl/engine/processors/test_agent_layer_wrappers.py:48-52`) `patch("src.backend.services.ai.ai_graph.build_and_run_agent", new=AsyncMock(...))` — баг не виден.

**Impact (P0):**
- **Production crash**: `LangGraphAgentProcessor.process()` бросает TypeError на каждом invocation.
- **AgentSpec/Airflow-style handoff**: один из 3 процессоров `langgraph_*` в DSL — broken at runtime.
- Cycle-1 audit DOMAIN-P1-005 (multi_agent) не покрывал этот процессор.
- Cycle-1 audit DOMAIN-P4-002 (Agent TOML-регистр LangGraph subgraphs) — теоретический, текущий баг — concrete.

**Minimal recommendation:**
- Заменить `query=` → `prompt=`; `thread_id=` → `session_id=`; удалить `max_iterations=` (или передать через `model=`/`temperature=` если нужен лимит); добавить обязательный `tool_actions=[]` (или дефолтный whitelist).
- Ponytail-вариант: `tool_actions=self.tool_actions or ["chat"]` + `prompt=self.query`.
- Или вынести `build_and_run_agent(prompt, tool_actions, *, session_id, max_iterations)` через builder.

**Test-criterion:**
- `test_langgraph_agent_process_passes_correct_kwargs` — mock `build_and_run_agent` через `AsyncMock(side_effect=...)` и assert that call_args == `(prompt=<query>, tool_actions=<expected>, session_id=<thread_id>)`.
- `test_langgraph_agent_process_propagates_build_error` — mock raises → `set_error()`.

---

### DOMAIN-P0-006 — `get_ai_agent_service()` raise-фабрика = dead code, 7 production callsites

**Path:** `src/backend/services/ai/ai_agent/__init__.py:109-111`.

**Evidence:**

```python
# ai_agent/__init__.py:107-111
__all__ = ("AIAgentService", "get_ai_agent_service")


def get_ai_agent_service() -> AIAgentService:
    """Фабрика AI-сервиса."""
    raise NotImplementedError  # заменяется декоратором
```

Контраст с `agent_memory.py:277-280`, который правильно декорирован:

```python
# agent_memory.py:277-280
@app_state_singleton("agent_memory_service", factory=AgentMemoryService)
def get_agent_memory_service() -> AgentMemoryService:
    """Фабрика: singleton AgentMemoryService (MongoDB)."""
    raise NotImplementedError  # заменяется декоратором
```

Decorator `app_state_singleton` (`src/backend/core/di/app_state.py:143-187`) заменяет тело функции через `decorator(fn) → wrapper`, который ищет в `app.state.attr` или вызывает `factory()`. **`get_ai_agent_service` НЕ декорирован.**

Прямая верификация (временный мок `get_ai_sanitizer_provider` чтобы избежать chain ошибок):

```bash
$ python -c "
import unittest.mock as mock
with mock.patch('src.backend.core.di.providers.ai.get_ai_sanitizer_provider') as m:
    m.return_value = mock.MagicMock()
    from src.backend.services.ai.ai_agent import get_ai_agent_service
    get_ai_agent_service()
"
NotImplementedError
```

**7 production callsites (verified by `grep -rn get_ai_agent_service src/backend/`)**:

| Callsite | Path | Action |
|---|---|---|
| `ml_inference.py:162-164` | `dsl/engine/processors/ml_inference.py` | direct `agent = get_ai_agent_service()` → crash |
| `llmfallback_processor.py:46-48` | `dsl/engine/processors/ai/llmfallback_processor.py` | direct → crash |
| `llmcall_processor.py:214-219` | `dsl/engine/processors/ai/llmcall_processor.py` | direct → crash |
| `ai_banking/_base.py:96-100` | `dsl/engine/processors/ai_banking/_base.py` | direct → crash |
| `route_authz.py:124-126` | `services/routes/route_authz.py` | direct → crash |
| `llm_judge.py:115-117` | `services/ai/llm_judge.py` | direct → crash |
| `registers_integrations.py:14-37` | `dsl/commands/setup/registers_integrations.py` | `service_getter=get_ai_agent_service` для **4** ActionHandlerSpec (`ai.search_web`, `ai.parse_webpage`, `ai.chat`, `ai.run_agent`) → `action_handler_registry.dispatch()` (line 300 `service = spec.service_getter()`) → crash |

**Composition-root отсутствует**: `grep -rn "app.state.ai_agent" src/backend/` → **0 hits**. `register_factory("ai", get_ai_agent_service)` в `plugins/composition/service_setup.py:212` регистрирует фактори под именем "ai", но `get_service("ai")` (если вызвано) **тоже поднимет `NotImplementedError`** (нет override `set_ai_agent_service`, нет `app.state.ai_agent_service`).

**Тесты проходят только потому, что mock'ят функцию**: `grep -rn "get_ai_agent_service" tests/unit/dsl/engine/processors/test_llmfallback_processor.py tests/unit/dsl/engine/processors/test_llmcall_processor.py` — все используют `unittest.mock.patch("src.backend.services.ai.ai_agent.get_ai_agent_service", return_value=mock_agent)`.

**Impact (P0):**
- **Production-broken**: любой LLM-action (`ai.chat`, `ai.run_agent`, `ai.search_web`, `ai.parse_webpage`) или LLM-процессор (`llmcall`, `llmfallback`, `ml_inference`, `ai_banking_*`, `llm_judge`) → **TypeError/NotImplementedError**.
- Cycle-1 DOMAIN-P1-003 (отмечен как «fragile decorator pattern») подтверждён **активным P0**: реальные production callsites, не теоретический.
- Cycle-1 Phase 4 (T-1.4/T-1.5) **не закрыл** этот finding.

**Minimal recommendation:**

```python
# ai_agent/__init__.py — заменить:
@app_state_singleton("ai_agent_service", factory=AIAgentService)
def get_ai_agent_service() -> AIAgentService:
    """Фабрика AI-сервиса."""
    raise NotImplementedError  # заменяется декоратором
```

+ добавить `app.state.ai_agent_service = AIAgentService()` в `plugins/composition/di.py:register_app_state()` (после `app.state.ai_gateway = get_ai_gateway_provider()`).

**Test-criterion:**
- `test_get_ai_agent_service_returns_constructed_instance` — без mock'а, после `register_app_state()`.
- Integration test: `await llm_judge(query, response)` через `route_authz.py:_resolve_authz_gateway()` без mock'а.

---

### DOMAIN-P0-003 — 3 Agent DSL процессора hardcode `tenant_id` (RESIDUAL)

**Path:**
- `src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py:251`
- `src/backend/dsl/engine/processors/agent_dsl/plan_execute.py:270`
- `src/backend/dsl/engine/processors/agent_dsl/reflection_loop.py:254`

**Evidence:**

```python
# ai_tool_dispatch.py:248-261 (in _ask_llm_for_tool_selection)
gateway = get_ai_gateway()
request = AIRequest(
    workflow_id="ai_tool_dispatch",
    tenant_id="default",     # ← hardcoded, ignores exchange.meta.tenant_id
    correlation_id="",       # ← hardcoded empty string
    prompt_inline=prompt,
    context={...},
    stream=False,
)
```

```python
# plan_execute.py:268-273 (in _call_workflow)
request = AIRequest(
    workflow_id=workflow_id,
    tenant_id="unknown",     # ← hardcoded
    correlation_id="plan-exec",  # ← loses per-request correlation_id
    prompt_inline=f"Context: {json.dumps(context, ensure_ascii=False)}",
)
```

```python
# reflection_loop.py:252-257 (in _call_workflow)
request = AIRequest(
    workflow_id=workflow_id,
    tenant_id="unknown",     # ← hardcoded
    correlation_id="reflection-loop",  # ← loses per-request correlation_id
    prompt_inline=f"Context: {json.dumps(context, ensure_ascii=False)}",
)
```

Контраст — `agent_run.py:135-142` корректно:

```python
request = AIRequest(
    workflow_id=self.workflow_id,
    tenant_id=exchange.meta.tenant_id or "unknown",     # ← correct
    correlation_id=exchange.meta.correlation_id,         # ← correct
    prompt_ref=self.prompt_ref,
    prompt_inline=self.prompt_inline,
    context=self._extract_context(exchange),
)
```

**Дополнительная проблема для `ai_tool_dispatch.py`**: `_ask_llm_for_tool_selection(self, *, query, tools_desc)` (line 228-230) **не принимает exchange** — даже после fix нужно менять signature.

**Тесты не ловят**: `grep -n tenant_id tests/unit/dsl/engine/processors/agent_dsl/test_ai_tool_dispatch.py` → **0 hits**. Тесты mock'ают gateway (`AsyncMock()`), поэтому AIRequest.tenant_id не инспектируется.

**Impact (P0):**
- Audit lineage broken: все 3 процессора записывают `ai_tool_dispatch`/`ai.agent.plan_execute`/`ai.agent.reflection_loop` events с `tenant_id="default"|"unknown"` и `correlation_id=""`/`"plan-exec"`/`"reflection-loop"` → невозможно отследить per-tenant spend / per-request trace.
- Per-tenant token budget (`core/ai/gateway_pipeline_mixin`) учитывается под wrong tenant_id → tenant A может потратить budget tenant B (или vice versa).
- Data-protection compliance: при cross-tenant investigation — audit показывает ложный tenant.

**Minimal recommendation:**
- `ai_tool_dispatch.py:_ask_llm_for_tool_selection` — добавить параметр `tenant_id: str`, `correlation_id: str`; передавать `exchange.meta.tenant_id` и `exchange.meta.correlation_id` из `_run()`.
- `plan_execute.py:_call_workflow` / `reflection_loop.py:_call_workflow` — добавить `tenant_id`, `correlation_id` параметры; передавать из `_generate_plan`/`_execute_step`/`_verify_step` (уже принимают `exchange`).

**Test-criterion:**
- `test_ai_tool_dispatch_propagates_tenant_id_from_exchange` — assert `gateway.invoke.call_args[0][0].tenant_id == exchange.meta.tenant_id`.
- Аналогичные тесты для `plan_execute` и `reflection_loop`.

---

### DOMAIN-P0-004 — `fastmcp_server.py` direct `infrastructure.workflow.registry` import (RESIDUAL)

**Path:** `src/backend/dsl/agents/fastmcp_server.py:36-39`.

**Evidence:**

```python
# fastmcp_server.py:36-39
from src.backend.infrastructure.workflow.registry import (
    WorkflowDescriptor,
    workflow_registry,
)
```

**Layer-checker не считает это violation** (DSL — meta-layer, `ALLOWED["dsl"] = {"core", "infrastructure", "services", "entrypoints", "schemas"}`, line 68 `tools/check_layers.py`). Но cycle-1 finding (DOMAIN-P0-004) был о **architectural coupling**, не о layer-checker mechanics:

> "DSL layer hard reverse-coupling к workflow registry implementation" — DSL должен знать только контракты (Protocol/Interface) из core, не infrastructure.

Прямая проверка: `grep -n "workflow_registry\|WorkflowDescriptor" tools/check_layers_allowlist.txt` → **0 hits** в allowlist, потому что layer checker пропускает (DSL→infra разрешён по правилу).

`wc -l tools/check_layers_allowlist.txt` → **180 строк** (см. раздел 12).

**Impact (P0):**
- Reverse-coupling: при рефакторе `WorkflowDescriptor` (например, добавление required полей) — `fastmcp_server.py` ломается даже если DSL-слой не менялся.
- Cycle-1 не закрыл (RESIDUAL). Sprint 36 план не включает этот фикс.

**Minimal recommendation:**
- Создать `src/backend/core/ai/workflow_protocol.py` с Protocol `WorkflowCatalog` (метод `list_all() -> Iterable[WorkflowDescriptor]`).
- В `infrastructure/workflow/registry.py` — реализовать Protocol через `class WorkflowRegistryAdapter: ...` или просто satisfy Protocol.
- В `fastmcp_server.py` — импортировать Protocol из core.

**Test-criterion:**
- Unit-test `fastmcp_server.py` с mock'ом `WorkflowCatalog.list_all()` без зависимости от infrastructure.

---

### DOMAIN-P1-001 — `try/except Exception` swallow'ит `CapabilityDeniedError` в `inspect.isawaitable` блоке

**Path:** `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py:151-157`.

**Evidence:**

```python
# policy_mixin.py:128-157 (T-1.5 fix, current state)
try:
    if use_three_arg:
        result = check(plugin, capability, scope)
    else:
        result = check(capability)
except TypeError:
    # cycle-1/B-05: signature lied or C-extension rejects 3-arg;
    # fallback на legacy 1-arg form.
    logger.error(...)
    try:
        result = check(capability)
    except TypeError as exc:
        logger.error(...)
        return
try:
    if inspect.isawaitable(result):
        await result
except Exception as exc:        # ← bare-ish except
    logger.debug(
        "AIGateway: capability check for %s failed: %s", capability, exc
    )
```

**Проблема**: если `gate.check()` бросает `CapabilityDeniedError` (которое **должно propagate** согласно docstring line 98-100), `result = await result` (line 153) **НЕ вызывает**, потому что `check()` не возвращает awaitable — он бросает. Но если check возвращает корутину которая **внутри** бросает `CapabilityDeniedError` — `except Exception` (line 154) ловит и swallow'ит → ломается fail-loud security policy.

**Сравнение с `services/ai/ai_agent/policy_mixin.py:36-135`** (`_policy_gate`): там явный `except (ImportError, RuntimeError, AttributeError)` — CapabilityDeniedError пробрасывается.

**Impact (P1):**
- Security: `CapabilityDeniedError` может быть случайно swallowed.
- Docstring на line 98-100 обещает: «Raises: CapabilityDeniedError» — текущий код нарушает контракт в edge-case.

**Minimal recommendation:**
- `except (RuntimeError, AttributeError, ValueError)` вместо `except Exception` (аналог `_policy_gate`).
- Или явно `except Exception as exc: if isinstance(exc, CapabilityDeniedError): raise`.

**Test-criterion:**
- `test_check_capability_propagates_capability_denied_error` — gate с `check(...)` raises `CapabilityDeniedError` → assert raise.

---

### DOMAIN-P1-002 — composition root строит gateway с голыми DI-конструкторами (RESIDUAL)

**Path:** `src/backend/core/di/providers/ai.py:244-272`.

**Evidence:**

```python
@lru_cache(maxsize=1)
def _build_ai_gateway_singleton() -> Any:
    """Строит AIGateway со всеми обязательными DI (Sprint 1.3)."""
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.policy.resolver import PolicyResolver
    from src.backend.core.security.capabilities.gate import CapabilityGate
    from src.backend.core.tenancy.token_budget import InMemoryTokenBudgetBackend

    return AIGateway(
        policy_resolver=PolicyResolver(),         # ← no vocabularies / config
        capability_gate=CapabilityGate(),          # ← no capability registry / roots
        token_budget=InMemoryTokenBudgetBackend(), # ← no per-tenant limits
    )
```

Контраст — composition plugins `_build_workspace_manager` (`plugins/composition/ai_safety_setup.py:75`), `_build_waf_policy_from_settings` (`plugins/composition/waf_setup.py:72`) — читают settings и инжектят конфиг.

**Impact (P1):**
- CapabilityGate без capability-registry: `check()` всегда allow (default fail-open в check_mixin).
- PolicyResolver без vocabularies: `_resolve_policy()` всегда возвращает None → strict-mode (`ai_policy_enforce=True`) бросает `PolicyNotResolvedError` сразу.
- TokenBudget in-memory: per-tenant limits не из config — только из defaults.

**Minimal recommendation:**
- Composition root должен вызывать `_build_ai_gateway_with_settings(settings)` или `get_ai_gateway_from_config()`; provider читает `ai_agent_settings.policy_resolver` / `capability_registry` / `token_budget_per_tenant`.

**Test-criterion:**
- Integration test: `AIGateway(policy_resolver=...)` с реальным vocab → resolves `ai_policy_enforce=True` без `PolicyNotResolvedError`.

---

### DOMAIN-P1-003 — `get_ai_agent_service()` экспортируется как рабочая фабрика (RESIDUAL)

См. DOMAIN-P0-006 (combined evidence). Этот ID — soft-версия для backward-compat public API; реальный impact = DOMAIN-P0-006.

**Minimal recommendation:** объединить с DOMAIN-P0-006 fix.

---

### DOMAIN-P1-004 — `LiteLLMModel.request_stream` NotImplementedError + дубль `LiteLLMModelAdapter` (RESIDUAL)

**Path:** `src/backend/services/ai/agents_pydantic/adapter.py:105-115`.

**Evidence:**

```python
# adapter.py:105-115
@asynccontextmanager
async def request_stream(
    self,
    messages: list[ModelMessage],
    model_settings: ModelSettings | None,
    model_request_parameters: ModelRequestParameters,
) -> AsyncIterator[StreamedResponse]:
    """Streaming not supported yet."""
    raise NotImplementedError(
        f"Streaming not yet supported by {self.__class__.__name__}"
    )
```

Дубль-имплементация `LiteLLMModelAdapter` в `core/ai/pydantic_ai_client.py:422-621` уже реализует:
- `request` (line 462-...)
- `request_stream` (через `_SimpleStreamedResponse` line 621)
- `prepare_request`
- `supported_builtin_tools`
- `supported_native_tools`

**Использование**:
- `grep -rn "BasePydanticAgent" extensions/` → **0 hits** (только `services/ai/agents_pydantic/examples/`).
- `LiteLLMModel` импортируется в: `agents_pydantic/base.py:184` (`_build_agent`), `tests/unit/services/ai/test_pydantic_ai_provider.py:24`, `tests/unit/services/ai/agents_pydantic/test_litellm_adapter.py:9`, `tests/unit/core/ai/test_ai_gateway_enforcement.py:93`.

**Impact (P1):**
- Пока production extensions не используют `BasePydanticAgent` — нет runtime impact. Но future use (планируется в roadmap) сломается на streaming.
- Дубль-имплементация (`adapter.py` + `pydantic_ai_client.py:422`) — нарушает DRY, увеличивает maintenance.
- Cycle-2 audit `principal-audit-2026-07-27/CYCLE_2_REPORT.md:52` уже отмечал: "Layer 8: 2 near-identical pydantic_ai adapters (LiteLLMModelAdapter + LiteLLMModel, ~285 LOC) — medium-risk refactor".

**Minimal recommendation:**
- Удалить `LiteLLMModel` (`agents_pydantic/adapter.py`), оставить `LiteLLMModelAdapter` в `pydantic_ai_client.py` как canonical impl.
- `BasePydanticAgent._build_agent()` — импортировать `LiteLLMModelAdapter` (rename или alias).

**Test-criterion:**
- `test_pydantic_ai_request_stream_produces_streamed_response` — streaming через `LiteLLMModelAdapter` (или новый canonical).

---

### DOMAIN-P2-002 — stale docstring в `ai_tool_dispatch.py` (RESIDUAL)

**Path:** `src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py:22-25`.

**Evidence:**

```python
# ai_tool_dispatch.py:22-25 (docstring)
Real AIGateway wiring (S106+ W5+ multi-wave scope). Сейчас ``_run`` помечает
exchange ошибкой ``NotImplementedError`` (scaffold) и эмитит audit
``ai.tool.dispatch`` с outcome=scaffold.
```

Реальный `_run` (line 98-226) реализует full pipeline (resolve query → build prompt → call AIGateway → parse JSON → whitelist check → ToolRegistry.get → invoke → set_property).

**Impact (P2):** docstring misleading → следующий разработчик может не понять, что код уже реализован.

**Minimal recommendation:** обновить docstring до реального состояния (S107+ W4 fully wired).

**Test-criterion:** — (doc-only fix).

---

### DOMAIN-P2-003 — `fastmcp_server.start()` / `stop()` — мёртвый интерфейс (RESIDUAL)

**Path:** `src/backend/dsl/agents/fastmcp_server.py:135-147`.

**Evidence:** `grep -rn "fastmcp_server.start\|fastmcp_server.stop\|FastMCPserver.start\|FastMCPserver.stop" src/` → **0 production callers**.

```python
# fastmcp_server.py:137-147
async def start(self) -> None:
    """No-op. Server is managed by the ASGI host (uvicorn/FastAPI)."""
    logger.debug("FastMCPserver.start() called — ASGI app lifecycle managed by caller")

async def stop(self) -> None:
    """No-op. Server is managed by the ASGI host (uvicorn/FastAPI)."""
    logger.debug("FastMCPserver.stop() called — ASGI app lifecycle managed by caller")
```

**Impact (P2):** мёртвый public API; путает с реальным lifecycle.

**Minimal recommendation:** удалить оба метода (или пометить `@deprecated("managed by ASGI host")`).

**Test-criterion:** — (doc-only или remove).

---

### DOMAIN-P3-001 — `optimize_prompt` ссылается на незарегистрированные DI services

**Path:** `src/backend/dsl/engine/processors/agent_dsl/optimize_prompt.py:74-79`.

**Evidence:**

```python
# optimize_prompt.py:73-86
try:
    from src.backend.core.svcs_registry import get_service
    trainer = get_service("dspy_feedback_trainer")
    if trainer is None:
        trainer = get_service("feedback_trainer")
except Exception as exc:
    _logger.warning("optimize_prompt: trainer not found in DI: %s", exc)
    ...
```

Проверка регистрации: `grep -rn "register_factory.*dspy\|register_factory.*feedback_trainer\|register_factory.*optimize" src/backend/` → **0 hits**.

`grep -n "register_factory" src/backend/plugins/composition/service_setup.py` → `("orders", ...)`, `("users", ...)`, ..., `("ai", get_ai_agent_service)` — **нет** `dspy_feedback_trainer` / `feedback_trainer`.

`get_service("dspy_feedback_trainer")` (per `core/svcs_registry.py:86-112`) бросит `KeyError`, ловится в `except Exception` → trainer = None → processor returns `{"status": "noop", "reason": "no trainer registered"}`.

**Impact (P3):**
- OptimizePromptProcessor всегда возвращает noop — dead code path.
- DSPy integration (`services/ai/dspy/feedback_trainer.py` + `optimizer.py`) — недостижима из DSL.

**Minimal recommendation:**
- Либо зарегистрировать `feedback_trainer` factory в `plugins/composition/service_setup.py:register_all_services()`.
- Либо удалить `OptimizePromptProcessor` (если DSPy пока не планируется).

**Test-criterion:**
- `test_optimize_prompt_invokes_trainer_when_registered` — mock `get_service("dspy_feedback_trainer")` returns trainer → assert `trainer.optimize` called.

---

### DOMAIN-P4-001 — `workflow_hooks.register_*` — public API unused

**Path:** `src/backend/core/ai/security/workflow_hooks.py:33-42`.

**Evidence:** `grep -rn "register_banking_transaction_hook\|register_rpa_browser_hook\|register_code_generation_hook\|register_data_export_hook" src/` → 0 production callers (только docstring example line 16-19).

**Impact (P4):** future feature surface; organic extension if/when banking/RPA/code-gen workflows начнут использовать security framework.

**Minimal recommendation:** либо удалить до начала использования, либо документировать как public API + добавить в `ai_safety_setup.py:register_all_safety()` (orgанично: при `feature_flags.banking_security_enabled` → register).

**Test-criterion:** — (organic; не блокирует).

---

## 5. Cycle-1 residuals (verified или mutated)

| Cycle-1 ID | Cycle-2 статус | Evidence |
|---|---|---|
| DOMAIN-P0-001 | **RESOLVED (cycle-1 Phase 4 T-1.5)** | `policy_mixin.py:108-150` dual-signature detection. Тесты `test_check_capability_three_arg_real_gate_called`, `test_check_capability_one_arg_real_gate_called`, `test_check_capability_typeerror_falls_back_to_one_arg` — все pass. Working-tree diff подтверждает fix. **НЕ атрибутируется рою cycle 2.** |
| DOMAIN-P0-002 | **RESOLVED (cycle-1 Phase 4 T-1.5)** | `gateway_adapter.py:100-142` raise `AIGatewayProductionWiringError` вместо silent `AIGateway()` fallback. Working-tree diff подтверждает fix. **НЕ атрибутируется рою cycle 2.** |
| DOMAIN-P0-003 | **RESIDUAL** | Hardcoded `tenant_id` всё ещё в `ai_tool_dispatch.py:251`, `plan_execute.py:270`, `reflection_loop.py:254`. См. раздел 4 (DOMAIN-P0-003). |
| DOMAIN-P0-004 | **RESIDUAL** | `fastmcp_server.py:36-39` всё ещё импортирует `infrastructure.workflow.registry`. См. раздел 4 (DOMAIN-P0-004). |
| DOMAIN-P1-001 | **MUTATED (частично closed by T-1.5)** | T-1.5 fix переписал try/except placement корректно для `check()` call, но всё ещё имеет `except Exception` вокруг `inspect.isawaitable(result): await result` (line 151-157) который swallow'ит `CapabilityDeniedError`. Cycle-1 finding был строже (placement), cycle-2 — narrowed scope (specific exception type). См. DOMAIN-P1-001 в разделе 4. |
| DOMAIN-P1-002 | **RESIDUAL** | `_build_ai_gateway_singleton` всё ещё собирает голые `PolicyResolver()` / `CapabilityGate()` / `InMemoryTokenBudgetBackend()` без DI-конфигов. См. DOMAIN-P1-002. |
| DOMAIN-P1-003 | **RESIDUAL — elevated to P0** | См. DOMAIN-P0-006 (production crash). |
| DOMAIN-P1-004 | **RESIDUAL** | `LiteLLMModel.request_stream` → `NotImplementedError` всё ещё в `adapter.py:113`. См. DOMAIN-P1-004. |
| DOMAIN-P1-005 | **RESIDUAL** (allowlist-only) | 6 core→services direct imports (`core/ai/{gateway_pipeline_mixin/{input_mixin:132,llm_mixin:74,output_mixin:139},multi_agent:10,policy/enforcer/input_guard_mixin:122,llm_gateway:23}`) — все в `tools/check_layers_allowlist.txt`. Layer-checker пропускает (allowlist). Архитектурное нарушение — documented, не closed. |
| DOMAIN-P2-001 | **RESIDUAL** | `ai_tool_dispatch.py:22-25` docstring всё ещё говорит "NotImplementedError (scaffold)". См. DOMAIN-P2-002 (cycle-2 уточнённая версия). |
| DOMAIN-P2-002 | **RESIDUAL** | `skill_invoke.py:20-21` docstring всё ещё упоминает "scaffold-режиме". NotImplementedError catch (line 96-101) — defensive fallback. Фактически код обрабатывает NotImplementedError как expected path → если `SkillRegistry.invoke()` действительно поднимает NotImplementedError — silent skip. Это OK как defensive, но docstring misleading. **Вне scope cycle-2 приоритета (P2).** |
| DOMAIN-P2-003 | **RESIDUAL** | `fastmcp_server.py:137-147` start/stop no-ops. См. DOMAIN-P2-003. |
| DOMAIN-P3-001 | **NOT INVESTIGATED in cycle-1** (new in cycle-2: см. DOMAIN-P4-001 для похожего паттерна). | `agent_security.py` OWASP pattern list (~24 regex) — оставлено как is. Library replacement `llm-guard` REMOVED в pyproject (line 207: «REMOVED 2026-07-16: protectai/llm-guard archived»). LlamaGuardRuntime / Lakera Guard API — alternatives, но custom pattern list OK для production. |
| DOMAIN-P3-002 | **NOT INVESTIGATED** (policy_mixin.py uses AuthorizationGateway already; cycle-2 подтверждает). | `services/ai/ai_agent/policy_mixin.py:36-135` использует AuthorizationGateway pattern. См. S-6. |
| DOMAIN-P4-001 | **NOT INVESTIGATED in cycle-1**. | DSPy integration — отдельная code-path; optimize_prompt мёртв (см. DOMAIN-P3-001). |
| DOMAIN-P4-002 | **PARTIALLY OBSERVED**: новый finding DOMAIN-P0-005 (LangGraphAgentProcessor process crash) — это concrete variant cycle-1's abstract "subgraphs отсутствуют". | См. DOMAIN-P0-005. |

---

## 6. Contradictions / overlaps to flag

1. **DOMAIN-P0-006 vs DOMAIN-P1-003**: cycle-1 P1-003 vs cycle-2 P0-006 — это **тот же finding**, но разный priority. Cycle-2 escalation обоснована: 7 production callsites + `action_handler_registry.dispatch()` → `service_getter()` crash on first action invocation. Не два независимых finding — один finding, разные severity views. Рекомендую объединить в **DOMAIN-P0-006** в phase-2 triage.

2. **DOMAIN-P1-001 (cycle-1) vs DOMAIN-P1-001 (cycle-2)**: cycle-1 finding был шире («try/except placement wrong, propagates TypeError/CapabilityDeniedError»). T-1.5 fix решил placement для `check()` call, но оставил bare `except Exception` вокруг `await result`. Cycle-2 narrowed scope до конкретного narrow issue. Это **evolved finding**, не duplicate.

3. **DOMAIN-P0-005 vs cycle-1 DOMAIN-P4-002**: cycle-1 P4-002 был abstract («subgraphs отсутствуют, Airflow-style DAG отсутствует»). Cycle-2 P0-005 — concrete TypeError в существующем `langgraph_agent` processor. Это **concrete instantiation** cycle-1's abstract concern.

4. **DOMAIN-P3-001 vs DOMAIN-P4-001 (cycle-2 own)**: оба о dead code paths. DOMAIN-P3-001 — DI keys не зарегистрированы (конкретный finding); DOMAIN-P4-001 — workflow hooks API не подключён. Разные механизмы, одинаковый outcome (dead code).

5. **DOMAIN-P0-003 vs DOMAIN-P0-002 (RESOLVED)**: cycle-1 P0-002 был о fail-open при fallback `AIGateway()` (RESOLVED в T-1.5). Cycle-1 P0-003 — hardcoded tenant_id в 3 процессорах. Это **разные attack vectors**: P0-002 — bypass policy/capability/budget; P0-003 — wrong audit attribution / per-tenant budget mis-attribution. Cycle-2 P0-003 — RESIDUAL.

---

## 7. Readiness score 0–100 (формула и обоснование)

**Формула** (cycle-2 alignment с другими phase-1 отчётами):
```
readiness = (strength_score × 0.40) + (security_score × 0.30) +
            (architecture_score × 0.20) + (production_readiness × 0.10)
```

**Расчёт компонентов** (по 100 max):

| Компонент | Score | Обоснование |
|---|---|---|
| `strength_score` (verified strengths count) | **80** | 12 verified strengths (S-1..S-12). T-1.5 fix verified; composition root DI работает; `@app_state_singleton` pattern работает где применён; fail-closed policy gate; tenant allowlist; deny file:// transport; query cap. |
| `security_score` (P0 security findings) | **0** | **4 P0**: DOMAIN-P0-005 (TypeError in production path), DOMAIN-P0-006 (NotImplementedError factory × 7 callsites), DOMAIN-P0-003 (hardcoded tenant_id × 3), DOMAIN-P0-004 (layer violation DSL→infra). |
| `architecture_score` (P1 layer boundaries) | **50** | 4 P1: DOMAIN-P1-001 (swallowed exception), DOMAIN-P1-002 (bare DI), DOMAIN-P1-003 (overlap P0-006), DOMAIN-P1-004 (duplicate adapter). С учётом, что P1-003 — это overlap с P0-006, реальная P1 density = 3. Layer-checker baseline: 175 legacy / 0 new — нет новых нарушений от роя. |
| `production_readiness` (P2 dead code + P3 library replacement) | **70** | 2 P2 (stale docstrings, dead start/stop), 1 P3 (DSPy dead DI), 1 P4 (workflow hooks unused). Не блокирует, но показывает organic debt. |

**Итог**:
```
readiness = (80 × 0.40) + (0 × 0.30) + (50 × 0.20) + (70 × 0.10)
          = 32 + 0 + 10 + 7
          = 49
```

**Обоснование 49/100**:
- 4 P0 блокируют production readiness (`security_score = 0` × 0.30 = 0).
- Strengths есть, но overridden by P0-006 (NOT_IMPLEMENTED factory — 7 production callsites = broken LLM-action subsystem).
- DOMAIN-P0-005 (LangGraphAgentProcessor) — broken core DSL path.
- DOMAIN-P0-003 (hardcoded tenant_id) — audit lineage broken.
- DOMAIN-P0-004 (DSL→infra coupling) — architectural debt.
- Per scoring rule: «**Оценка ≥80 запрещена при наличии P0/P1**». Текущая 49 → well below threshold.

---

## 8. Recommended next tasks (cycle 2 Phase 2 / Phase 3)

| Приоритет | Задача | Связь | Ожидаемый эффект |
|---|---|---|---|
| **P0-A** | Fix `get_ai_agent_service()` (DOMAIN-P0-006): добавить `@app_state_singleton("ai_agent_service", factory=AIAgentService)` decorator + зарегистрировать `app.state.ai_agent_service` в `plugins/composition/di.py:register_app_state()` (после `app.state.ai_gateway`). | DOMAIN-P0-006, DOMAIN-P1-003 | Закрывает 7 production callsites. |
| **P0-B** | Fix `LangGraphAgentProcessor.process()` (DOMAIN-P0-005): `query=self.query` → `prompt=self.query`; `thread_id=self.thread_id` → `session_id=self.thread_id`; добавить `tool_actions` (например, `self.tool_actions or []`). | DOMAIN-P0-005 | Закрывает broken core DSL path. |
| **P0-C** | Fix hardcoded `tenant_id` (DOMAIN-P0-003): пробрасывать `exchange.meta.tenant_id`/`exchange.meta.correlation_id` в `_ask_llm_for_tool_selection`, `_call_workflow`. | DOMAIN-P0-003 | Audit lineage restored. |
| **P0-D** | Fix `fastmcp_server` layer violation (DOMAIN-P0-004): создать `core/ai/workflow_protocol.py` Protocol `WorkflowCatalog`; импортировать Protocol вместо infrastructure. | DOMAIN-P0-004 | Устраняет reverse-coupling. |
| **P1-A** | Tighten `except Exception` в `_check_capability` (DOMAIN-P1-001): заменить на `except (RuntimeError, AttributeError, ValueError)` или явный re-raise `CapabilityDeniedError`. | DOMAIN-P1-001 | Fail-loud security. |
| **P1-B** | Composition root DI config (DOMAIN-P1-002): `_build_ai_gateway_singleton()` читать `ai_agent_settings` / `capability_settings` / `token_budget_settings` вместо bare constructors. | DOMAIN-P1-002 | Production-correct DI. |
| **P1-C** | Dedup `LiteLLMModel` (DOMAIN-P1-004): удалить `services/ai/agents_pydantic/adapter.py`; canonical = `core/ai/pydantic_ai_client.py:LiteLLMModelAdapter`. | DOMAIN-P1-004 | DRY, future-proof. |
| **P2-A** | Update stale docstrings (DOMAIN-P2-002): `ai_tool_dispatch.py:22-25` — «scaffold» → «real LLM-wiring (S107 W4)». | DOMAIN-P2-002 | Dev velocity. |
| **P2-B** | Remove dead `start()/stop()` (DOMAIN-P2-003): или пометить `@deprecated`. | DOMAIN-P2-003 | API hygiene. |
| **P3-A** | Register DSPy trainer (DOMAIN-P3-001): `register_factory("dspy_feedback_trainer", get_feedback_trainer)` в `plugins/composition/service_setup.py`. | DOMAIN-P3-001 | DSPy integration live. |
| **P4-A** | Decide workflow_hooks fate (DOMAIN-P4-001): органично подключить в `ai_safety_setup.py` при `feature_flags.banking_security_enabled`, или удалить. | DOMAIN-P4-001 | Future security surface. |

---

## 9. Commands run (audit trail)

```bash
# Baseline
git log --oneline -5
# ca5bff93 docs(s183-w2): cycle retrospective — 4 P0 fixes done, combined reviewer PASS
git status --short
# (10 modified files: 5 source + 3 test + 1 preflight + 1 tool; 5 untracked)
python tools/check_layers.py --root src   # exit 0; "Нарушений: 0 новых (файлов: 2273; baseline: 175 legacy)"
wc -l tools/check_layers_allowlist.txt     # 180 (175 valid + 5 comments/empty)

# Cycle-1 finding verification
git diff src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py    # T-1.5 fix confirmed in working tree (cycle-1 Phase 4)
git diff src/backend/services/ai/gateway_adapter.py                    # T-1.5 fix confirmed in working tree (cycle-1 Phase 4)

# DOMAIN-P0-003 verification
grep -n "tenant_id" src/backend/dsl/engine/processors/agent_dsl/{ai_tool_dispatch,plan_execute,reflection_loop,agent_run}.py
# 3 hardcoded: ai_tool_dispatch.py:251 "default", plan_execute.py:270 "unknown", reflection_loop.py:254 "unknown"
# Correct: agent_run.py:137 "exchange.meta.tenant_id or 'unknown'"

# DOMAIN-P0-004 verification
grep -n "fastmcp_server" tools/check_layers_allowlist.txt  # 0 hits (DSL→infra allowed by layer checker, but architectural coupling exists)

# DOMAIN-P0-006 — NotImplementedError factory
python -c "import unittest.mock as mock; \
    with mock.patch('src.backend.core.di.providers.ai.get_ai_sanitizer_provider') as m: \
        m.return_value = mock.MagicMock(); \
        from src.backend.services.ai.ai_agent import get_ai_agent_service; \
        get_ai_agent_service()"
# → NotImplementedError

# 7 production callsites of get_ai_agent_service
grep -rn "get_ai_agent_service" src/backend/ | grep -v "cache\|.pyc\|test"
# ml_inference.py:162-164, llmfallback_processor.py:46-48, llmcall_processor.py:214-219,
# ai_banking/_base.py:96-100, route_authz.py:124-126, llm_judge.py:115-117,
# registers_integrations.py:14-37 (4 ActionHandlerSpec), service_setup.py:212 (register_factory)

# app.state.ai_agent_service — NEVER registered
grep -rn "app.state.ai_agent" src/backend/  # 0 hits

# DOMAIN-P0-005 — TypeError в LangGraphAgentProcessor
python -c "import asyncio; \
    from src.backend.services.ai.ai_graph import build_and_run_agent; \
    asyncio.run(build_and_run_agent(query='x', thread_id='t', max_iterations=10))"
# → TypeError: build_and_run_agent() got an unexpected keyword argument 'query'

# Signature verification
python -c "import inspect; from src.backend.services.ai.ai_graph import build_and_run_agent; \
    print(inspect.signature(build_and_run_agent))"
# (prompt: 'str', tool_actions: 'list[str]', *, gateway, model, temperature, durable, session_id)

# DOMAIN-P3-001 — DSPy trainer not registered
grep -rn "register_factory.*dspy\|register_factory.*feedback_trainer" src/backend/  # 0 hits
grep -n "register_factory" src/backend/plugins/composition/service_setup.py | head -20  # orders/users/files/etc., no dspy

# DOMAIN-P1-004 — дубль LiteLLMModel
grep -rn "BasePydanticAgent" extensions/  # 0 hits (only in examples/)
grep -rn "LiteLLMModel" src/backend/services/ai/agents_pydantic/ src/backend/services/ai/ai_graph.py 2>&1 | head -10
# adapter.py:16 export, base.py:184 import (in _build_agent)

# DOMAIN-P2-003 — fastmcp start/stop callers
grep -rn "fastmcp_server.start\|fastmcp_server.stop\|FastMCPserver.start\|FastMCPserver.stop" src/  # 0 hits

# DOMAIN-P4-001 — workflow_hooks callers
grep -rn "register_banking_transaction_hook\|register_rpa_browser_hook\|register_code_generation_hook\|register_data_export_hook" src/  # 0 production

# Dead-code sweep
grep -rn "raise NotImplementedError\|^[[:space:]]*pass$" src/backend/services/ai/ai_agent/ src/backend/services/ai/agents_pydantic/ src/backend/dsl/agents/ src/backend/dsl/engine/processors/agent_dsl/
# ai_agent/__init__.py:111 (raise NotImplementedError — DOMAIN-P0-006)
# agents_pydantic/adapter.py:113 (raise NotImplementedError — DOMAIN-P1-004)
# mcp_tool.py:45 (pass — bare except ImportError for fastmcp import)
# optimize_prompt.py:71 (pass — bare except Exception — DOMAIN-P3-001 risk)

# TODO/FIXME sweep
grep -rn "TODO\|FIXME\|XXX" src/backend/dsl/engine/processors/agent_dsl/*.py src/backend/dsl/agents/*.py src/backend/services/ai/agents_pydantic/*.py src/backend/services/ai/ai_agent/*.py  # 0 hits
```

---

## 10. Summary

**Cycle-1 partial closure**: T-1.5 (DOMAIN-P0-001 + DOMAIN-P0-002) — resolved (verified in working tree, не атрибутируется рою cycle 2). 7 cycle-1 findings — RESIDUAL (DOMAIN-P0-003, DOMAIN-P0-004, DOMAIN-P1-002, DOMAIN-P1-003, DOMAIN-P1-004, DOMAIN-P2-001/002, DOMAIN-P2-003).

**Cycle-2 new findings** (4 P0, 4 P1, 2 P2, 1 P3, 1 P4 = **12 total**):
- **DOMAIN-P0-005**: LangGraphAgentProcessor process() → TypeError (production crash).
- **DOMAIN-P0-006**: get_ai_agent_service() NotImplementedError (7 production callsites).
- DOMAIN-P0-003: hardcoded tenant_id (RESIDUAL, 3 processors).
- DOMAIN-P0-004: fastmcp_server DSL→infra coupling (RESIDUAL).
- DOMAIN-P1-001: swallowed CapabilityDeniedError (cycle-1 mutated).
- DOMAIN-P1-002: bare DI constructors in composition root (RESIDUAL).
- DOMAIN-P1-003: get_ai_agent_service export contract (overlap P0-006).
- DOMAIN-P1-004: LiteLLMModel.request_stream NotImplementedError + duplicate adapter (RESIDUAL).
- DOMAIN-P2-002: stale docstring (RESIDUAL).
- DOMAIN-P2-003: dead fastmcp start/stop (RESIDUAL).
- DOMAIN-P3-001: DSPy trainer DI keys not registered (new).
- DOMAIN-P4-001: workflow_hooks public API unused (new).

**Readiness: 49/100** (formula: 80×0.40 + 0×0.30 + 50×0.20 + 70×0.10). 4 P0 + 4 P1 блокируют ≥80.

**Layer-checker baseline**: 175 legacy / 0 new (ca5bff93) — стабильно с cycle-1. `wc -l tools/check_layers_allowlist.txt` = 180 (175 валидных + 5 пустых/комментариев). **Заявленный рост 173→180 НЕ подтверждается** — это несоответствие в данных cycle-1 (173) vs cycle-2 baseline (175 + 5 file-level comments) vs raw `wc -l` (180). Аналитикам phase-2 следует уточнить источник «173→180» (возможно, считались только legacy без комментариев; разница 5 = новые комментарии добавлены в allowlist, не новые violations).

**Блокирующие P0 для production**:
1. **DOMAIN-P0-006** — broken LLM-action subsystem (7 callsites).
2. **DOMAIN-P0-005** — broken LangGraph DSL path.
3. **DOMAIN-P0-003** — audit/budget lineage broken (3 processors).
4. **DOMAIN-P0-004** — architectural DSL→infra coupling.

**Composition root** (`plugins/composition/di.py:register_app_state`) **НЕ регистрирует `app.state.ai_agent_service`** — это root cause DOMAIN-P0-006; должно быть исправлено **одновременно** с decorator fix.

**Тесты, которые сейчас проходят** (mock'ают): `tests/unit/dsl/engine/processors/test_llmfallback_processor.py`, `test_llmcall_processor.py`, `tests/unit/dsl/engine/processors/test_agent_layer_wrappers.py` (mock `build_and_run_agent`), `tests/unit/dsl/engine/processors/agent_dsl/test_{plan_execute,reflection_loop,ai_tool_dispatch}.py` (mock gateway). **Без mock'ов все эти тесты упадут** на production code path. Это маскирует 4 P0 finding.

**Дополнительные проверки, которые НЕ проводились** (out of scope): `pydantic_ai_client.py` (644 LOC) полностью; vendor libs; extensions/; production deployment pipeline.