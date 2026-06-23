"""Structural protocol for RedisClient mixins.

Breaks the circular dependency between ``RedisClient`` and its mixins and
gives mypy enough information about the attributes/helpers the mixins use.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from redis.asyncio import Redis

from src.backend.core.config.settings import RedisSettings

RedisKind = Any


class _RedisClientProtocol(Protocol):
    """Private shape shared by RedisClient mixins."""

    settings: RedisSettings
    logger: Any
    _clients: dict[RedisKind, Redis | None]
    _locks: dict[RedisKind, Any]
    _breakers: dict[RedisKind, Any]

    def _resolve_retry_on_error(self) -> list[type[BaseException]]:
        """Resolve retry-on-error exception types.

        Returns:
            List of exception types to retry on.
        """
        ...

    def _base_url(self) -> str:
        """Get base Redis URL.

        Returns:
            Redis URL string.
        """
        ...

    def _db_for_kind(self, kind: RedisKind) -> int:
        """Get database number for Redis kind.

        Args:
            kind: Redis kind identifier.

        Returns:
            Database number.
        """
        ...

    def _build_client(self, kind: RedisKind) -> Redis:
        """Build Redis client for kind.

        Args:
            kind: Redis kind identifier.

        Returns:
            Redis client instance.
        """
        ...

    async def get_client(self, kind: RedisKind, force_reconnect: bool = False) -> Redis:
        """Get Redis client for kind.

        Args:
            kind: Redis kind identifier.
            force_reconnect: Force reconnection.

        Returns:
            Redis client instance.
        """
        ...

    async def reset_client(self, kind: RedisKind) -> None:
        """Reset Redis client for kind.

        Args:
            kind: Redis kind identifier.
        """
        ...

    async def close(self) -> None:
        """Close all Redis connections."""
        ...

    async def ensure_connected(self) -> None:
        """Ensure all Redis connections are active."""
        ...

    async def check_connection(self, kind: RedisKind) -> bool:
        """Check Redis connection health.

        Args:
            kind: Redis kind identifier.

        Returns:
            True if connected.
        """
        ...

    async def execute(
        self, kind: RedisKind, operation: Callable[[Redis], Awaitable[Any]]
    ) -> Any:
        """Execute operation with Redis client.

        Args:
            kind: Redis kind identifier.
            operation: Async operation to execute.

        Returns:
            Operation result.
        """
        ...

    async def _safe_close(self, client: Redis | None) -> None: ...

    async def cache_get(self, key: str) -> Any: ...

    async def cache_set(
        self, key: str, value: Any, expire: int | None = None
    ) -> None: ...

    async def cache_delete(self, *keys: str) -> int: ...

    async def cache_delete_pattern(self, pattern: str) -> int: ...

    async def bulk_get(self, keys: list[str]) -> list[Any]: ...

    async def bulk_set(
        self, items: dict[str, Any], expire: int | None = None
    ) -> None: ...

    def decode(self, value: Any) -> Any: ...

    async def limits_client(self) -> Redis: ...

    async def queue_client(self) -> Redis: ...

    async def list_cache_keys(self, pattern: str = "*") -> dict[str, list[str]]: ...

    async def get_cache_value(self, key: str) -> Any: ...

    async def invalidate_cache(self, *keys: str) -> int: ...

    async def stream_publish(
        self,
        stream: str,
        data: dict[str, Any],
        max_len: int | None = None,
        approximate: bool = True,
    ) -> str: ...
