"""NATS connection pool — persistent NATS connection with health checks.

Problem: NATSJetStreamSink creates a new connection per ``publish()`` call
(connect → publish → drain → close). This is wasteful for high-throughput
scenarios.

Solution: Single persistent connection (NATS multiplexes streams over one
connection). Pool maintains the connection and provides acquire/release for
JetStream context.

Usage::

    pool = NatsConnectionPool(url="nats://localhost:4222")
    await pool.start()
    async with pool.acquire() as js:
        await js.publish("subject", b"data")
    await pool.stop()
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("NatsConnectionPool",)

_logger = get_logger("infrastructure.clients.transport.nats_pool")


class NatsConnectionPool:
    """Persistent NATS connection pool.

    Unlike TCP pools, NATS multiplexes all messages over a single TCP
    connection. This pool maintains ONE persistent connection and provides
    JetStream context access.

    Args:
        url: NATS server URL.
        name: Connection name for monitoring.
        max_reconnect_attempts: Max reconnect attempts before giving up.
    """

    def __init__(
        self,
        *,
        url: str = "nats://localhost:4222",
        name: str = "nats-pool",
        max_reconnect_attempts: int = 10,
    ) -> None:
        self._url = url
        self._name = name
        self._max_reconnect = max_reconnect_attempts
        self._nc: Any | None = None
        self._started: bool = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the pool and establish persistent NATS connection."""
        if self._started:
            return
        try:
            import nats
        except ImportError:
            _logger.warning("nats-py not installed, pool disabled")
            return
        async with self._lock:
            if self._nc is not None:
                return
            self._nc = await nats.connect(
                self._url,
                max_reconnect_attempts=self._max_reconnect,
                name=self._name,
            )
            self._started = True
            _logger.info(
                "nats pool started",
                extra={"url": self._url, "name": self._name},
            )

    async def stop(self) -> None:
        """Stop the pool and drain NATS connection."""
        if not self._started or self._nc is None:
            return
        try:
            await self._nc.drain()
        except Exception as exc:
            _logger.debug("nats pool drain error: %s", exc)
        try:
            await self._nc.close()
        except Exception as exc:
            _logger.debug("nats pool close error: %s", exc)
        self._nc = None
        self._started = False
        _logger.info("nats pool stopped", extra={"name": self._name})

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        """Acquire NATS connection. Yields nats client for direct use."""
        if not self._started or self._nc is None:
            raise RuntimeError(f"NatsConnectionPool not started: {self._name}")
        # Reconnect if disconnected
        if not self._nc.is_connected:
            try:
                await self._nc.reconnect()
            except Exception as exc:
                raise RuntimeError(f"NATS reconnect failed: {exc}") from exc
        yield self._nc

    async def publish(
        self,
        subject: str,
        data: bytes,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Publish to NATS JetStream via pooled connection."""
        if not self._started or self._nc is None:
            raise RuntimeError(f"NatsConnectionPool not started: {self._name}")
        if not self._nc.is_connected:
            await self._nc.reconnect()
        js = self._nc.jetstream()
        return await js.publish(subject, data, headers=headers or None)

    async def health(self) -> bool:
        """Check if NATS connection is alive."""
        if self._nc is None:
            return False
        return self._nc.is_connected
