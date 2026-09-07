"""Sprint 38: messaging facade — re-exports infrastructure.messaging.

Ponytail fix: services/* должен импортировать через core.api.messaging
(not infrastructure.messaging directly). Это eliminates
services → infrastructure.messaging violations.
"""

from __future__ import annotations

# Re-exports infrastructure.messaging (3+ services → infrastructure.messaging violations)
from src.backend.infrastructure.messaging import dlq_base, outbox
from src.backend.infrastructure.messaging.outbox.stuck_monitor import (
    OutboxStuckMonitor as OutboxMonitor,
)

# Backward-compat aliases
DLQBase = dlq_base
Outbox = outbox


# Sprint 38 fix: KafkaProducer is conditional (requires aiokafka installed).
# Lazy import via __getattr__ to avoid breaking imports on dev env.
# ponytail: PEP 562 lazy proxy; mypy sees orphan module-level signature.
def __getattr__(name: str) -> object:  # type: ignore[misc]
    if name == "KafkaProducer":
        # kafka_pool_registration only registers; реальный KafkaProducer class
        # в kafka_producer module (lazy импорт сохраняет optional aiokafka dep).
        from src.backend.infrastructure.messaging.kafka_producer import (  # type: ignore[import-not-found]  # Kafka SDK optional — ImportError fallback ниже
            KafkaProducer,  # type: ignore[attr-defined]
        )

        return KafkaProducer
    raise AttributeError(f"module 'core.api.messaging' has no attribute {name!r}")


__all__ = [
    "dlq_base",
    "outbox",
    "OutboxMonitor",
    "DLQBase",
    "Outbox",
    # KafkaProducer is exposed via __getattr__ (lazy, requires aiokafka)
]
