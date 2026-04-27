# DSL Cookbook

## Basic Pipeline

```python
from src.dsl.builder import RouteBuilder

route = (
    RouteBuilder.from_("orders.process", source="http:POST:/orders")
    .validate(OrderSchema)
    .dispatch_action("orders.create")
    .log("Order created")
    .build()
)
```

## ETL Pipeline

```python
route = (
    RouteBuilder.from_("etl.import", source="cron:0 */6 * * *")
    .dispatch_action("external.fetch_data")
    .transform(lambda ex, ctx: ex.in_message.set_body(
        transform_data(ex.in_message.body)
    ))
    .dispatch_action("analytics.insert_batch")
    .log("ETL complete")
    .build()
)
```

## Webhook Relay (1 вход → N выходов)

```python
route = (
    RouteBuilder.from_("webhook.relay", source="http:POST:/webhook")
    .recipient_list(
        lambda ex: ["service_a", "service_b", "service_c"],
        parallel=True,
    )
    .build()
)
```

## Saga с компенсациями

```python
route = (
    RouteBuilder.from_("orders.saga", source="internal:orders")
    .saga([
        SagaStep(
            action="orders.reserve",
            compensation="orders.cancel_reservation",
        ),
        SagaStep(
            action="payments.charge",
            compensation="payments.refund",
        ),
        SagaStep(action="notifications.send"),
    ])
    .build()
)
```

## Content-Based Routing

```python
route = (
    RouteBuilder.from_("router.by_type", source="queue:incoming")
    .choice(
        when=[
            (lambda ex: ex.in_message.body.get("type") == "A", [
                DispatchActionProcessor(action="handler.type_a"),
            ]),
            (lambda ex: ex.in_message.body.get("type") == "B", [
                DispatchActionProcessor(action="handler.type_b"),
            ]),
        ],
        otherwise=[LogProcessor(message="Unknown type")],
    )
    .build()
)
```

## Retry с Exponential Backoff

```python
route = (
    RouteBuilder.from_("external.call", source="internal:external")
    .retry(
        processors=[DispatchActionProcessor(action="external.api")],
        max_attempts=5,
        backoff_base=2.0,
        backoff_max=60.0,
    )
    .build()
)
```

## AI Pipeline (RAG + LLM)

```python
route = (
    RouteBuilder.from_("ai.answer", source="internal:ai")
    .validate(QuestionSchema)
    .rag_search(query_field="question", top_k=5)
    .compose_prompt(
        template="Контекст:\n{context}\n\nВопрос: {question}\nОтвет:",
        context_property="vector_results",
    )
    .token_budget(max_tokens=4096)
    .sanitize_pii()
    .call_llm(provider="openai", model="gpt-4o")
    .restore_pii()
    .parse_llm_output(schema=AnswerSchema)
    .build()
)
```

## Pipeline Composition

```python
sanitize = (
    RouteBuilder.from_("module.sanitize", source="internal:module")
    .sanitize_pii()
    .log("PII masked")
    .build()
)

main = (
    RouteBuilder.from_("orders.full", source="http:POST:/orders")
    .include(sanitize)
    .dispatch_action("orders.create")
    .publish_event("events.orders")
    .build()
)
```

## Feature Flag

```python
route = (
    RouteBuilder.from_("orders.new_flow", source="internal:orders")
    .feature_flag("orders.new_flow")
    .dispatch_action("orders.process_v2")
    .build()
)
```
