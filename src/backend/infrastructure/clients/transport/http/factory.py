from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.infrastructure.clients.transport.http import HttpClient


_http_client_singleton: "HttpClient | None" = None


async def get_http_client() -> AsyncGenerator["HttpClient"]:
    # Lazy import to break circular dependency: __init__.py imports
    # factory functions, factory functions cannot import HttpClient
    # back from __init__.py (would be partial-init error).
    from . import HttpClient

    client = HttpClient()
    try:
        yield client
    finally:
        await client.close()


def get_http_client_dependency() -> "HttpClient":
    """Returns the global singleton HttpClient instance.

    ponytail: Исправлено — был создавал новый инстанс при каждом вызове.
    Теперь используется модульный синглтон с lazy init.
    """
    global _http_client_singleton
    if _http_client_singleton is None:
        _http_client_singleton = _create_http_client_sync()
    return _http_client_singleton


def _create_http_client_sync() -> "HttpClient":
    """Create HttpClient in sync context (for singleton init)."""
    from . import HttpClient

    return HttpClient()


def get_http_client_typed() -> "HttpClient":
    """Alias для get_http_client_dependency — для использования в typed DI."""
    return get_http_client_dependency()
