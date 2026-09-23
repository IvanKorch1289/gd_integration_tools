"""DLQ Replay Cockpit — централизованный DLQ + replay tooling (Wave 1 P0 #4).

Проблема (EP-R1):
    Poison messages и unrecoverable failures попадают в DLQ.
    Без централизованного cockpit:
    - Непонятно, какие ошибки классифицируются как poison.
    - Replay делается вручную через broker CLI.
    - Нет audit trail для replayed events.

Решение:
    ``DLQReplayService`` + ``ReplayCockpit``:

    1. ``classify_failure(error)`` → ``FailureClass`` (retryable/poison/business/security).
    2. ``send_to_dlq(message, error, failure_class)`` → DLQ record с full context.
    3. ``list_dlq(filter)`` → список pending DLQ records.
    4. ``replay(message_id, operator)`` → re-publish + audit.

Использование::

    from src.backend.core.dlq_replay import get_dlq_replay

    cockpit = get_dlq_replay()

    # При failure:
    await cockpit.send_to_dlq(
        message={"order_id": "o1"},
        error=ValueError("timeout"),
        consumer="order-consumer",
        topic="events.orders",
    )

    # Replay:
    records = await cockpit.list_dlq(consumer="order-consumer")
    await cockpit.replay(record_id=records[0].record_id, operator="alice")
"""

from __future__ import annotations

from src.backend.core.dlq_replay.cockpit import (
    DLQRecord,
    DLQReplayService,
    FailureClass,
    ReplayCockpit,
    get_dlq_replay,
)
from src.backend.core.dlq_replay.failure_taxonomy import (
    FailureTaxonomy,
    classify_exception,
)
from src.backend.core.dlq_replay.store.base import DLQStore
from src.backend.core.dlq_replay.store.in_memory import InMemoryDLQStore

__all__ = (
    "DLQRecord",
    "DLQReplayService",
    "DLQStore",
    "FailureClass",
    "FailureTaxonomy",
    "InMemoryDLQStore",
    "ReplayCockpit",
    "classify_exception",
    "get_dlq_replay",
)
