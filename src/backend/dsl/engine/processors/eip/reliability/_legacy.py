"""EIP reliability patterns: Redelivery, Expiration, Correlation ID, Return Address (S56 W3).

Apache Camel EIP catalog (reliability / routing-metadata):

* :class:`RedeliveryPolicyProcessor` — Redelivery: https://camel.apache.org/components/latest/eips/redelivery.html
  Retry policy для failed message delivery с exponential backoff и DLQ-routing
  после N attempts.

* :class:`MessageExpirationProcessor` — Message Expiration: https://camel.apache.org/components/latest/eips/message-expiration.html
  TTL на message (PEX — per-message expiration). Expired messages drop
  с optional on_expired_action.

* :class:`CorrelationIdentifierProcessor` — Correlation Identifier: https://camel.apache.org/components/latest/eips/correlation-identifier.html
  Управление ``correlation_id`` header: explicit set, propagate from upstream
  message, или generate через factory (UUID4 / ULID / snowflake).

* :class:`ReturnAddressProcessor` — Return Address: https://camel.apache.org/components/latest/eips/return-address.html
  Capture original ``reply_to`` endpoint при request-reply pattern,
  attach к headers для downstream callback routing.

Все процессоры — :class:`BaseProcessor` для inline-использования в DSL.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = (
    "CorrelationIdentifierProcessor",
    "MessageExpirationProcessor",
    "RedeliveryPolicyProcessor",
    "ReturnAddressProcessor",
)

_log = get_logger(__name__)


# Header constants — стандартные имена (JMS-style / Camel conventions).
HEADER_CORRELATION_ID = "correlation_id"
HEADER_MESSAGE_ID = "message_id"
HEADER_EXPIRATION = "expiration"  # millis-since-epoch (JMS-style) или ISO 8601
HEADER_REDELIVERED = "redelivered"
HEADER_REDELIVERY_COUNT = "redelivery_count"
HEADER_RETURN_ADDRESS = "return_address"  # reply-to endpoint URI


# Type aliases
IdFactory = Callable[[], str]
ExpirationResolver = Callable[
    [Exchange[Any]], datetime | None | Awaitable[datetime | None]
]
RedeliveryAttempt = tuple[int, float]  # (attempt_number, delay_seconds)


