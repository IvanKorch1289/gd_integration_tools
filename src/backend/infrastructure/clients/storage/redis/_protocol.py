"""Structural protocol for RedisClient mixins.

Module extracted by S147 W2 to resolve the S146 W1 broken import
(``from ._protocol import _RedisClientProtocol`` without the module
existing). Keeping the protocol in its own module breaks the circular
dependency between ``RedisClient`` and its mixins and gives mypy enough
information about the attributes/helpers the mixins use.
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

    def _resolve_retry_on_error(self) -> list[type[BaseException]]: ...

    def _base_url(self) -> str: ...

    def _db_for_kind(self, kind: RedisKind) -> int: ...

    def _build_client(self, kind: RedisKind) -> Redis: ...

    async def get_client(
        self, kind: RedisKind, force_reconnect: bool = False
    ) -> Redis: ...

    async def reset_client(self, kind: RedisKind) -> None: ...

    async def close(self) -> None: ...

    async def ensure_connected(self) -> bool: ...

    async def check_connection(self) -> bool: ...

    async def execute(
        self, kind: RedisKind, operation: Callable[[Redis], Awaitable[Any]]
    ) -> Any: ...

    async def _safe_close(self, client: Redis | None) -> None: ...

    async def cache_get(self, key: str) -> Any: ...

    async def cache_set(
        self, key: str, value: Any, expire: int | None = None
    ) -> None: ...

    async def cache_delete(self, *keys: str) -> int: ...

    async def cache_delete_pattern(self, pattern: str) -> int: ...

    async def bulk_cache_get(self, keys: list[str]) -> dict[str, Any]: ...

    async def bulk_cache_set(
        self, mapping: dict[str, Any], expire: int | None = None
    ) -> None: ...

    def decode(self, value: Any) -> Any: ...

    async def limits_client(self) -> Redis: ...

    async def queue_client(self) -> Redis: ...

    async def list_cache_keys(self, pattern: str = "*") -> dict[str, list[str]]: ...

    async def get_cache_value(self, key: str) -> Any: ...

    async def invalidate_cache(self, *keys: str) -> int: ...

    async def add_to_stream(self, stream_name: str, data: dict[str, Any]) -> Any: ...

    async def stream_publish(
        self,
        stream: str,
        data: dict[str, Any],
        max_len: int | None = None,
        approximate: bool = True,
    ) -> str: ...
