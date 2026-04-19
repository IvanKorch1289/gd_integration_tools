# AI Integration Guide

Полноценная интеграция LLM, RAG, PII-маскирования и safety guardrails в DSL-маршруты.

## Архитектура AI pipeline

```
Input → PII mask → RAG search → Prompt compose → Token budget →
LLM call → Parse → PII restore → Guardrails → Output
```

Каждый шаг — отдельный DSL-процессор, можно выбирать набор по задаче.

## Базовый LLM вызов

```python
route = (
    RouteBuilder.from_("ai.simple_qa", source="internal:ai")
    .compose_prompt(template="Answer concisely: {question}")
    .call_llm(provider="perplexity", model="sonar-pro")
    .build()
)
```

## RAG Q&A pipeline

Полный цикл с векторным поиском, PII маскированием и парсингом:

```python
from app.dsl.macros import ai_qa_pipeline

route = ai_qa_pipeline(
    route_id="ai.support_qa",
    query_field="question",
    top_k=5,                     # RAG top-k
    provider="anthropic",
    model="claude-3-sonnet",
    response_schema=SupportAnswer,  # Pydantic модель
)
```

Эквивалентно:

```python
route = (
    RouteBuilder.from_("ai.support_qa", source="internal:ai")
    .timeout(
        processors=[DispatchActionProcessor(action="rag.search")],
        seconds=15.0,
    )
    .rag_search(query_field="question", top_k=5)
    .compose_prompt(
        template="Context:\n{context}\n\nQuestion: {question}\nAnswer:",
    )
    .token_budget(max_tokens=4096)  # tiktoken
    .sanitize_pii()                 # маскировка перед LLM
    .call_llm(provider="anthropic", model="claude-3-sonnet")
    .restore_pii()                  # восстановление после LLM
    .parse_llm_output(schema=SupportAnswer)
    .build()
)
```

## Multi-provider fallback

Если primary провайдер недоступен — пробует следующий:

```python
.call_llm_with_fallback(
    providers=["perplexity", "huggingface", "open_webui"],
    model="default",
)
```

## Кеширование LLM ответов

Redis-backed cache — экономия на повторных запросах:

```python
route = (
    RouteBuilder.from_("ai.cached_qa", source="internal:ai")
    .cache(
        key_fn=lambda ex: str(ex.in_message.body.get("question", ""))[:200],
        ttl=3600,  # 1 час
    )
    # Если в кеше — остальное пропускается (property cached=True)
    .compose_prompt(template="{question}")
    .call_llm(provider="perplexity")
    .cache_write(
        key_fn=lambda ex: str(ex.in_message.body.get("question", ""))[:200],
        ttl=3600,
    )
    .build()
)
```

## PII-маскировка

Автоматически заменяет телефоны, email, номера карт, СНИЛС на placeholder:

```python
.sanitize_pii()  # перед LLM — данные не утекут
# ... LLM обработка ...
.restore_pii()   # восстановление оригиналов в ответе
```

Sanitizer находит:
- Email
- Телефоны (RU, international)
- Номера карт
- Паспорт, СНИЛС, ИНН
- API keys (по шаблонам)

## Safety Guardrails

Проверка LLM output перед возвращением пользователю:

```python
.call_llm(provider="perplexity")
.guardrails(
    max_length=5000,                # обрезать слишком длинные
    blocked_patterns=[               # блоклист regex
        r"\bpassword\b",
        r"\bsecret\b",
        r"\bapi[_-]key\b",
    ],
    required_fields=["answer", "sources"],  # для dict body
)
```

При нарушении — `exchange.fail("Guardrail: ...")`.

## Semantic Search + Routing

Роутинг запроса на специализированный pipeline через RAG:

```python
# 1. Векторный поиск интента
.rag_search(query_field="question", top_k=1, namespace="intents")
# 2. По результату выбираем маршрут
.switch(
    field="intent",
    cases={
        "order_status": [PipelineRefProcessor("route.order_status")],
        "complaint": [PipelineRefProcessor("route.support")],
        "billing": [PipelineRefProcessor("route.billing")],
    },
    default=[PipelineRefProcessor("route.general_qa")],
)
```

## Token Budget (tiktoken)

Точный подсчёт токенов для GPT-моделей, fallback на символы:

```python
.token_budget(max_tokens=4096)
# Обрежет текст до лимита с суффиксом "...[truncated]"
```

## Cost Tracking (рекомендация)

Через `slo_tracker` и `structlog` — логируйте токены/стоимость:

```python
import structlog
logger = structlog.get_logger()

async def track_cost(exchange, context):
    tokens = exchange.properties.get("llm_tokens_used", 0)
    provider = exchange.properties.get("llm_provider_used", "unknown")
    logger.info("llm_call", tokens=tokens, provider=provider,
                estimated_cost_usd=tokens * 0.00002)

route = (
    RouteBuilder.from_(...)
    .call_llm(provider="perplexity")
    .process_fn(track_cost)
    .build()
)
```

## Безопасность AI

1. **Всегда маскируй PII** перед отправкой в LLM — `.sanitize_pii()`
2. **Ставь timeout** на LLM вызовы — `.timeout(seconds=30)`
3. **Включай guardrails** для production — `.guardrails(blocked_patterns=[...])`
4. **Используй fallback chain** для надёжности — `.call_llm_with_fallback()`
5. **Кешируй результаты** для экономии — `.cache() + .cache_write()`
6. **Не логируй промпты с PII** в plaintext — всегда через `.sanitize_pii()`

## Провайдеры

Текущие (`app.services.ai_agent`):
- **Perplexity** (web-grounded search)
- **HuggingFace** (OSS модели)
- **Open WebUI** (локальные модели)

Конфигурация через `.env`:
```bash
AI_PERPLEXITY_API_KEY=...
AI_HUGGINGFACE_API_KEY=...
AI_FALLBACK_CHAIN=perplexity,huggingface,open_webui
```
