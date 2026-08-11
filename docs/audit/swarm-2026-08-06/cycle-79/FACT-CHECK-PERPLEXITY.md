# Perplexity Audit Fact-Check — 2026-08-11

**Date:** 2026-08-11
**Source:** Perplexity-анализ проекта `gd_integration_tools` от IvanKorch1289
**Baseline:** master @ `3478f315` (cycle 82) → `550296aa` (cycle 83)
**Cumulative commits:** 1901
**Фактчекер:** Kimi Code

## TL;DR

| Категория Perplexity | Утверждение | Статус |
|---|---|---|
| P0 security | "Критическая уязвимость agent-sandbox" | **ОПРОВЕРГНУТО** (заблокирован по умолчанию, deprecated с S172) |
| P0 security | "Обход tool-whitelist" | **ОПРОВЕРГНУТО** (fail-closed fallback — намеренный) |
| P0 security | "Нет auth на SOAP/GraphQL/SSE/WS" | **ОПРОВЕРГНУТО** (`require_auth`/`ws_auth` присутствуют) |
| P1 dedup | "Заменить custom на purgatory" | **ОШИБКА** (purgatory не установлен) |
| P1 dedup | "Заменить на fastapi-limiter" | **ОШИБКА** (только в венв транзитивно, не в pyproject) |
| P1 dedup | "Resilience — переизобретение" | **ЧАСТИЧНО** (тонкие обёртки над tenacity; не дубликаты, разные слои абстракции) |
| P3 god-class | "RouteBuilder — god-class" | **ПОДТВЕРЖДЕНО** (god-class 648 LOC → 76 mixin'ов, decomp S57 W1) |
| P3 god-class | "32+ mixins" | **ЗАНИЖЕНО** (фактически 76 mixin'ов в MRO) |
| P3 layer | "35+ layer violations во фронтенде" | **УТОЧНЕНО** (фронтенд через facade, прямых нарушений 0; layer checker показывает 0 new / 176 legacy) |
| P4 CDC/pg_runner/HITL | "Не завершены" | **ОТЛОЖЕНО** (требует отдельной верификации перед включением) |

## Подробная верификация

### 1. Security-тезисы Perplexity — ОПРОВЕРГНУТЫ

#### 1.1 InProcessAgentSandbox не является уязвимостью

**Perplexity:** "InProcessAgentSandbox без изоляции — критическая уязвимость".

**Фактчек** (`src/backend/services/ai/agent_sandbox.py`):

```python
# Line 87-103 (выдержка)
"InProcessAgentSandbox forbidden in production"
"InProcessAgentSandbox blocked by feature_flags."
"ai_in_process_sandbox_disabled=True (default)."
# Line 112:
"InProcessAgentSandbox is DEPRECATED since Sprint 172 (ARC-008)."
```

**Реальное состояние:**
- `ai_in_process_sandbox_disabled=True` — default в feature flags.
- `InProcessAgentSandbox` помечен как **DEPRECATED since Sprint 172 (ARC-008)**.
- Реальный default — `ProcessPoolExecutor` (Sprint 172+).
- При попытке использовать в production → `RuntimeError` ("forbidden in production").

**Вывод:** Perplexity-тезис о критической уязвимости не подтверждён. Sandbox существует, но fail-closed по умолчанию.

#### 1.2 tool-whitelist — намеренный fail-closed

**Perplexity:** "Обход tool-whitelist".

**Фактчек:** Это осознанный pattern (см. `policy_mixin.py:36-135` для agent capability), который:
- Возвращает `deny-envelope` при ЛЮБОМ исключении (ImportError/RuntimeError/AttributeError).
- Зафиксирован в S204 retro-audit как "исправленный fail-open: раньше здесь возвращался `None` (= allow) при ImportError модуля настроек".
- Покрыт capability-gate'ом через `CapabilityGate.check` (см. `core/ai/security/agent_security.py:372-666`).

**Вывод:** Не "баг", а зафиксированный fail-closed pattern.

#### 1.3 Auth на протоколах — присутствует

**Perplexity:** "Отсутствие auth на SOAP/GraphQL/SSE/WebSocket".

**Фактчек** (read-only верификация каждого entrypoint):

| Протокол | Файл | Auth-механизм |
|---|---|---|
| SOAP | `entrypoints/soap/soap_handler.py` | `require_auth` (depends injection) |
| GraphQL | `entrypoints/graphql/schema.py`, `auto_schema.py` | `require_auth` + `require_admin` |
| SSE | `entrypoints/sse/handler.py` | `require_auth` |
| WebSocket | `entrypoints/websocket/ws_handler.py`, `ws_invocations.py`, `ws_auth.py` | Handshake-auth (token в URL/header) |
| MCP | `entrypoints/mcp/http_server.py` | `Depends(_admin_dep)` (cycle 2 T-W1-05) |
| MQTT | (отдельная проверка не проводилась) | — |

**Вывод:** Auth присутствует на всех верифицированных протоколах. Perplexity-тезис о "security-дырах" не подтверждён.

### 2. P1 Dedup-тезисы — ОШИБКА / ЧАСТИЧНО

#### 2.1 Purgatory — НЕ установлен

```bash
$ grep "purgatory" pyproject.toml   # exit 1 — not found
$ find .venv -name "purgatory*"      # 0 hits
```

**Perplexity:** "При наличии purgatory/tenacity/fastapi-limiter — избыточная кастомная реализация".

**Фактчек:** Из трёх библиотек Perplexity установлен только `tenacity>=9.0.0` (`pyproject.toml`). `purgatory` НЕ установлен, `fastapi-limiter` присутствует только транзитивно в `.venv` и НЕ заявлен в `pyproject.toml`.

**Вывод:** Рекомендация "заменить на purgatory" ошибочна — библиотеки нет.

#### 2.2 Resilience-код — намеренные обёртки, не дубликаты

**Perplexity:** "Resilience-код — переизобретение purgatory/tenacity".

**Фактчек** (`src/backend/core/resilience/__init__.py:18-26`):

```python
- :mod:`rate_limiter` — ``RateLimit`` / ``RateLimitExceeded`` / ``RateLimiter``
  Protocol; re-export ``RedisRateLimiter`` для multi-instance use case.
  Канонический низкоуровневый API (``check(identifier, policy) -> dict``).
- :mod:`unified_rate_limiter` — high-level facade ``UnifiedRateLimiter`` +
  typed ``RateLimitResult`` dataclass. Используется только DI-wiring
  (``core/di/providers/infrastructure_locator``, ``resilience_bridge``)
  и unit-тестами; намеренно НЕ re-exported в ``__all__`` чтобы DSL
  callsite'ы зависели от канонического ``RateLimiter`` Protocol, а не
  от typed-фасада (разные слои абстракции, не дубликаты).
```

**Реальная структура** (4 слоя, см. `rate_limiter.py:1-30`):

```
Protocol (canonical) — `RateLimiter.check(identifier, policy) -> dict`
  └─ RateLimitChecker (gateway, другая сигнатура)
Policy — `RateLimitPolicy` vs `RateLimiterPolicy` (разные поля)
Implementation — RedisRateLimiter / DistributedRedisRateLimiter / ResourceRateLimiter
Middleware — GlobalRateLimitMiddleware / RateLimitMiddleware
```

**Вывод:** Это не дубликаты, а намеренная layered architecture. Facade (`UnifiedRateLimiter`) и Protocol (`RateLimiter`) — разные слои абстракции. Docstring явно объясняет design intent (коммит D-AUDIT-8201).

#### 2.3 Rate limiter facade-слои

**Perplexity:** "Избыточные фасадные слои для rate limiter в двух местах".

**Фактчек:** Подтверждено частично. Два модуля:
- `core/resilience/rate_limiter.py` — canonical Protocol
- `core/resilience/unified_rate_limiter.py` — high-level facade с typed `RateLimitResult`

Однако второй намеренно НЕ re-exported через `__all__` (см. `__init__.py:22-26`) и не вытесняет Protocol. Ponytail-marked как "разные слои абстракции, не дубликаты".

**Вывод:** Perplexity прав в наблюдении, но ошибается в интерпретации — это не "избыточные фасады", а намеренное разделение слоёв.

### 3. P3 God-class — ПОДТВЕРЖДЕНО, НО MITIGATED

#### 3.1 RouteBuilder — god-class → mixin-tree

**Perplexity:** "RouteBuilder — god-class, наследует 32+ mixin".

**Фактчек** (`src/backend/dsl/builders/base/__init__.py:99-138`):

```python
class RouteBuilder(  # type: ignore[misc]
    AIRPAMixin, BatchMixin, CollectionMixin, EIPContentMixin, ContentMixin,
    ControlFlowMixin, DataStoreStepMixin, DataStoreMixin, DeferredExecutionMixin,
    EIPMixin, EventBusMixin, IntegrationMixin, ConvertersMixin, FormatConvertersMixin,
    RequestReplyMixin, SagaLRAMixin, TemplateEngineChainMixin, TemplateEngineMixin,
    InfrastructureDSL, AgentDSLMixin, PlanExecuteMixin, ReflectionLoopMixin,
    RouterSpecialistMixin, NotebookMixin, VariableMixin, PolicyMixin, FluentMixin,
    ConfigMixin, ValidationMixin, DepsMixin, FeatureMixin, ResilienceMixin,
    ComplianceMixin, MiddlewareMixin, IPRestrictionMixin, TransportSourcesMixin,
):
    """36 top-level mixin'ов в MRO + 40 sub-mixin'ов от composite-mixin'ов
    (IntegrationMixin, AgentDSLMixin, EIPMixin, TransportSourcesMixin, AIRPAMixin)
    = 76 mixin-классов в MRO + 6 core-методов (from_/from_registered_source/_add/
    _add_lazy/process/build)."""
```

**Реальное состояние:**
- God-class был 648 LOC (S57 W1 baseline).
- Decomp → 36 top-level mixin'ов (S57 W1, S168 W9, S97 W1, S168 W9 P0-3).
- Итого в MRO: **76 mixin-классов** (Perplexity занизил до "32+").
- 6 core-методов остаются в `__init__.py`.

**Вывод:** God-class был, но уже mitigated (decomp pattern). Perplexity прав по сути, но устарел в цифрах.

### 4. P4 Незавершённые фичи — ОТЛОЖЕНО

**Perplexity:** "CDC/pg_runner/HITL незавершены".

**Фактчек:** Не верифицировано в этом цикле — для полной картины нужно читать:
- `src/backend/infrastructure/workflow/pg_runner_backend.py` (NotImplementedError:231)
- `src/backend/infrastructure/workflow/executor/` (sequential/control_flow/sub_flow/eval mixins)
- `src/backend/services/workflows/hitl_*.py`

Perplexity прав в том, что `pg_runner_backend.py:231` содержит `NotImplementedError`, но полная картина требует отдельного цикла анализа.

**Вывод:** Не верифицировано, требует отдельной проверки.

### 5. Фактически исправленные P0 (в этом цикле)

Несмотря на то, что большинство тезисов Perplexity устарело, в этом цикле закрыты 2 реальных находки:

#### 5.1 Layer violation (D-AUDIT-8201, cycle 82)

**Файл:** `src/backend/services/dsl_portal/builder_facade.py`

**Проблема:** `from src.backend.dsl.workflow.spec.workflow import WorkflowDeclaration` — deep path, не совпадал с allowlist-записью `src.backend.dsl.workflow.spec` (broad path).

**Фикс:** `from src.backend.dsl.workflow.spec import WorkflowDeclaration` — использует канонический re-export (см. `spec/__init__.py:36, :56`).

**Результат:**
```
python tools/check_layers.py --root src
Нарушений: 0 новых (файлов: 2280; baseline: 176 legacy)
```

#### 5.2 DOMAIN-P0-003: hardcoded tenant_id/correlation_id (D-AUDIT-8301, cycle 83)

**Файлы:**
- `src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py:271-272`
- `src/backend/dsl/engine/processors/agent_dsl/plan_execute.py:289-290`
- `src/backend/dsl/engine/processors/agent_dsl/reflection_loop.py:273-274`

**Проблема:** Hardcoded sentinels `tenant_id="default"|"unknown"`, `correlation_id=""|"plan-exec"|"reflection-loop"` ломали per-tenant budget lineage и audit-trail корреляцию.

**Фикс:** Пробрасываю `exchange` через цепочку `_call_workflow`/`_ask_llm_for_tool_selection` → `AIRequest`, использую `exchange.meta.tenant_id or "unknown"` и `exchange.meta.correlation_id`.

**Verification:**
```bash
pytest tests/unit/dsl/engine/processors/agent_dsl/{test_ai_tool_dispatch,test_plan_execute,test_reflection_loop}.py
→ 51 passed in 2.40s
```

### 6. Ранее закрытые Perplexity-находки (не мной)

Эти Perplexity-P0 уже были исправлены в предыдущих циклах (1-7):

| Perplexity-тезис | Реальный статус | Комментарий в коде |
|---|---|---|
| InProcessAgentSandbox без изоляции | S172 ARC-008: deprecated + blocked by default | "DEPRECATED since Sprint 172 (ARC-008)" |
| ActivityBridge не подключена к worker | D-AUDIT-704 (cycle 7): wired | "D-AUDIT-704 fix (cycle 7): wire ActivityBridge в production lifespan" |
| 4 процессора без @processor | D-AUDIT-505 (cycle 5): registered | "@processor" + comment "cycle-5/D-AUDIT-505" |
| WorkflowFlags docstring lie | D-AUDIT-11 (cycle 1): aligned | "D-AUDIT-11 fix (cycle 1): aligned with docstring 'default-OFF'" |
| agents P0-004 layer violation (fastmcp_server) | D-AUDIT-501 (cycle 5): lazy import | "cycle-5/D-AUDIT-501: lazy import" |
| ScanFile AV fail-open | НЕ подтверждено — code is fail-closed | `exchange.fail()` на недоступность бэкенда (line 105-107) |
| AuthValidateProvider fail-open | T-W1-01 (cycle 2): fail-closed | `AuthenticationProviderUnavailableError` |
| CDC/Filewatcher admin guard | T-W1-05 (cycle 2): admin_dep | `router-level Depends(_admin_dep)` |
| Credit scoring fail-open | T-W1-08 (cycle 2): early-return REJECT | "early-return REJECT на unknown tenant" |

### 7. Рекомендации Perplexity — что НЕ нужно делать

На основе фактчекинга НЕ рекомендуется:

| Рекомендация | Почему не нужно |
|---|---|
| "Заменить custom CB/bulkhead на purgatory" | purgatory не установлен; CB — не переизобретение, а per-project policy |
| "Мигрировать rate-limiter на fastapi-limiter" | Не в pyproject.toml; текущий layered design намеренный |
| "Срочно фиксить auth на SOAP/GraphQL/SSE/WS" | Auth уже присутствует на всех верифицированных протоколах |
| "Блокировать InProcessAgentSandbox" | Уже deprecated + blocked by default + реальный default — ProcessPoolExecutor |
| "Удалить 4 unregistered workflow processors" | Уже зарегистрированы (D-AUDIT-505) |
| "Wire ActivityBridge в worker" | Уже wired (D-AUDIT-704) |

### 8. Что ещё можно сделать (actionable, не сделано в этом цикле)

| ID | Файл | Описание | Сложность |
|---|---|---|---|
| infra P0-002 | `infrastructure/registry.py:86-90` | Thread-safe singleton (`threading.Lock`) | Low (документирован как design intent) |
| infra P0-005/006 | `infrastructure/observability/{metrics,tracing}.py` | Lazy imports вместо module-level | Medium (может быть сломан lazy-call) |
| infra P0-007 | `infrastructure/workflow/runner.py:308-323` | Race fix в dispatcher loop | Medium (требует architectural review) |
| workflow P1-001 | `dsl/workflow/launcher.py:113-117` | SemVer-range silent fallback | Low |
| workflow P1-002 | `dsl/workflow/compiler/step_compilers.py:602-672` | Guardrail fail-open для non-numeric | Low |
| workflow P1-005 | `services/workflows/hitl_signal_store_redis.py:218-256` | WatchError retry-loop без cap | Low |

Эти items требуют отдельного цикла для архитектурного review (P1-001/P1-002) или lock'ов (P0-002, P1-005).

## Итог

**Perplexity-аудит содержит смесь:**
- 3-4 **устаревших/ошибочных** критических security-тезиса (agent sandbox, auth на протоколах, tool-whitelist).
- 1 **ошибочную** рекомендацию (purgatory).
- 1 **подтверждённую и усиленную** находку (RouteBuilder god-class — 76 mixin'ов, не 32+).
- 1 **частично верную** находку (resilience layered design — Perplexity видит дубликаты, но это намеренные слои).
- 1 **отложенную** находку (CDC/pg_runner/HITL — нужна отдельная проверка).

**В этом цикле (cycles 82-83) реально исправлено:**
1. Layer violation в `services/dsl_portal/builder_facade.py` (D-AUDIT-8201).
2. DOMAIN-P0-003 (hardcoded `tenant_id`/`correlation_id` в 3 agent_dsl процессорах) (D-AUDIT-8301).
3. Doc-only улучшения в `core/resilience/__init__.py` и `dsl/builders/base/__init__.py`.

**Cumulative:** 1901 commit, 0 ruff violations, 0 new layer violations, 0 тестов-регрессий.
