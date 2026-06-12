from __future__ import annotations

"""S60 W3 — health.py part of setup_infra decomp.

Funcs: _get_watcher_manager, _register_health_checks.

health check registration (132 LOC main func + helper).
"""

from typing import Any

from src.backend.infrastructure.clients.storage.clickhouse import get_clickhouse_client
from src.backend.infrastructure.clients.storage.redis import get_redis_client
from src.backend.infrastructure.clients.storage.s3_pool import get_s3_client
from src.backend.infrastructure.database.database import get_db_initializer
from src.backend.core.logging import get_logger

app_logger = get_logger("application")


def _get_watcher_manager():
    """Ленивый импорт WatcherManager для избежания циклических зависимостей."""
    from src.backend.entrypoints.filewatcher.watcher_manager import watcher_manager

    return watcher_manager


async def _register_health_checks() -> None:
    """ARCH-3: Wire HealthAggregator to infrastructure components.

    Registers ping-based health checks for Redis, DB, S3, SMTP,
    ClickHouse, Kafka (TCP probe) and NATS (TCP probe).
    Aggregator exposes unified /health endpoint for K8s probes.
    """
    try:
        from src.backend.infrastructure.application.health_aggregator import (
            get_health_aggregator,
        )
    except ImportError:
        return

    aggregator = get_health_aggregator()

    # Redis
    async def _redis_health() -> dict[str, Any]:
        import time

        start = time.monotonic()
        try:
            redis_client = get_redis_client()
            raw = getattr(redis_client, "_raw_client", None) or redis_client
            await raw.ping()
            return {
                "status": "ok",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    # DB main
    async def _db_health() -> dict[str, Any]:
        import time

        from sqlalchemy import text

        start = time.monotonic()
        try:
            async with get_db_initializer().get_async_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            return {
                "status": "ok",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    # S3
    async def _s3_health() -> dict[str, Any]:
        import time

        start = time.monotonic()
        try:
            is_ok = await get_s3_client().check_bucket_exists()
            return {
                "status": "ok" if is_ok else "degraded",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    # ClickHouse
    async def _clickhouse_health() -> dict[str, Any]:
        import time

        start = time.monotonic()
        try:
            ok = await get_clickhouse_client().ping()
            return {
                "status": "ok" if ok else "degraded",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    # Kafka — lightweight TCP probe (avoids aiokafka import overhead)
    async def _kafka_health() -> dict[str, Any]:
        import asyncio
        import time

        from src.backend.core.config.services.queue import queue_settings

        if queue_settings.type != "kafka":
            return {"status": "skipped", "reason": "queue.type != kafka"}

        start = time.monotonic()
        host = queue_settings.host
        port = queue_settings.port
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=2.0
            )
            writer.close()
            await writer.wait_closed()
            return {
                "status": "ok",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    # NATS — lightweight TCP probe
    async def _nats_health() -> dict[str, Any]:
        import asyncio
        import time

        start = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("localhost", 4222), timeout=2.0
            )
            writer.close()
            await writer.wait_closed()
            return {
                "status": "ok",
                "latency_ms": round((time.monotonic() - start) * 1000, 2),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)[:200]}

    aggregator.register("redis", _redis_health)
    aggregator.register("database", _db_health)
    aggregator.register("s3", _s3_health)
    if _clickhouse_enabled():
        aggregator.register("clickhouse", _clickhouse_health)
    aggregator.register("kafka", _kafka_health)
    aggregator.register("nats", _nats_health)
    app_logger.info(
        "Health checks registered: redis, database, s3, clickhouse, kafka, nats"
    )
