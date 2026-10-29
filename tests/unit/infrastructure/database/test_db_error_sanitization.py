"""Wave 16 / X4: PII параметров запроса не должна утекать в ошибки БД.

SQLAlchemy дописывает в текст исключения блок с фактическими значениями
параметров::

    (sqlite3.IntegrityError) UNIQUE constraint failed: pii_users.email
    [SQL: INSERT INTO pii_users (email) VALUES (?)]
    [parameters: ('ivan@example.com',)]

Этот текст уезжал в ``exchange.error`` (через ``DatabaseError``) и в лог
(``exc_info``). После правки блок параметров маскируется в точке
формирования DB-ошибки: ``session_manager`` и ``listeners``.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytest.importorskip("aiosqlite")

from src.backend.core.errors import DatabaseError  # noqa: E402
from src.backend.infrastructure.database.listeners import (  # noqa: E402
    DatabaseListener,
    sanitize_db_error_text,
)
from src.backend.infrastructure.database.session_manager import (  # noqa: E402
    DatabaseSessionManager,
)

EMAIL = "ivan@example.com"


# ── чистый helper ───────────────────────────────────────────────────────


def test_sanitize_masks_parameter_values() -> None:
    """Блок ``[parameters: ...]`` заменяется на маску, SQL сохраняется."""
    raw = (
        "(sqlite3.IntegrityError) UNIQUE constraint failed: pii_users.email\n"
        "[SQL: INSERT INTO pii_users (email) VALUES (?)]\n"
        "[parameters: ('ivan@example.com',)]"
    )
    sanitized = sanitize_db_error_text(raw)

    assert EMAIL not in sanitized
    assert "INSERT INTO pii_users" in sanitized
    assert "[parameters: ***]" in sanitized


def test_sanitize_keeps_text_without_parameters() -> None:
    """Текст без параметров не меняется (диагностика не теряется)."""
    raw = "(sqlite3.OperationalError) no such table: pii_users"
    assert sanitize_db_error_text(raw) == raw


# ── session_manager: текст ошибки наружу ────────────────────────────────


@pytest_asyncio.fixture
async def sqlite_manager(tmp_path: Any) -> AsyncSession:
    """Session manager поверх временной aiosqlite-БД.

    Yields:
        Готовый менеджер сессий.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    db_file = tmp_path / "pii.db"
    async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    maker = async_sessionmaker(
        bind=async_engine, class_=AsyncSession, expire_on_commit=False
    )
    manager = DatabaseSessionManager(session_maker=maker, db_name="pii")
    try:
        yield manager
    finally:
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_database_error_message_has_no_pii(sqlite_manager: Any) -> None:
    """``DatabaseError`` наружу не содержит значения параметров.

    Args:
        sqlite_manager: Менеджер сессий поверх aiosqlite.
    """
    async with sqlite_manager.create_session() as session:
        await session.execute(
            text("CREATE TABLE pii_users (id INTEGER PRIMARY KEY, email TEXT UNIQUE)")
        )
        await session.commit()

    @sqlite_manager.connection()
    async def _insert(session: AsyncSession) -> int:
        # Неизвестная колонка → OperationalError (не IntegrityError):
        # проверяем общий путь обёртки в DatabaseError.
        await session.execute(
            text("INSERT INTO pii_users (id, email, nope) VALUES (:id, :email, 1)"),
            {"id": 2, "email": EMAIL},
        )
        return 1

    with pytest.raises(DatabaseError) as exc_info:
        await _insert()

    message = str(exc_info.value)
    assert EMAIL not in message, f"PII в тексте ошибки БД: {message}"
    assert "INSERT INTO pii_users" in message, "диагностика SQL потеряна"


@pytest.mark.asyncio
async def test_integrity_error_has_no_pii(sqlite_manager: Any) -> None:
    """``IntegrityError`` пробрасывается без значений параметров.

    Args:
        sqlite_manager: Менеджер сессий поверх aiosqlite.
    """
    async with sqlite_manager.create_session() as session:
        await session.execute(
            text("CREATE TABLE pii_users (id INTEGER PRIMARY KEY, email TEXT UNIQUE)")
        )
        await session.execute(
            text("INSERT INTO pii_users (id, email) VALUES (1, 'ivan@example.com')")
        )
        await session.commit()

    @sqlite_manager.connection()
    async def _insert(session: AsyncSession) -> int:
        await session.execute(
            text("INSERT INTO pii_users (id, email) VALUES (:id, :email)"),
            {"id": 2, "email": EMAIL},
        )
        return 1

    with pytest.raises(IntegrityError) as exc_info:
        await _insert()

    message = str(exc_info.value)
    assert EMAIL not in message, f"PII в тексте ошибки БД: {message}"
    assert "INSERT INTO pii_users" in message, "диагностика SQL потеряна"


@pytest.mark.asyncio
async def test_database_error_log_has_no_pii(
    sqlite_manager: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """В лог БД не уходят значения параметров запроса.

    Args:
        sqlite_manager: Менеджер сессий поверх aiosqlite.
        caplog: Захват логов pytest.
    """
    async with sqlite_manager.create_session() as session:
        await session.execute(
            text("CREATE TABLE pii_users (id INTEGER PRIMARY KEY, email TEXT UNIQUE)")
        )
        await session.commit()

    @sqlite_manager.connection()
    async def _insert(session: AsyncSession) -> int:
        await session.execute(
            text("INSERT INTO pii_users (id, email, nope) VALUES (:id, :email, 1)"),
            {"id": 2, "email": EMAIL},
        )
        return 1

    with caplog.at_level(logging.ERROR, logger="database"):
        with pytest.raises(DatabaseError):
            await _insert()

    assert EMAIL not in caplog.text, "PII просочилась в лог БД"


# ── listeners: handle_error ──────────────────────────────────────────────


@pytest.fixture
def captured_handlers() -> Any:
    """Перехватывает регистрацию SQLAlchemy listeners.

    Yields:
        Список пар ``(event_name, handler)``.
    """
    handlers: list[tuple[str, object]] = []

    def fake_listens_for(
        target: object, identifier: str, *args: object, **kw: object
    ) -> object:
        if args and callable(args[0]):
            handlers.append((identifier, args[0]))
            return lambda: None

        def decorator(fn: object) -> object:
            handlers.append((identifier, fn))
            return fn

        return decorator

    with patch("sqlalchemy.event.listens_for", side_effect=fake_listens_for):
        yield handlers


def test_handle_error_log_has_no_pii(
    captured_handlers: list[tuple[str, object]], caplog: pytest.LogCaptureFixture
) -> None:
    """``handle_error`` не логирует значения параметров запроса.

    Args:
        captured_handlers: Перехваченные SQLAlchemy handlers.
        caplog: Захват логов pytest.
    """
    engine = MagicMock()
    engine.sync_engine = MagicMock()
    DatabaseListener(async_engine=engine, db_name="pg_prod", slow_query_threshold=0.5)

    error_handler = next(fn for name, fn in captured_handlers if name == "handle_error")

    original = IntegrityError(
        "INSERT INTO pii_users (email) VALUES (?)",
        {"email": EMAIL},
        Exception("UNIQUE constraint failed: pii_users.email"),
    )
    ctx = MagicMock()
    ctx.is_disconnect = False
    ctx.statement = "INSERT INTO pii_users (email) VALUES (?)"
    ctx.original_exception = original

    with caplog.at_level(logging.ERROR, logger="database"):
        error_handler(ctx)

    assert EMAIL not in caplog.text, "PII просочилась в лог драйвера БД"
