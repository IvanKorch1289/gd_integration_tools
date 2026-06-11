from __future__ import annotations
"""S68 W1 - ai_qa_pipeline blueprint extracted from macros.py.

AI Q&A pipeline (RAG-style retrieval + LLM answer).
"""

from collections.abc import Callable
from typing import Any

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors import (
    DeadLetterProcessor,
    DispatchActionProcessor,
    LogProcessor,
    RetryProcessor,
)

def ai_qa_pipeline(
    route_id: str,
    source: str = "internal:ai",
    *,
    query_field: str = "question",
    top_k: int = 5,
    provider: str | None = None,
    model: str | None = None,
    response_schema: type | None = None,
    max_tokens: int = 4096,
    description: str = "",
) -> Pipeline:
    """AI Q&A pipeline: RAG → prompt → PII mask → LLM → unmask → parse.

    Полный цикл обработки вопроса с использованием RAG,
    PII-маскировки и ограничения по токенам.

    Args:
        route_id: Уникальный идентификатор маршрута.
        source: Источник (обычно "internal:ai").
        query_field: Поле с вопросом в body.
        top_k: Количество результатов RAG-поиска.
        provider: LLM провайдер (openai, anthropic, ...).
        model: Конкретная модель.
        response_schema: Pydantic-модель для парсинга ответа.
        max_tokens: Максимум токенов в промпте.
        description: Описание маршрута.

    Returns:
        Pipeline: Готовый AI Q&A pipeline.

    Example::

        pipeline = ai_qa_pipeline(
            route_id="ai.support",
            query_field="question",
            top_k=10,
            provider="anthropic",
            response_schema=SupportAnswerSchema,
        )
    """
    builder = (
        RouteBuilder.from_(
            route_id, source=source, description=description or f"AI Q&A: {route_id}"
        )
        .timeout(
            processors=[DispatchActionProcessor(action="rag.search")], seconds=15.0
        )
        .rag_search(query_field=query_field, top_k=top_k)
        .compose_prompt(
            template="Контекст:\n{context}\n\nВопрос: {" + query_field + "}\nОтвет:",
            context_property="vector_results",
        )
        .token_budget(max_tokens=max_tokens)
        .sanitize_pii()
        .call_llm(provider=provider, model=model)
        .restore_pii()
    )
    if response_schema:
        builder = builder.parse_llm_output(schema=response_schema)

    return builder.build()
