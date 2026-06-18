# AI Platform

Унифицированный AI-шлюз: LLM, RAG, RLM, агенты, memory, guardrails.

## Архитектура

```
src/backend/core/ai/
├── gateway.py              # 9-step pipeline orchestrator
├── pydantic_ai_client.py   # PydanticAI client
├── multi_agent.py          # LangGraph agent coordinator
├── sandbox.py              # CodeSandbox Protocol (E2B integration)
├── skill_registry.py       # Skill export to MCP/LangGraph/OpenAI
├── agent_registry.py       # Agent hot-reload
├── agent_spec.py           # Agent spec (Pydantic)
├── policy/                 # AI policy enforcement
├── guardrails/             # Nemo Guardrails integration
├── memory_profile.py       # Memory tier config
├── fs_facade.py            # AI FS safety facade
└── workspace_manager.py    # AI workspace isolation

src/backend/services/ai/gateway/
├── client.py               # LiteLLMGateway
├── exceptions.py
└── callbacks.py            # Langfuse v3 callbacks
```

## AIGateway Pipeline (9 steps)

1. Resolve policy
2. Capability check
3. Input sanitization (Presidio)
4. PII detection
5. Prompt render
6. LLM invoke
7. Output guards
8. PII tokenization
9. Audit emit

## DSL Methods

| Метод | Описание |
|---|---|
| `route.invoke_llm()` | Single LLM call |
| `route.invoke_agent()` | LangGraph agent |
| `route.rag_query()` | RAG retrieval |
| `route.to_cache()` | AI response cache (S165 W1) |

## Sandbox (S166 W2)

```python
from src.backend.core.ai.gateway import AIGateway
from src.backend.infrastructure.ai.e2b_sandbox import E2BSandbox

gateway = AIGateway()
gateway.attach_sandbox(E2BSandbox(api_key=...))
result = await gateway.run_agent_code("print('hello')", timeout_seconds=30.0)
```

Default-OFF: без attached sandbox `run_agent_code()` raises RuntimeError
(per V15 R-V15-4 — no in-process code execution).

## Guards (Rule 10)

- Nemo Guardrails (in deps, integrated)
- OPA/Rego for tool policy — **deferred to S166 W5+**
- Tool whitelist/blacklist via `ToolsSpec` Pydantic model

## Storage

- `StorageFacade` (S164 W37) — file/blob storage abstraction
- `UnifiedCacheFacade` (S165 W1) — cache with TTL+tag invalidation

## См. также

- [DSL](../dsl/index.md)
- [ARCHITECTURE](../ARCHITECTURE.md)