# Политика выбора AI-фреймворка (Sprint 36)

> Когда использовать LangGraph, PydanticAI или AIAgentService.

---

## LangGraph

**Когда использовать:**
- Multi-step stateful агенты с необходимостью checkpoint / replay.
- Supervisor pattern (handoff между агентами).
- Сложные циклы с человеком (HITL) — pause/resume/retry.
- Нужна persistence в PostgreSQL (`LangGraphPostgresSaver`).

**Когда НЕ использовать:**
- Простые one-shot вызовы (избыточная сложность).
- Нет необходимости в state machine.

**Примеры в проекте:**
- `services/ai/multi_agent/supervisor.py`
- `services/ai/ai_graph.py` (ReAct с tool-use)

---

## PydanticAI

**Когда использовать:**
- Structured output — ответ должен проходить валидацию через Pydantic.
- Type-safe responses (generic `Agent[ResultT]`).
- Retry с exponential backoff (tenacity) и fallback-моделями.
- Интеграция с LiteLLM Gateway (`LiteLLMModel` adapter).

**Когда НЕ использовать:**
- Нужен сложный state graph (LangGraph лучше).
- Нет требования к strict schema validation.

**Примеры в проекте:**
- `services/ai/agents_pydantic/base.py`
- `services/ai/agents_pydantic/examples/rag_answering.py`

---

## AIAgentService (`services/ai/ai_agent.py`)

**Когда использовать:**
- Простые one-shot LLM вызовы без агентной логики.
- Search, parse, summarize — задачи без state.
- PII sanitize/restore, RAG augmentation, policy gate — pipeline-обработка.

**Когда НЕ использовать:**
- Нужен multi-step reasoning (используй LangGraph).
- Нужен strict output validation (используй PydanticAI).

**Будущее:**
`AIGateway` (`core/ai/gateway.py`) в режиме `enforce=True` должен
заменить `AIAgentService` для всех LLM-вызовов (ADR-NEW-19).
До миграции — используй `AIAgentService` только для legacy pipeline.

---

## Summary matrix

| Критерий | LangGraph | PydanticAI | AIAgentService |
|----------|-----------|------------|----------------|
| Stateful | Да | Нет | Нет |
| Checkpoint / replay | Да | Нет | Нет |
| Structured output | Частично | Да (strict) | Нет |
| Multi-agent | Да (supervisor) | Нет | Нет |
| HITL | Да | Нет | Нет |
| One-shot | Избыточно | Ок | Оптимально |
| Fallback chain | Вручную | Встроено | Вручную |

---

## Решение

1. Новый feature → начинай с **PydanticAI** (type-safe, тестируемо).
2. Нужен state / HITL / multi-agent → **LangGraph**.
3. Legacy one-shot pipeline → **AIAgentService** (до миграции на AIGateway).
