"""ADR-0387: graceful-degradation ``initialize_async_pool`` при недоступной БД.

Контракт тот же, что у соседнего sync-пула (движок → ``None`` + warning,
старт не падает): прогрев асинхронного пула — best-effort. SQLAlchemy
``OperationalError`` (БД недоступна, отказ старта Postgres, таймаут
соединения) не должен ронять старт приложения невнятным трейсбеком —
ошибка логируется (warning), уже открытые соединения закрываются, пул
остаётся «холодным» и прогреется лениво при первом запросе.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.enums.database import DatabaseTypeChoices
from src.backend.infrastructure.database.database.initializer import DatabaseInitializer

pytestmark = pytest.mark.unit


def _make_initializer(*, pool_size: int = 2) -> DatabaseInitializer:
    """Создаёт инициализатор на sqlite in-memory (aiosqlite — hard dep).

    Args:
        pool_size: Размер пула (сколько соединений прогревает warmup).

    Returns:
        Готовый инициализатор с рабочим async/sync engine.

    """
    settings = DatabaseConnectionSettings(
        type=DatabaseTypeChoices.sqlite,
        path=":memory:",
        pool_size=pool_size,
        max_overflow=0,
        pool_recycle=3600,
        pool_timeout=30,
        # Профили конфигурации по умолчанию несут PG-настройки SSL —
        # для sqlite они недопустимы (model_validator ``validate_ssl``).
        ssl_mode=None,
        ca_bundle=None,
    )
    return DatabaseInitializer(settings=settings, name="probe")


def _operational_error() -> OperationalError:
    """Строит ``OperationalError`` как при недоступной БД."""
    return OperationalError(
        "SELECT 1",
        {},
        Exception("connection refused"),
    )


class _StubConnection:
    """Минимальное соединение для прогрева пула."""

    def __init__(self) -> None:
        """Инициализирует стаб соединения."""
        self.closed = False

    async def close(self) -> None:
        """Помечает соединение закрытым."""
        self.closed = True


class _FailingCloseConnection(_StubConnection):
    """Соединение, ``close()`` которого падает."""

    async def close(self) -> None:
        """Имитирует ошибку закрытия соединения.

        Raises:
            RuntimeError: Всегда — ошибка закрытия битого соединения.

        """
        raise RuntimeError("close failed")


class TestAsyncPoolGracefulDegradation:
    """Прогрев пула не должен ронять старт приложения."""

    @pytest.mark.asyncio
    async def test_operational_error_does_not_raise(self, monkeypatch) -> None:
        """``OperationalError`` → деградация без исключения.

        Raises:
            OperationalError: Если деградация не сработала (тест упал).

        """
        initializer = _make_initializer()

        def _boom(self: Any, *args: Any, **kwargs: Any) -> Any:
            raise _operational_error()

        monkeypatch.setattr(AsyncEngine, "connect", _boom)

        await initializer.initialize_async_pool()

        assert initializer.async_engine is not None
        assert initializer.get_async_engine() is initializer.async_engine

    @pytest.mark.asyncio
    async def test_operational_error_logs_warning(self, monkeypatch, caplog) -> None:
        """Деградация логируется на уровне ``warning`` (как sync-пул).

        Raises:
            AssertionError: Если warning не зафиксирован.

        """
        caplog.set_level(logging.WARNING)
        initializer = _make_initializer()

        def _boom(self: Any, *args: Any, **kwargs: Any) -> Any:
            raise _operational_error()

        monkeypatch.setattr(AsyncEngine, "connect", _boom)

        await initializer.initialize_async_pool()

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "прогреть асинхронный пул" in r.getMessage() for r in warnings
        ), "не залогирован warning о неудачном прогреве пула"

    @pytest.mark.asyncio
    async def test_operational_error_closes_opened_connections(
        self, monkeypatch
    ) -> None:
        """Частично открытые соединения закрываются при деградации.

        Raises:
            AssertionError: Если соединение осталось открытым.

        """
        initializer = _make_initializer(pool_size=2)
        opened: list[_StubConnection] = []

        async def _connect(self: Any) -> Any:
            if opened:
                raise _operational_error()
            conn = _StubConnection()
            opened.append(conn)
            return conn

        monkeypatch.setattr(AsyncEngine, "connect", _connect)

        await initializer.initialize_async_pool()

        assert len(opened) == 1
        assert opened[0].closed, "соединение не закрыто при деградации"

    @pytest.mark.asyncio
    async def test_close_failure_does_not_escape(self, monkeypatch) -> None:
        """Ошибка закрытия битого соединения не пробивает деградацию.

        Raises:
            RuntimeError: Если ошибка закрытия утекла наружу (тест упал).

        """
        initializer = _make_initializer(pool_size=2)
        opened: list[_StubConnection] = []

        async def _connect(self: Any) -> Any:
            if opened:
                raise _operational_error()
            conn = _FailingCloseConnection()
            opened.append(conn)
            return conn

        monkeypatch.setattr(AsyncEngine, "connect", _connect)

        await initializer.initialize_async_pool()

        assert len(opened) == 1

    @pytest.mark.asyncio
    async def test_os_error_still_degrades(self, monkeypatch) -> None:
        """``OSError`` (сеть недоступна) деградирует так же, как раньше.

        Raises:
            OSError: Если деградация не сработала (тест упал).

        """
        initializer = _make_initializer()

        def _boom(self: Any, *args: Any, **kwargs: Any) -> Any:
            raise OSError("network unreachable")

        monkeypatch.setattr(AsyncEngine, "connect", _boom)

        await initializer.initialize_async_pool()

        assert initializer.async_engine is not None
