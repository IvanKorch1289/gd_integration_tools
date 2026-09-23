"""EIP reliability subpackage: shared header constants и type aliases.

S56 W3 S175 Phase 1: header constants + type aliases для reliability-
процессоров (Redelivery, Expiration, Correlation Identifier, Return Address).
S175 Phase 2: каждый Processor-класс вынесен в отдельный модуль
(``correlation_identifier``, ``message_expiration``, ``redelivery_policy``,
``return_address``); этот модуль содержит только то, что между ними общее.

Apache Camel EIP catalog (reliability / routing-metadata):

* Redelivery: https://camel.apache.org/components/latest/eips/redelivery.html
* Message Expiration: https://camel.apache.org/components/latest/eips/message-expiration.html
* Correlation Identifier: https://camel.apache.org/components/latest/eips/correlation-identifier.html
* Return Address: https://camel.apache.org/components/latest/eips/return-address.html

Public API:

* Header constants (JMS-style / Camel conventions):
    - ``HEADER_CORRELATION_ID``
    - ``HEADER_MESSAGE_ID``
    - ``HEADER_EXPIRATION``
    - ``HEADER_REDELIVERED``
    - ``HEADER_REDELIVERY_COUNT``
    - ``HEADER_RETURN_ADDRESS``

* Type aliases:
    - ``IdFactory``
    - ``ExpirationResolver``
    - ``RedeliveryAttempt``

W3 P0-4 Phase 2A (MINIMAX cycle 152): файл переименован из ``_legacy.py``
в ``common.py`` — старое имя misleading (это не legacy, это shared module
для 4 reliability-процессоров). См. ADR-0307.

Migration для downstream:

    from src.backend.dsl.engine.processors.eip.reliability import HEADER_CORRELATION_ID
    # ^ остаётся рабочим через __init__.py re-export.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    # Header constants
    "HEADER_CORRELATION_ID",
    "HEADER_EXPIRATION",
    "HEADER_MESSAGE_ID",
    "HEADER_REDELIVERED",
    "HEADER_REDELIVERY_COUNT",
    "HEADER_RETURN_ADDRESS",
    # Type aliases
    "ExpirationResolver",
    "IdFactory",
    "RedeliveryAttempt",
)

_log = get_logger(__name__)


# Header constants — стандартные имена (JMS-style / Camel conventions).
HEADER_CORRELATION_ID = "correlation_id"
HEADER_MESSAGE_ID = "message_id"
HEADER_EXPIRATION = "expiration"  # millis-since-epoch (JMS-style) или ISO 8601
HEADER_REDELIVERED = "redelivered"
HEADER_REDELIVERY_COUNT = "redelivery_count"
HEADER_RETURN_ADDRESS = "return_address"  # reply-to endpoint URI


# Type aliases.
IdFactory = Callable[[], str]
ExpirationResolver = Callable[
    [Exchange[Any]], datetime | Awaitable[datetime | None] | None
]
RedeliveryAttempt = tuple[int, float]  # (attempt_number, delay_seconds)