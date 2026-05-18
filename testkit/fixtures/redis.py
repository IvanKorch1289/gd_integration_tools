"""Pytest-фикстура: Redis через testcontainers.

Optional extra ``testkit`` обеспечивает ``testcontainers[redis]``;
без extra fixture выставляет ``pytest.skip``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

__all__ = ("redis_container", "redis_url")


@pytest.fixture(scope="session")
def redis_container() -> Iterator[Any]:
    """Поднимает контейнер Redis на время сессии."""
    try:
        from testcontainers.redis import RedisContainer  # noqa: PLC0415
    except ImportError:
        pytest.skip("testcontainers[redis] not installed (extra: testkit)")

    container = RedisContainer("redis:7-alpine")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def redis_url(redis_container: Any) -> str:
    """URL поднятого контейнера Redis (``redis://host:port/0``)."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"
