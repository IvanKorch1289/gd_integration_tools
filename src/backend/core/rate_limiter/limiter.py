"""Token bucket rate limiter (sync + async) — Wave 4 P2.14b.

Pure-Python stdlib implementation:
- RateLimiter (sync): thread-safe via threading.Lock.
- AsyncRateLimiter: async via asyncio.Lock + asyncio.Event.
- get_rate_limiter(name, config) singleton registry.
- RateLimiterConfig (max_tokens, refill_rate, initial_tokens).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = ("AsyncRateLimiter", "RateLimiter", "RateLimiterConfig", "get_rate_limiter")


@dataclass(slots=True)
class RateLimiterConfig:
    """Configuration для rate limiter.

    Attributes:
        max_tokens: Bucket capacity (burst size).
        refill_rate: Tokens added per second.
        initial_tokens: Starting tokens (default = max_tokens).
    """

    max_tokens: int = 10
    refill_rate: float = 1.0
    initial_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be > 0")
        if self.refill_rate <= 0:
            raise ValueError("refill_rate must be > 0")
        if self.initial_tokens is None:
            self.initial_tokens = self.max_tokens
        if not 0 <= self.initial_tokens <= self.max_tokens:
            raise ValueError("initial_tokens must be in [0, max_tokens]")


class RateLimiter:
    """Synchronous token bucket rate limiter (thread-safe)."""

    def __init__(self, config: RateLimiterConfig) -> None:
        self._config = config
        self._tokens: float = float(config.initial_tokens or 0)
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    @property
    def config(self) -> RateLimiterConfig:
        """Конфигурация лимитера (rates/burst)."""
        return self._config

    def _refill(self) -> None:
        """Add tokens based on elapsed time. Must hold lock."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(
                self._config.max_tokens,
                self._tokens + elapsed * self._config.refill_rate,
            )
            self._last_refill = now

    def try_acquire(self, cost: float = 1.0) -> bool:
        """Try to consume `cost` tokens. Returns True if successful."""
        with self._lock:
            self._refill()
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False

    def acquire(self, cost: float = 1.0, *, timeout: float | None = None) -> bool:
        """Block until tokens available (with optional timeout)."""
        deadline = time.monotonic() + timeout if timeout is not None else None
        while True:
            if self.try_acquire(cost):
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            # Sleep proportional to needed time.
            time.sleep(min(0.1, cost / max(self._config.refill_rate, 0.01)))

    @property
    def available_tokens(self) -> float:
        """Snapshot of current tokens (does NOT refill).

        Use ``try_acquire()`` to get a refilled value before reading.
        """
        with self._lock:
            return self._tokens

    def __repr__(self) -> str:
        return f"RateLimiter(tokens={self._tokens:.2f}, max={self._config.max_tokens})"

    def reset(self) -> None:
        """Reset to initial state."""
        with self._lock:
            self._tokens = float(self._config.initial_tokens or 0)
            self._last_refill = time.monotonic()

    def available_with_refill(self) -> float:
        """Return tokens after applying pending refill (test/debug helper)."""
        with self._lock:
            self._refill()
            return self._tokens


class AsyncRateLimiter:
    """Async token bucket rate limiter."""

    def __init__(self, config: RateLimiterConfig) -> None:
        self._config = config
        self._tokens: float = float(config.initial_tokens or 0)
        self._last_refill: float = 0.0
        self._lock = asyncio.Lock()
        self._event = asyncio.Event()

    @property
    def config(self) -> RateLimiterConfig:
        """Конфигурация конкретного лимитера."""
        return self._config

    async def _refill(self) -> None:
        now = asyncio.get_event_loop().time()
        if self._last_refill == 0.0:
            self._last_refill = now
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(
                self._config.max_tokens,
                self._tokens + elapsed * self._config.refill_rate,
            )
            self._last_refill = now
            self._event.set()

    async def try_acquire(self, cost: float = 1.0) -> bool:
        """Попытка получить токены; False при нехватке (cost учитывается)."""
        async with self._lock:
            await self._refill()
            if self._tokens >= cost:
                self._tokens -= cost
                return True
            return False

    async def acquire(self, cost: float = 1.0, *, timeout: float | None = None) -> bool:
        """Block until tokens available."""
        deadline = (
            asyncio.get_event_loop().time() + timeout if timeout is not None else None
        )
        while True:
            if await self.try_acquire(cost):
                return True
            if deadline is not None and asyncio.get_event_loop().time() >= deadline:
                return False
            # Wait for refill event.
            try:
                await asyncio.wait_for(
                    self._event.wait(),
                    timeout=min(0.1, cost / max(self._config.refill_rate, 0.01)),
                )
            except asyncio.TimeoutError:
                pass
            # Re-check after wakeup.
            self._event.clear()

    @property
    def available_tokens(self) -> float:
        """Доступно токенов прямо сейчас."""
        return self._tokens  # Approximate; without lock for sync read.

    def reset(self) -> None:
        """Сбросить состояние buckets (для тестов)."""
        self._tokens = float(self._config.initial_tokens or 0)
        self._last_refill = 0.0
        self._event.set()


# ─── Module-level singleton registry ────────────────────────

_limiters: dict[str, RateLimiter] = {}


def get_rate_limiter(name: str, config: RateLimiterConfig | None = None) -> RateLimiter:
    """Get or create singleton sync rate limiter по name."""
    if name not in _limiters:
        if config is None:
            config = RateLimiterConfig()
        _limiters[name] = RateLimiter(config)
    return _limiters[name]


def reset_rate_limiters() -> None:
    """Reset all singletons (test-only)."""
    _limiters.clear()
