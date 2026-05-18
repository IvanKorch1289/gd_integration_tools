"""InMemoryDLQWriter — для unit-тестов и dev_light (Sprint 9 K2 W1).

Хранит DLQ-envelope'ы в list для inspection в тестах. Идемпотентно
дедуплицирует по ``dlq_id``.
"""

from __future__ import annotations

from src.backend.infrastructure.messaging.dlq_base import DLQEnvelope

__all__ = ("InMemoryDLQWriter",)


class InMemoryDLQWriter:
    """In-memory writer для тестов.

    Attributes:
        records: список накопленных envelope'ов.
    """

    def __init__(self) -> None:
        self.records: list[DLQEnvelope] = []
        self._seen: set[str] = set()

    async def write(self, envelope: DLQEnvelope) -> None:
        if envelope.dlq_id in self._seen:
            return
        self._seen.add(envelope.dlq_id)
        self.records.append(envelope)

    def clear(self) -> None:
        self.records.clear()
        self._seen.clear()
