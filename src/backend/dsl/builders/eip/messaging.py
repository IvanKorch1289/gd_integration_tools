"""Messaging EIP-методы: validate_schema / reply_to / exactly_once /
durable_fanout / purge_channel / sample / schema_validate / composed_message.

Sprint 60 W4 — split из eip.py (1354 LOC).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from src.backend.dsl.builders.eip._base import EIPMixinBase
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import BaseProcessor
from src.backend.dsl.engine.processors.streaming import (
    ChannelPurgerProcessor,
    DurableSubscriberProcessor,
    ExactlyOnceProcessor,
    ReplyToProcessor,
    SamplingProcessor,
    SchemaRegistryValidator,
)

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder

__all__ = ("MessagingEIPsMixin",)


class MessagingEIPsMixin(EIPMixinBase):
    """Schema-registry / streaming messaging EIPs."""

    def validate_schema(
        self, subject: str, *, schema_loader: Any = None
    ) -> "RouteBuilder":
        """Валидация по схеме из реестра (JSON Schema / Avro / Protobuf)."""
        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                SchemaRegistryValidator(subject=subject, schema_loader=schema_loader)
            ),
        )

    def reply_to(
        self,
        broker: Any,
        *,
        reply_to_header: str = "reply-to",
        correlation_header: str = "x-correlation-id",
    ) -> "RouteBuilder":
        """Return Address: публикует ответ в очередь из reply-to заголовка."""
        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                ReplyToProcessor(
                    broker=broker,
                    reply_to_header=reply_to_header,
                    correlation_header=correlation_header,
                )
            ),
        )

    def exactly_once(
        self,
        storage: Any,
        *,
        id_header: str = "x-message-id",
        ttl_seconds: int = 86_400,
        namespace: str = "exactly-once",
    ) -> "RouteBuilder":
        """Exactly-once: dedup через storage по message-id."""
        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                ExactlyOnceProcessor(
                    storage=storage,
                    id_header=id_header,
                    ttl_seconds=ttl_seconds,
                    namespace=namespace,
                )
            ),
        )

    def durable_fanout(self, broker: Any, subscribers: list[str]) -> "RouteBuilder":
        """Durable Subscriber: fan-out к persistent-подписчикам."""
        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                DurableSubscriberProcessor(broker=broker, subscribers=subscribers)
            ),
        )

    def purge_channel(
        self, broker: Any, channel: str, *, dry_run: bool = True
    ) -> "RouteBuilder":
        """Очистка очереди/стрима (admin-операция)."""
        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                ChannelPurgerProcessor(broker=broker, channel=channel, dry_run=dry_run)
            ),
        )

    def sample(self, probability: float = 0.1) -> "RouteBuilder":
        """Вероятностный сэмплинг (A/B, canary, debug-sampling)."""
        return cast(
            "RouteBuilder",
            self._add(SamplingProcessor(probability=probability)),  # type: ignore[attr-defined]
        )

    def schema_validate(self, schema: dict[str, Any]) -> "RouteBuilder":
        """Валидация body по JSON Schema (Draft 2020-12)."""
        from src.backend.dsl.engine.processors.generic import SchemaValidateProcessor

        return cast(
            "RouteBuilder",
            self._add(SchemaValidateProcessor(schema=schema)),  # type: ignore[attr-defined]
        )

    def composed_message(
        self,
        splitter: Callable[[Exchange[Any]], Any],
        processors: list[BaseProcessor],
        aggregator: Callable[[list[Exchange[Any]]], Any],
    ) -> "RouteBuilder":
        """Composed Message Processor: split → per-part → aggregate."""
        return cast(
            "RouteBuilder",
            self._add_lazy(  # type: ignore[attr-defined]
                "src.backend.dsl.engine.processors.composed_message",
                "ComposedMessageProcessor",
                splitter=splitter,
                processors=processors,
                aggregator=aggregator,
            ),
        )
