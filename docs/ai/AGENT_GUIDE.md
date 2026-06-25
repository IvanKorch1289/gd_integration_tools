# AI Agent Guide (Sprint 171 M7)

> **Практическое руководство для разработчиков агентов.**
> Создание политик, маскирование, agent workflow, версионирование промптов,
> memory + RLM, с подробными примерами и рекомендациями когда использовать.

## Оглавление

1. [Создание политик безопасности](#1-создание-политик-безопасности)
2. [Маскирование PII (Presidio + кастомные)](#2-маскирование-pii)
3. [Agent workflow (LangGraph + DSL)](#3-agent-workflow)
4. [Версионирование и оптимизация промптов](#4-версионирование-промптов)
5. [Memory (episodic / semantic / procedural)](#5-memory)
6. [RLM toolkit — когда и как использовать](#6-rlm-toolkit)
7. [Выбор правильного паттерна](#7-выбор-паттерна)
8. [Тестирование агентов](#8-тестирование-агентов)

---

## 1. Создание политик безопасности

### 1.1 Capability-based permissions

```python
# src/backend/dsl/builders/security.py
from src.backend.core.security.capabilities import CapabilityGate

# Декоратор для processor
@requires_capability("rpa.shell.exec")
class ShellExecProcessor(BaseProcessor):
    ...
```

### 1.2 Per-route policy (Camel-style)

```python
route = (
    RouteBuilder.from_("api.heavy", source="http:GET /api/heavy")
    .policy.cache(ttl_seconds=60)
    .policy.circuit_breaker(threshold=5, recovery_seconds=30)
    .policy.rate_limit(rate=100, per_seconds=1)
    .policy.timeout(seconds=10.0)
    .policy.retry(max_attempts=3)
    .dispatch_action("heavy.execute")
    .build()
)
```

### 1.3 HTTP role check (defense in depth — 3 layers)

```
Layer 1: RpaPolicyMiddleware (HTTP role check)
        ↓
Layer 2: required_capability (DSL capability gate)
        ↓
Layer 3: audit_event (ClickHouse/Redis)
```

**Когда использовать:** для RCE-shaped operations (file delete, shell exec,
DB write, external API call).

### 1.4 AgentToolPolicy (default-deny)

```yaml
# src/backend/ai/policy/tool_policy.py
AgentToolPolicy:
  default: deny
  allow:
    - tool: search_web
      roles: [user, admin]
    - tool: send_email
      roles: [admin]
  audit:
    - tool: '*'
      emit: tool.invoked
```

---

## 2. Маскирование PII

### 2.1 Общий PII (regex-based, `pii_mask.py`)

```python
# src/backend/dsl/engine/processors/agent_dsl/pii_mask.py
from src.backend.dsl.engine.processors.agent_dsl.pii_mask import PIIMaskProcessor

p = PIIMaskProcessor(
    source_property="body.text",
    scope="banking",  # banking | hr | medical
    language="ru",
)
```

### 2.2 Agent-specific PII (recursive dict, `agent_pii_mask.py`)

```python
# src/backend/dsl/engine/processors/agent_dsl/agent_pii_mask.py
from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
    AgentDictPIIMaskProcessor,
)

# Для tool_call args / action params (dict structure)
p = AgentDictPIIMaskProcessor.for_tools(scope="banking")
# or
p = AgentDictPIIMaskProcessor.for_actions(scope="hr")
```

### 2.3 Unmask (round-trip)

```python
from src.backend.dsl.engine.processors.agent_dsl.pii_unmask import PIIUnmaskProcessor

p = PIIUnmaskProcessor(token_map_property="pii_token_map")
# Читает token_map из exchange и восстанавливает оригинал
```

### 2.4 Когда какой использовать

| Сценарий | Processor | Почему |
|----------|-----------|--------|
| Текст в body (string) | `PIIMaskProcessor` | regex + Presidio NER, flat string |
| Tool call args (dict) | `AgentDictPIIMaskProcessor.for_tools` | recursive walk, agent context |
| Action params (dict) | `AgentDictPIIMaskProcessor.for_actions` | recursive walk, different audit |
| Structured response | `PIIMaskProcessor` (post-processing) | single-shot, no recursion |

### 2.5 Presidio fallback

```python
# src/backend/core/security/pii_tokenizer.py
# Presidio если установлен; regex fallback иначе
provider = get_pii_tokenizer_provider()  # returns factory
tokenizer = provider()  # PresidioTokenizer | RegexTokenizer
```

---

## 3. Agent workflow (LangGraph + DSL)

### 3.1 LangGraph agent DSL

```python
# src/backend/dsl/engine/processors/agent_dsl/langgraph_agent.py
from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (
    LangGraphAgentProcessor,
)

p = LangGraphAgentProcessor(
    query="What is the INN for company X?",
    to="body.answer",
    thread_id="thread-123",
    max_iterations=10,
)
```

### 3.2 Multi-step agent workflow

```python
from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (
    LangGraphAgentProcessor,
)
from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
    AgentDictPIIMaskProcessor,
)

route = (
    RouteBuilder.from_("agent.osint", source="http:POST /api/v1/agent/run")
    # Step 1: Mask PII in incoming user query
    .add(AgentDictPIIMaskProcessor.for_tools(scope="banking"))
    # Step 2: Run LangGraph agent
    .add(LangGraphAgentProcessor(
        query="body.query",
        thread_id="body.thread_id",
        max_iterations=15,
        to="body.answer",
    ))
    # Step 3: Mask PII in agent's response
    .add(AgentDictPIIMaskProcessor.for_actions(scope="banking"))
    .build()
)
```

### 3.3 ReAct loop с tool calling

```python
# src/backend/services/ai/ai_graph.py (build_and_run_agent)
# Default: ReAct agent with tool dispatch
result = await build_and_run_agent(
    query="test",
    thread_id="t1",
    max_iterations=10,  # Safety: prevent infinite loops
)
```

### 3.4 Tool policy в workflow

```python
# src/backend/dsl/engine/processors/agent_dsl/ai_tool_dispatch.py
from src.backend.dsl.engine.processors.agent_dsl.ai_tool_dispatch import (
    AIToolDispatchProcessor,
)

p = AIToolDispatchProcessor(
    available_tool_ids=["search_web", "calculate"],
    tool_policy=tool_policy,  # AgentToolPolicy from §1.4
)
```

---

## 4. Версионирование и оптимизация промптов

### 4.1 PromptRegistry (YAML-based versioning)

```python
# src/backend/services/ai/prompt_registry.py
from src.backend.services.ai.prompt_registry import get_prompt_registry

registry = get_prompt_registry()

# Get specific version
prompt = await registry.get(
    name="osint_report",
    version="v2.3",
    label="production",
    variables={"company_name": "Acme Corp"},
)
```

### 4.2 DSL wrapper

```yaml
# В route definition
- prompt_get:
    name: osint_report
    version: v2.3
    to: body.prompt
- llm_call:
    model: minimax/MiniMax-Text-01
    prompt: body.prompt
    to: body.response
```

### 4.3 Jinja2 template rendering (для dynamic prompts)

```python
# src/backend/dsl/engine/processors/rpa/operations/templaterenderprocessor.py
from src.backend.dsl.engine.processors.rpa.operations.templaterenderprocessor import (
    TemplateRenderProcessor,
)

p = TemplateRenderProcessor(
    template_string="Hello {{ name }}, today is {{ date }}",
    variables={"name": "Alice", "date": "2026-06-25"},
    to="body.rendered",
)
```

### 4.4 Оптимизация промптов

| Стратегия | Описание | Когда использовать |
|-----------|----------|-------------------|
| **Token reduction** | Удалить filler words, повторы | Перед каждым production deploy |
| **Few-shot examples** | 3-5 примеров в system message | Для классификации, structured output |
| **Chain-of-thought** | "Let me think step by step..." | Math, logic, multi-step reasoning |
| **Prompt caching** | Cache system message (90% savings) | Длинные system prompts, identical across calls |
| **Structured output** | `instructor.from_litellm` + pydantic | Когда нужна typed response |

### 4.5 Prompt caching (savings ~90%)

```python
# src/backend/services/ai/prompt_cache.py
# Cache key: (model, system_message_hash)
# TTL: 1h default
# Use for: long system prompts that don't change between calls
```

---

## 5. Memory

### 5.1 Memory types

```python
# src/backend/services/ai/memory/langmem/
# Episodic: per-thread conversation history
# Semantic: facts about entities (user, project, etc.)
# Procedural: how-to knowledge
# RLM: large context storage + retrieval
```

### 5.2 Memory DSL

```python
# src/backend/dsl/engine/processors/agent_dsl/memory_recall.py
from src.backend.dsl.engine.processors.agent_dsl.memory_recall import (
    MemoryRecallProcessor,
)

p = MemoryRecallProcessor(
    query="user preferences",
    memory_type="semantic",
    top_k=5,
    to="body.recalled",
)
```

```python
# src/backend/dsl/engine/processors/agent_dsl/memory_store.py
from src.backend.dsl.engine.processors.agent_dsl.memory_store import (
    MemoryStoreProcessor,
)

p = MemoryStoreProcessor(
    content="User prefers concise responses",
    memory_type="semantic",
    thread_id="t1",
)
```

### 5.3 Когда использовать какой тип

| Тип | Когда использовать | Пример |
|------|-------------------|--------|
| **Episodic** | Conversation history, debugging | "What did user ask 3 turns ago?" |
| **Semantic** | Facts about users/projects | "What is user's company INN?" |
| **Procedural** | How-to knowledge | "How to format API response?" |
| **RLM** | Large documents (>10K tokens) | "Find clause in 100-page contract" |

### 5.4 RAG vs Memory

- **RAG** (RAG_GUIDE.md): document corpus, vector search
- **Memory** (this section): per-thread state, episodic/semantic facts

---

## 6. RLM toolkit

### 6.1 Что такое RLM

**RLM (Recursive Language Model)** — для работы с большими контекстами
(>10K токенов), где naive LLM call не помещается в context window.

### 6.2 Когда использовать RLM

- ✅ Документы > 10K токенов (договоры, спецификации, отчёты)
- ✅ Multi-step reasoning over large corpus
- ✅ Sandboxed REPL execution (Python, SQL)

### 6.3 RLM DSL

```python
# src/backend/dsl/engine/processors/ai_rlm.py
from src.backend.dsl.engine.processors.ai_rlm import AIRLMProcessor

p = AIRLMProcessor(
    query="Find all termination clauses in this contract",
    context_property="body.contract",
    max_iterations=10,
    max_tokens=4000,
    to="body.answer",
)
```

### 6.4 RLM vs direct LLM

| Сценарий | LLM direct | RLM |
|----------|------------|-----|
| < 4K tokens | ✅ preferred | ❌ overhead |
| 4K-10K tokens | ✅ OK | ✅ optional |
| 10K-100K tokens | ❌ overflow | ✅ required |
| > 100K tokens | ❌ impossible | ✅ with chunking |

### 6.5 RLM safety

```python
# src/backend/dsl/engine/processors/ai_rlm.py
RLMConfig:
  max_iterations: 10   # prevent infinite loops
  max_tokens: 4000      # per iteration
  sandbox_enabled: true # (deprecated — actual sandbox via core.ai.sandbox)
```

---

## 7. Выбор правильного паттерна

```
┌─────────────────────────────────────────────────────┐
│ У вас есть задача для AI-агента                      │
└─────────────────────────────────────────────────────┘
                        ↓
        ┌───────────────┴───────────────┐
        │ Это простой Q&A?              │
        │ (< 1 turn, no tools needed)   │
        └───────┬───────────────┬───────┘
               YES              NO
                ↓                ↓
        Direct LLM call    ┌────┴─────┐
        (ai/llmcall)       │ Multi-step│
                           │ reasoning?│
                           └────┬─────┘
                            YES │ NO
                                ↓  ↓
                            LangGraph  Multi-turn chat
                            (with       (memory)
                             tools)
```

### Decision matrix

| Задача | Pattern | Library |
|--------|---------|---------|
| Single Q&A | Direct LLM | minimax, openai, etc. |
| Multi-turn chat | Memory DSL | langmem |
| Tool calling | LangGraph DSL | langgraph |
| Document Q&A (>4K) | RAG | hybrid_rag |
| Document Q&A (>10K) | RLM | ai_rlm |
| Structured output | Instructor + pydantic | instructor |
| OSINT workflow | Pre-built route | osint_agent |
| Custom pipeline | DSL composition | route_builder |

---

## 8. Тестирование агентов

### 8.1 Unit tests (TDD)

```python
# tests/unit/dsl/engine/processors/agent_dsl/test_*.py
from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (
    LangGraphAgentProcessor,
)

@pytest.mark.asyncio
async def test_agent_uses_correct_tool():
    p = LangGraphAgentProcessor(query="test", to="body.answer")
    ex = MagicMock()
    ex.in_message = MagicMock()
    ex.in_message.body = {}
    
    with patch("src.backend.services.ai.ai_graph.build_and_run_agent",
               new=AsyncMock(return_value={"output": "answer"})):
        await p.process(ex, MagicMock())
    
    assert ex.in_message.body["answer"] == "answer"
```

### 8.2 Integration tests (real agents)

```python
@pytest.mark.integration
async def test_real_langgraph_agent():
    """Требует OPENAI_API_KEY или MiniMax key."""
    result = await build_and_run_agent(
        query="What is 2+2?",
        max_iterations=3,
    )
    assert "4" in result["output"]
```

### 8.3 Mock patterns

- ✅ Use `AsyncMock` for async library methods
- ✅ Use `async def mock_fn` for callable mocks
- ❌ Never use `MagicMock` for async methods (writes coroutine to body)

### 8.4 Runtime verification

Unit tests with mocks can pass for WRONG contracts. Always add
**runtime integration test** to catch:
- Coroutine written to body
- DI provider returning None
- Wrong API signature

```python
# Real test: actually call the processor without mocks
async def test_real_mask_reversible():
    from src.backend.core.security.pii_tokenizer import get_pii_tokenizer_provider
    provider = get_pii_tokenizer_provider()
    tokenizer = provider() if provider else None
    if tokenizer is None:
        pytest.skip("PIITokenizer not configured")
    result = await tokenizer.mask_reversible("test@example.com", language="ru")
    assert "[EMAIL_1]" in result["text"]
```

---

## D-rules (Agent Layer)

- **D156**: `agent_dsl/` directory has 17+ processors (per S170 M3)
- **D157**: `memory_recall.py` + `memory_store.py` are the canonical memory DSL
- **D158**: `ai/policy/tool_policy.py` is the canonical AgentToolPolicy
- **D161**: `services/ai/ai_graph.py` (build_and_run_agent) is the canonical LangGraph entry
- **D162**: RLMConfig max_iterations=10, max_tokens=4000 are safety defaults

## See also

- `docs/ai/BEST_PRACTICES.md` — общий overview (S170 M3)
- `src/backend/dsl/engine/processors/agent_dsl/` — все agent processors
- `src/backend/services/ai/` — service layer (ai_graph, memory, prompts, RLM)
- `src/backend/core/security/` — auth + PII + capability gate
