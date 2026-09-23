"""Sprint 15 P1-12: infrastructure startup phases.

Phases:
- :func:`phase_redis_cluster` — Redis cluster adapter (Sprint 3 K2 W1)
- :func:`phase_setup_infra` — Starting infrastructure (DB/cache/etc.)
- :func:`phase_eventbus_startup` — EventBus (S133 W4)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI

_logger = get_logger("application.startup.infrastructure")


async def phase_redis_cluster(app: FastAPI) -> None:  # noqa: ARG001
    """Redis cluster adapter (Sprint 3 K2 W1) — opt-in via env."""
    if os.environ.get("REDIS_CLUSTER_ENABLED", "false").lower() != "true":
        return
    try:
        nodes_env = os.environ.get("REDIS_CLUSTER_NODES", "").strip()
        if not nodes_env:
            _logger.warning(
                "REDIS_CLUSTER_ENABLED=true, но REDIS_CLUSTER_NODES пуст — пропуск"
            )
        else:
            from src.backend.infrastructure.clients.storage.redis import (
                configure_redis_cluster,
            )

            nodes = [n.strip() for n in nodes_env.split(",") if n.strip()]
            await configure_redis_cluster(nodes)
            _logger.info("Redis cluster adapter configured: %d nodes", len(nodes))
    except Exception as redis_exc:
        _logger.warning(
            "Redis cluster adapter skipped: %s "
            "(приложение продолжит с standalone Redis)",
            redis_exc,
        )


async def phase_setup_infra(app: FastAPI) -> None:  # noqa: ARG001
    """Starting infrastructure: DB pool, cache layers, protocol providers."""
    from src.backend.plugins.composition.lifecycle.bootstrap import (
        validate_cache_layers,
    )
    from src.backend.plugins.composition.lifecycle.protocols import (
        register_protocol_providers,
    )
    from src.backend.plugins.composition.setup_infra import starting

    await starting()
    await register_protocol_providers()
    validate_cache_layers()


async def phase_eventbus_startup(app: FastAPI) -> None:
    """EventBus startup (S133 W4) — registers to app.state."""
    from src.backend.plugins.composition.lifecycle.startup import _start_event_bus

    await _start_event_bus(app)


__all__ = ("phase_redis_cluster", "phase_setup_infra", "phase_eventbus_startup")
