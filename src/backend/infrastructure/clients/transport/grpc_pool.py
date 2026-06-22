"""gRPC channel pool — reuse gRPC channels across calls.

Problem: gRPC sink creates a new channel per ``send()`` call (TCP + TLS +
HTTP/2 setup each time). gRPC source creates new channel on each reconnect.

Solution: Queue-based pool (same pattern as ImapConnectionPool). Pre-warm
min_size channels, reuse across calls, health-check via ``channel_ready()``.

Usage::

    pool = GrpcChannelPool(target="grpc.example.com:443", secure=True)
    await pool.start()
    async with pool.acquire() as channel:
        stub = MyStub(channel)
        response = await stub.MyMethod(request)
    await pool.stop()
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from src.backend.core.config.pooling import DEFAULT_POOLING_PROFILE, PoolingProfile
from src.backend.core.logging import get_logger
# S165 W4: Purgatory Circuit Breaker для gRPC (Rule 6).
# Per skill: per-pool long-lived manager → per-pool CB keyed by target.
# Module-level per-target CB factory to avoid circular imports.
from src.backend.core.resilience.breaker import (  # noqa: E402
    BreakerSpec,
    get_breaker_registry,
)

__all__ = ("GrpcChannelPool",)

_logger = get_logger("infrastructure.clients.transport.grpc_pool")


def _get_grpc_breaker(target: str) -> Any:
    """S165 W4: Per-target module-level CB for gRPC pool (per-pool pattern)."""
    return get_breaker_registry().get_or_create(
        f"grpc_pool_{target}",
        BreakerSpec(
            name=f"grpc_pool_{target}",
            failure_threshold=5,
            recovery_timeout=30.0,
        ),
    )


class GrpcChannelPool:
    """Queue-based gRPC channel pool.

    Args:
        target: ``host:port`` of gRPC server.
        secure: Use TLS (default True).
        pooling: Pool sizing profile.
    """

    def __init__(
        self, *, target: str, secure: bool = True, pooling: PoolingProfile | None = None
    ) -> None:
        self._target = target
        self._secure = secure
        self._pooling = pooling or DEFAULT_POOLING_PROFILE
        self._pool: asyncio.Queue[Any] = asyncio.Queue(maxsize=self._pooling.max_size)
        self._created: int = 0
        self._lock = asyncio.Lock()
        self._started: bool = False

    async def start(self) -> None:
        """Start the pool and pre-warm min_size channels."""
        if self._started:
            return

        for _ in range(self._pooling.min_size):
            channel = self._create_channel()
            await channel.channel_ready()
            await self._pool.put(channel)
            self._created += 1
        self._started = True
        _logger.info(
            "grpc pool started",
            extra={
                "target": self._target,
                "min_size": self._pooling.min_size,
                "max_size": self._pooling.max_size,
            },
        )

    async def stop(self) -> None:
        """Stop the pool and close all channels."""
        if not self._started:
            return
        while not self._pool.empty():
            try:
                channel = self._pool.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                await channel.close()
            except Exception:
                pass
        self._created = 0
        self._started = False
        _logger.info("grpc pool stopped", extra={"target": self._target})

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        """Acquire a gRPC channel from pool. Returns to pool on exit."""
        if not self._started:
            raise RuntimeError(f"GrpcChannelPool not started: {self._target}")

        # S165 W6: Purgatory CB integration (Rule 6).
        # Per skill: nested `async with self._lock:` requires manual CB
        # __aenter__/__aexit__ (per-call shared CB).
        from src.backend.core.resilience.breaker import CircuitOpen

        breaker = _get_grpc_breaker(self._target)
        breaker_guard = breaker.guard()
        await breaker_guard.__aenter__()

        channel: Any | None = None
        try:
            try:
                channel = self._pool.get_nowait()
            except asyncio.QueueEmpty:
                async with self._lock:
                    if self._created < self._pooling.max_size:
                        channel = self._create_channel()
                        await channel.channel_ready()
                        self._created += 1
                    else:
                        channel = await asyncio.wait_for(
                            self._pool.get(), timeout=self._pooling.acquire_timeout_s
                        )
            # Liveness check
            try:
                await asyncio.wait_for(channel.channel_ready(), timeout=2.0)
            except Exception:
                try:
                    await channel.close()
                except Exception:
                    pass
                channel = self._create_channel()
                await channel.channel_ready()

            yield channel
        finally:
            if channel is not None:
                try:
                    self._pool.put_nowait(channel)
                except asyncio.QueueFull:
                    try:
                        await channel.close()
                    except Exception:
                        pass
                    self._created -= 1
            await breaker_guard.__aexit__(None, None, None)

    def _create_channel(self) -> Any:
        import grpc

        if self._secure:
            return grpc.aio.secure_channel(self._target, grpc.ssl_channel_credentials())
        return grpc.aio.insecure_channel(self._target)
