"""Pytest-фикстура: PostgreSQL через testcontainers.

Использует уже подключённую зависимость ``testcontainers[postgres]``.
Для chaos/perf-сценариев и интеграционных тестов плагинов — без неё
fixture выставляет ``pytest.skip``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

__all__ = ("postgres_container", "postgres_url")


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[Any]:
    """Поднимает контейнер PostgreSQL на время сессии."""
    try:
        from testcontainers.postgres import PostgresContainer  # noqa: PLC0415
    except ImportError:
        pytest.skip("testcontainers[postgres] not installed (extra: testkit)")

    container = PostgresContainer("postgres:16-alpine")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def postgres_url(postgres_container: Any) -> str:
    """SQLAlchemy URL поднятого контейнера PostgreSQL."""
    return postgres_container.get_connection_url()
