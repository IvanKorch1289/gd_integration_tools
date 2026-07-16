"""S175: eip/reliability subpackage — split 442 LOC god-file.

Phase 2 done: все 4 класса вынесены в отдельные файлы.

Modules:
- :mod:`correlation_identifier` — :class:`CorrelationIdentifierProcessor`
- :mod:`message_expiration` — :class:`MessageExpirationProcessor`
- :mod:`redelivery_policy` — :class:`RedeliveryPolicyProcessor`
- :mod:`return_address` — :class:`ReturnAddressProcessor`
- :mod:`_legacy` — backward-compat constants/types (S175 Phase 1)

Public API:
- Header constants: ``HEADER_CORRELATION_ID``, ``HEADER_MESSAGE_ID``,
  ``HEADER_EXPIRATION``, ``HEADER_REDELIVERED``, ``HEADER_REDELIVERY_COUNT``,
  ``HEADER_RETURN_ADDRESS``
- Type aliases: ``IdFactory``, ``ExpirationResolver``, ``RedeliveryAttempt``
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.eip.reliability._legacy import (
    HEADER_CORRELATION_ID,
    HEADER_EXPIRATION,
    HEADER_MESSAGE_ID,
    HEADER_REDELIVERED,
    HEADER_REDELIVERY_COUNT,
    HEADER_RETURN_ADDRESS,
    ExpirationResolver,
    IdFactory,
    RedeliveryAttempt,
)
from src.backend.dsl.engine.processors.eip.reliability.correlation_identifier import (
    CorrelationIdentifierProcessor,
)
from src.backend.dsl.engine.processors.eip.reliability.message_expiration import (
    MessageExpirationProcessor,
)
from src.backend.dsl.engine.processors.eip.reliability.redelivery_policy import (
    RedeliveryPolicyProcessor,
)
from src.backend.dsl.engine.processors.eip.reliability.return_address import (
    ReturnAddressProcessor,
)

__all__ = (
    "CorrelationIdentifierProcessor",
    "ExpirationResolver",
    "HEADER_CORRELATION_ID",
    "HEADER_EXPIRATION",
    "HEADER_MESSAGE_ID",
    "HEADER_REDELIVERED",
    "HEADER_REDELIVERY_COUNT",
    "HEADER_RETURN_ADDRESS",
    "IdFactory",
    "MessageExpirationProcessor",
    "RedeliveryAttempt",
    "RedeliveryPolicyProcessor",
    "ReturnAddressProcessor",
)
