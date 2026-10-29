"""ADR-0393 — лимит выборки и аудит доступа к данным у DSL-БД-шагов.

Закрывает дефекты волны 18:

* **(7)** ``fetchall()`` / ``mappings().all()`` без ограничения — один
  ``SELECT * FROM big_table`` вытягивал в память процесса весь результат;
* **(8)** доступ к данным не порождал ни одного audit-события.

Тесты против настоящего SQLite (aiosqlite) — лимит проверяется на
фактическом результате, а не на моке.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.backend.dsl.engine.context import ExecutionContext  # noqa: E402
from src.backend.dsl.engine.exchange import Exchange  # noqa: E402
from src.backend.dsl.engine.processors._sql_validation import (  # noqa: E402
    MAX_RESULT_ROWS,
    limit_rows,
)

pytestmark = pytest.mark.unit


class _SessionManager:
    """Мини-менеджер сессий с семантикой реального ``create_session()``."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def create_session(self) -> Any:
        """Открывает сессию (без коммита — только явный ``session.commit()``)."""
        async with self._session_factory() as session:
            yield session


@pytest.fixture
async def sqlite_engine() -> AsyncEngine:
    """Настоящий SQLite-engine с таблицей ``widgets``."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(
            text("CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT)")
        )
        for index in range(10):
            await conn.execute(
                text("INSERT INTO widgets (id, name) VALUES (:id, :name)"),
                {"id": index, "name": f"w{index}"},
            )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(sqlite_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика async-сессий поверх SQLite-engine."""
    return async_sessionmaker(sqlite_engine, expire_on_commit=False)


# ── (7) лимит выборки ─────────────────────────────────────────────────────


def test_limit_rows_truncates_and_reports() -> None:
    """``limit_rows`` обрезает список и сообщает об обрезке."""
    rows, truncated = limit_rows([1, 2, 3], limit=2)

    assert rows == [1, 2]
    assert truncated is True


def test_limit_rows_keeps_short_result() -> None:
    """Результат короче лимита — без обрезки."""
    rows, truncated = limit_rows([1], limit=5)

    assert rows == [1]
    assert truncated is False


def test_limit_rows_zero_means_no_limit() -> None:
    """``limit <= 0`` — ограничение выключено."""
    rows, truncated = limit_rows([1, 2, 3], limit=0)

    assert rows == [1, 2, 3]
    assert truncated is False


def test_default_max_rows_is_positive() -> None:
    """Лимит по умолчанию задан и положителен."""
    assert MAX_RESULT_ROWS > 0


async def test_db_query_external_truncates_result(
    sqlite_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``db_query_external`` режет выборку до ``max_rows``."""
    from src.backend.dsl.engine.processors.db_query_external import (
        ExternalDbQueryProcessor,
    )

    manager = _SessionManager(session_factory)
    monkeypatch.setattr(
        "src.backend.core.di.providers.get_external_session_manager_provider",
        lambda: lambda profile: manager,
    )

    processor = ExternalDbQueryProcessor(
        profile="sqlite_probe", sql="SELECT id, name FROM widgets", max_rows=3
    )
    exchange = Exchange()
    exchange.in_message.body = {}

    await processor.process(exchange, ExecutionContext())

    rows = exchange.get_property("db_result")
    assert isinstance(rows, list)
    assert len(rows) == 3


async def test_db_query_external_emits_audit_event(
    sqlite_engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Доступ к данным порождает audit-событие без значений данных."""
    from src.backend.dsl.engine.processors.db_query_external import (
        ExternalDbQueryProcessor,
    )

    manager = _SessionManager(session_factory)
    monkeypatch.setattr(
        "src.backend.core.di.providers.get_external_session_manager_provider",
        lambda: lambda profile: manager,
    )
    captured: list[dict[str, Any]] = []

    def _capture(**kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(
        "src.backend.core.audit.facade.emit_audit", _capture, raising=False
    )

    processor = ExternalDbQueryProcessor(
        profile="sqlite_probe", sql="SELECT id, name FROM widgets"
    )
    exchange = Exchange()
    exchange.in_message.body = {}

    await processor.process(exchange, ExecutionContext())

    assert captured, "audit-событие доступа к данным не эмитилось"
    event = captured[-1]
    assert event["event"] == "db.read"
    assert event["resource"] == "sqlite_probe"
    assert event["details"]["capability"] == "db.read"
    # Значений данных в событии нет.
    assert "rows" not in str(event)
