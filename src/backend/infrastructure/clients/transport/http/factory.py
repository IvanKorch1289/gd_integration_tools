from __future__ import annotations

from collections.abc import AsyncGenerator


async def get_http_client() -> AsyncGenerator[HttpClient]:
    client = HttpClient()
    yield client


def get_http_client_dependency() -> HttpClient:
    """Lazy singleton глобального ``HttpClient`` (Wave 6.1)."""
    return HttpClient()
