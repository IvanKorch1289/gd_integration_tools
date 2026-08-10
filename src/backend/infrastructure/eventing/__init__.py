"""Eventing — CloudEvents envelope, Schema Registry, Outbox, Inbox.

Фазы C4 (CloudEvents + Schema Registry) и C5 (Outbox+Inbox).
"""

from src.backend.infrastructure.eventing.cloudevents import (
    CloudEvent,
    envelope,
    parse_envelope,
)
from src.backend.infrastructure.eventing.inbox import Inbox  # noqa: F401 — re-export
from src.backend.infrastructure.eventing.schema_registry import SchemaRegistry  # noqa: F401 — re-export

__all__ = (
    "CloudEvent",
    "Inbox",
    "SchemaRegistry",
    "envelope",
    "parse_envelope",
)
