"""Kafka pool registration helper (Sprint I-1.2).

Предоставляет :func:`register_kafka_pool_if_available` для интеграции
Kafka producer в :class:`UnifiedPoolManager`.

ADR-0172 (S90 W3): Kafka producer — per-component dependency, не singleton.
Однако для observability (PoolHealthMonitor) полезно зарегистрировать
producer pool в UnifiedPoolManager как LOGICAL pool с custom ping_fn.

Использование::

    from src.backend.infrastructure.messaging.kafka_pool_registration import (
        register_kafka_pool_if_available,
    )

    register_kafka_pool_if_available(manager, name="kafka_main")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.infrastructure.clients.unified_pool_manager import (
        UnifiedPoolManager,
    )


async def kafka_ping_fn() -> bool:
    """Default Kafka liveness check (best-effort, non-blocking).

    S189 fix: теперь async для соответствия
    ``ping_fn: Callable[[], Awaitable[Any]]`` в UnifiedPoolManager.

    Returns:
        True если Kafka producer доступен, False иначе.

    """
    try:
        from src.backend.infrastructure.messaging.kafka_producer import (
            KafkaProducer,  # noqa: F401 — availability probe
        )

        producer = KafkaProducer()
        return producer.is_available()
    except (ImportError, RuntimeError, OSError, ConnectionError, AttributeError) as ping_exc:
        # cycle-9/D-AUDIT-933: narrow exceptions + observability.
        # ImportError — Kafka SDK missing, RuntimeError — broker unavailable,
        # OSError/ConnectionError — network, AttributeError — producer API
        # change. Bare `except Exception` маскировал unrelated runtime errors.
        import logging  # noqa: F401 — availability probe
        logging.getLogger(__name__).debug(
            "kafka_pool.ping_failed",
            extra={"error": str(ping_exc)},
        )
        return False


def register_kafka_pool_if_available(
    manager: UnifiedPoolManager,
    *,
    name: str = "kafka_main",
    bootstrap_servers: list[str] | None = None,
) -> bool:
    """Регистрирует Kafka producer pool если доступен.

    Args:
        manager: UnifiedPoolManager instance.
        name: Pool name (default ``"kafka_main"``).
        bootstrap_servers: Опциональный override для bootstrap servers.

    Returns:
        True если pool зарегистрирован, False если Kafka недоступен.

    """
    try:
        from src.backend.infrastructure.messaging.kafka_producer import (
            KafkaProducer,  # noqa: F401 — availability probe
        )

        producer = KafkaProducer(bootstrap_servers=bootstrap_servers or [])
        manager.register(
            name=name,
            pool=producer,
            ping_fn=kafka_ping_fn,
        )
        return True
    except ImportError:
        # Kafka SDK not available (purgatory/faststream missing)
        return False
    except (RuntimeError, AttributeError, ValueError) as reg_exc:
        # cycle-9/D-AUDIT-933: narrow exceptions + observability.
        # RuntimeError — manager.register failed, AttributeError — manager
        # API change, ValueError — invalid args. Bare `except Exception`
        # маскировал unrelated runtime errors (KeyError, TypeError).
        import logging  # noqa: F401 — availability probe
        logging.getLogger(__name__).debug(
            "kafka_pool.register_failed",
            extra={"name": name, "error": str(reg_exc)},
        )
        return False


__all__ = ("kafka_ping_fn", "register_kafka_pool_if_available")
