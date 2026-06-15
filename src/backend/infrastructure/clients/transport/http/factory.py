from __future__ import annotations

from collections.abc import AsyncGenerator


async def get_http_client() -> AsyncGenerator[HttpClient]:
    # Lazy import to break circular dependency: __init__.py imports
    # factory functions, factory functions cannot import HttpClient
    # back from __init__.py (would be partial-init error).
    from . import HttpClient

    client = HttpClient()
    yield client


def get_http_client_dependency() -> HttpClient:
    """Lazy singleton глобального ``HttpClient`` (Wave 6.1)."""
    from . import HttpClient

    return HttpClient()
