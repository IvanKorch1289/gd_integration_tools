"""Eventing — CloudEvents envelope, Schema Registry, Outbox, Inbox.

Фазы C4 (CloudEvents + Schema Registry) и C5 (Outbox+Inbox).
"""

from src.backend.infrastructure.eventing.cloudevents import (
    CloudEvent,
    envelope,
    parse_envelope,
)
from src.backend.infrastructure.eventing.inbox import Inbox
from src.backend.infrastructure.eventing.outbox import OutboxEvent, OutboxPublisher
from src.backend.infrastructure.eventing.schema_registry import SchemaRegistry

__all__ = (
    "CloudEvent",
    "envelope",
    "parse_envelope",
    "SchemaRegistry",
    "OutboxEvent",
    "OutboxPublisher",
    "Inbox",
)
