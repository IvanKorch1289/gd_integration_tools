"""
Conftest для интеграционных тестов.

Поднимает реальные контейнеры через testcontainers:
  - PostgreSQL (SQLAlchemy async engine)
  - Redis (aioredis клиент)

Фикстуры наследуют root conftest.py и переопределяют test_db / test_cache.

Зависимости: testcontainers-python, sqlalchemy[asyncio], asyncpg, redis.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def test_db():
    """PostgreSQL через testcontainers.

    Scope=session: контейнер поднимается один раз на всю сессию.
    Используйте транзакцию + rollback в каждом тесте для изоляции.

    Yields:
        SQLAlchemy async engine с подключением к тестовой БД.
    """
    try:
        from testcontainers.postgres import PostgresContainer

        with PostgresContainer("postgres:16-alpine") as pg:
            yield pg.get_connection_url()
    except ImportError:
        pytest.skip("testcontainers не установлен")


@pytest.fixture(scope="session")
def test_cache():
    """Redis через testcontainers.

    Yields:
        URL подключения к тестовому Redis.
    """
    try:
        from testcontainers.redis import RedisContainer

        with RedisContainer() as redis:
            yield redis.get_connection_url()
    except ImportError:
        pytest.skip("testcontainers не установлен")
