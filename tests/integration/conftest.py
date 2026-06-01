"""
Conftest для интеграционных тестов.

Поднимает реальные контейнеры через testcontainers:
  - PostgreSQL (SQLAlchemy async engine)
  - Redis (aioredis клиент)

Фикстуры наследуют root conftest.py и переопределяют test_db / test_cache.

Зависимости: testcontainers-python, sqlalchemy[asyncio], asyncpg, redis.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


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
    except ImportError:
        pytest.skip("testcontainers не установлен")

    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def test_cache():
    """Redis через testcontainers.

    Yields:
        URL подключения к тестовому Redis.
    """
    try:
        from testcontainers.redis import RedisContainer
    except ImportError:
        pytest.skip("testcontainers не установлен")

    with RedisContainer() as redis:
        yield redis.get_connection_url()


@pytest.fixture(scope="session")
def pg_engine_with_alembic() -> Iterator["AsyncEngine"]:
    """Поднимает Postgres-контейнер и накатывает alembic-миграции.

    Используется для тестов, требующих актуальной production-схемы
    (как правило, проверка PG-specific миграций или новых колонок).

    Yields:
        SQLAlchemy ``AsyncEngine`` поверх ``asyncpg``-URL.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers[postgres] не установлен")

    try:
        from alembic import command as alembic_command
        from alembic.config import Config as AlembicConfig
        from sqlalchemy.ext.asyncio import create_async_engine
    except ImportError as exc:
        pytest.skip(f"alembic/sqlalchemy недоступны: {exc}")

    try:
        container = PostgresContainer("postgres:16-alpine")
        container.start()
    except Exception as exc:  # docker недоступен/нет прав/нет образа
        pytest.skip(f"Docker недоступен для testcontainers: {exc}")

    try:
        sync_url = container.get_connection_url()
        async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://").replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )

        cfg = AlembicConfig(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", sync_url)
        alembic_command.upgrade(cfg, "head")

        engine = create_async_engine(async_url, future=True)
        try:
            yield engine
        finally:
            import asyncio

            asyncio.run(engine.dispose())
    finally:
        container.stop()
