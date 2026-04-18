"""DSL Macros — pre-built patterns для типовых сценариев.

Упрощают создание pipeline для распространённых use-case:
- ETL pipeline
- Webhook relay
- AI Q&A pipeline
- CRUD с аудитом
- Retry с dead-letter
"""

from __future__ import annotations

from typing import Any, Callable

from app.dsl.builder import RouteBuilder
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.pipeline import Pipeline
from app.dsl.engine.processors import (
    BaseProcessor,
    DeadLetterProcessor,
    DispatchActionProcessor,
    LogProcessor,
    RetryProcessor,
    TryCatchProcessor,
    ValidateProcessor,
)

__all__ = (
    "etl_pipeline",
    "webhook_relay",
    "ai_qa_pipeline",
    "safe_action",
    "crud_with_audit",
)


def etl_pipeline(
    route_id: str,
    source: str,
    extract_action: str,
    transform_fn: Callable[[Exchange[Any], Any], None],
    load_action: str,
    *,
    retry_attempts: int = 3,
    description: str = "",
) -> Pipeline:
    """ETL pipeline: extract → transform → load с retry."""
    return (
        RouteBuilder.from_(route_id, source=source, description=description or f"ETL: {route_id}")
        .retry(
            processors=[DispatchActionProcessor(action=extract_action)],
            max_attempts=retry_attempts,
        )
        .process_fn(transform_fn)
        .dispatch_action(load_action)
        .log(f"ETL {route_id} complete")
        .build()
    )


def webhook_relay(
    route_id: str,
    source: str,
    targets: list[str],
    *,
    parallel: bool = True,
    description: str = "",
) -> Pipeline:
    """Webhook relay: 1 вход → N выходов (parallel или sequential)."""
    return (
        RouteBuilder.from_(route_id, source=source, description=description or f"Relay: {route_id}")
        .recipient_list(lambda ex: targets, parallel=parallel)
        .log(f"Relayed to {len(targets)} targets")
        .build()
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
    description: str = "",
) -> Pipeline:
    """AI Q&A pipeline: validate → RAG search → compose prompt → PII mask → LLM → parse."""
    builder = (
        RouteBuilder.from_(route_id, source=source, description=description or f"AI Q&A: {route_id}")
        .rag_search(query_field=query_field, top_k=top_k)
        .compose_prompt(
            template="Контекст:\n{context}\n\nВопрос: {" + query_field + "}\nОтвет:",
            context_property="vector_results",
        )
        .token_budget(max_tokens=4096)
        .sanitize_pii()
        .call_llm(provider=provider, model=model)
        .restore_pii()
    )
    if response_schema:
        builder = builder.parse_llm_output(schema=response_schema)

    return builder.build()


def safe_action(
    route_id: str,
    action: str,
    *,
    source: str = "",
    max_retries: int = 3,
    dlq_action: str | None = None,
    description: str = "",
) -> Pipeline:
    """Action с retry и optional dead-letter queue."""
    builder = RouteBuilder.from_(
        route_id, source=source or f"internal:{route_id}",
        description=description or f"Safe action: {action}",
    )

    action_processor = DispatchActionProcessor(action=action)

    if dlq_action:
        builder = builder.do_try(
            try_processors=[
                RetryProcessor(
                    processors=[action_processor],
                    max_attempts=max_retries,
                ),
            ],
            catch_processors=[
                DeadLetterProcessor(
                    dlq_action=dlq_action,
                    max_retries=0,
                ),
            ],
        )
    else:
        builder = builder.retry(
            processors=[action_processor],
            max_attempts=max_retries,
        )

    return builder.build()


def crud_with_audit(
    route_id_prefix: str,
    create_action: str,
    update_action: str,
    delete_action: str,
    *,
    event_channel: str = "events.orders",
    source_prefix: str = "internal",
) -> list[Pipeline]:
    """CRUD pipelines с event publishing для аудита."""
    pipelines = []

    for op, action in [("create", create_action), ("update", update_action), ("delete", delete_action)]:
        pipeline = (
            RouteBuilder.from_(
                f"{route_id_prefix}.{op}",
                source=f"{source_prefix}:{route_id_prefix}.{op}",
            )
            .dispatch_action(action)
            .publish_event(event_channel)
            .log(f"{route_id_prefix}.{op} completed")
            .build()
        )
        pipelines.append(pipeline)

    return pipelines
