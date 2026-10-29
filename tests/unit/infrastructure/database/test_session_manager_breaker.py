"""Wave 16 / X4: breaker не должен открываться на бизнес-ошибках.

``NotFoundError``/``IntegrityError`` — ожидаемый исход запроса, а не
недоступность БД. Но они проходили через ``self._breaker.guard()``, и
purgatory считала их отказами: 10 «не найдено» подряд открывали breaker
``db:<name>`` на 30 с и глушили весь DB-трафик (воспроизведено:
``OpenedState``).

Контракт: ``BreakerSpec.excluded_exceptions`` исключает эти исключения
из счётчика отказов; настоящие DB-ошибки breaker по-прежнему открывают.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytest.importorskip("aiosqlite")

from src.backend.core.config.settings import settings  # noqa: E402
from src.backend.core.errors import DatabaseError, NotFoundError  # noqa: E402
from src.backend.core.resilience.breaker import breaker_registry  # noqa: E402
from src.backend.infrastructure.database.session_manager import (  # noqa: E402
    DatabaseSessionManager,
)


@pytest.fixture(autouse=True)
def _reset_breakers() -> Any:
    """Изолирует тесты от общего singleton-реестра breaker'ов."""
    breaker_registry.reset()
    yield
    breaker_registry.reset()


@pytest_asyncio.fixture
async def sqlite_manager(tmp_path: Any) -> DatabaseSessionManager:
    """Session manager поверх временной aiosqlite-БД.

    Yields:
        Готовый менеджер сессий.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    db_file = tmp_path / "breaker.db"
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    maker = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    manager = DatabaseSessionManager(session_maker=maker, db_name="breaker-notfound")
    try:
        yield manager
    finally:
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_not_found_error_does_not_open_breaker(
    sqlite_manager: DatabaseSessionManager,
) -> None:
    """Десять «не найдено» не открывают breaker.

    Args:
        sqlite_manager: Менеджер сессий поверх aiosqlite.
    """

    @sqlite_manager.connection()
    async def _missing(session: AsyncSession) -> int:
        raise NotFoundError(message="ресурс не найден")

    for _ in range(10):
        with pytest.raises(NotFoundError):
            await _missing()

    assert sqlite_manager._breaker.state != "open", (
        "бизнес-ошибка NotFoundError не должна открывать circuit breaker"
    )


@pytest.mark.asyncio
async def test_integrity_error_does_not_open_breaker(
    sqlite_manager: DatabaseSessionManager,
) -> None:
    """``IntegrityError`` (дубликат ключа) — тоже не отказ БД.

    Args:
        sqlite_manager: Менеджер сессий поверх aiosqlite.
    """

    @sqlite_manager.connection()
    async def _duplicate(session: AsyncSession) -> int:
        raise IntegrityError(
            "INSERT INTO users (email) VALUES (?)",
            {"email": "ivan@example.com"},
            Exception("UNIQUE constraint failed: users.email"),
        )

    for _ in range(10):
        with pytest.raises(IntegrityError):
            await _duplicate()

    assert sqlite_manager._breaker.state != "open", (
        "IntegrityError не должен открывать circuit breaker"
    )


@pytest.mark.asyncio
async def test_real_db_error_still_opens_breaker(tmp_path: Any) -> None:
    """Настоящая ошибка БД breaker по-прежнему открывает (регрессия-сторож).

    Args:
        tmp_path: Временный каталог для SQLite-файла.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    db_file = tmp_path / "breaker_real.db"
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    maker = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    manager = DatabaseSessionManager(session_maker=maker, db_name="breaker-real")

    @manager.connection()
    async def _broken(session: AsyncSession) -> int:
        raise RuntimeError("соединение с БД потеряно")

    threshold = max(2, int(settings.database.circuit_breaker_max_failures))
    for _ in range(threshold):
        with pytest.raises(DatabaseError):
            await _broken()

    assert manager._breaker.state == "open", (
        "настоящие отказы БД обязаны открывать circuit breaker"
    )
    await async_engine.dispose()
