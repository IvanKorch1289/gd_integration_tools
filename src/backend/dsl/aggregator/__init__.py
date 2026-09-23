"""EIP Aggregator — completion-based batching (Wave 4 P4.19).

Реализация Camel EIP Aggregator pattern:
- correlation key (группировка messages в batch).
- completion predicate (size / timeout / predicate).
- completion_strategy (single_result / list / sum / merge / custom).
- timeout-based flush (если batch не заполнился за timeout).

Use cases:
- Order aggregation (collect orders → place batch every N orders или 30s).
- Audit log batching (accumulate до 100 events → flush).
- Sensor readings (group by sensor_id → max value every 5 sec).

Использование::

    from src.backend.dsl.aggregator import (  # noqa: F401 — re-export
        AggregatorConfig, CompletionStrategy, Message, aggregate,
    )

    config = AggregatorConfig(
        correlation_key=lambda msg: msg.headers["customer_id"],
        completion_size=10,
        completion_timeout=30.0,
        completion_strategy=CompletionStrategy.LIST,
    )

    result = aggregate(incoming_messages, config=config)
    for batch in result.batches:
        process_batch(batch)  # list of Message
"""

from __future__ import annotations

from src.backend.dsl.aggregator.aggregator import (  # noqa: F401 — re-export
    AggregatedBatch,
    AggregatorConfig,
    CompletionStrategy,
    Message,
    aggregate,
    aggregate_stream,
)

__all__ = (
    "AggregatedBatch",
    "AggregatorConfig",
    "CompletionStrategy",
    "Message",
    "aggregate",
    "aggregate_stream",
)
