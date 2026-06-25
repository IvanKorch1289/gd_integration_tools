"""DSL processor ``infra_kafka_produce`` (Sprint 170 M2 Phase 3).

Kafka message production через facade::

    - infra_kafka_produce:
        topic: orders
        value:
          order_id: 1
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


@processor(
    "infra_kafka_produce",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "value": {},
            "key": {"type": "string"},
        },
        "required": ["topic", "value"],
    },
    capabilities=("queue.produce.kafka",),
    meta={"tier": 1, "category": "infra"},
)
class InfraKafkaProduceProcessor(BaseProcessor):
    def __init__(self, topic: str, value: Any, key: str | None = None) -> None:
        super().__init__(name=f"infra_kafka_produce:{topic}")
        self.topic = topic
        self.value = value
        self.key = key

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.di.providers.infrastructure_facade import (
            get_kafka_producer_class,
        )
        producer = get_kafka_producer_class()(context)
        await producer.send_and_wait(self.topic, value=self.value, key=self.key)
