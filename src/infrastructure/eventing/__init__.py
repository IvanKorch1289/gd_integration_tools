"""Eventing — CloudEvents envelope, Schema Registry, Outbox, Inbox.

Фазы C4 (CloudEvents + Schema Registry) и C5 (Outbox+Inbox).
"""

from app.infrastructure.eventing.cloudevents import CloudEvent, envelope, parse_envelope
from app.infrastructure.eventing.inbox import Inbox
from app.infrastructure.eventing.outbox import OutboxEvent, OutboxPublisher
from app.infrastructure.eventing.schema_registry import SchemaRegistry

__all__ = (
    "CloudEvent",
    "envelope",
    "parse_envelope",
    "SchemaRegistry",
    "OutboxEvent",
    "OutboxPublisher",
    "Inbox",
)
