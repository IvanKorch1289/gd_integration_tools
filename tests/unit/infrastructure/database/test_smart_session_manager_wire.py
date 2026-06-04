# ruff: noqa: S101
"""Тесты подключения SmartSessionManager к DatabaseBundle (Wave A.4)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.infrastructure.database.database import DatabaseBundle


class _FakeSession:
    """Минимальный stub async-session."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeSessionMaker:
    """Возвращает помеченный :class:`_FakeSession`."""

    def __init__(self, label: str) -> None:
        self.label = label

    def __call__(self) -> _FakeSession:
        return _FakeSession(self.label)


@pytest.mark.asyncio
async def test_bundle_carries_replica_session_maker() -> None:
    """DatabaseBundle прозрачно хранит replica_engine + replica_session_maker."""
    primary_engine = MagicMock(name="primary_engine")
    replica_engine = MagicMock(name="replica_engine")
    primary_smk = _FakeSessionMaker("primary")
    replica_smk = _FakeSessionMaker("replica")

    bundle = DatabaseBundle(
        name="main",
        settings=MagicMock(),
        async_engine=primary_engine,
        async_session_maker=primary_smk,  # type: ignore[arg-type]
        sync_engine=None,
        sync_session_maker=None,
        replica_engine=replica_engine,
        replica_session_maker=replica_smk,  # type: ignore[arg-type]
    )

    assert bundle.replica_engine is replica_engine
    assert bundle.replica_session_maker is replica_smk


@pytest.mark.asyncio
async def test_smart_session_manager_uses_bundle_replica() -> None:
    """SmartSessionManager построенный над bundle.replica_session_maker роутит read→replica."""
    from src.backend.infrastructure.database.smart_session_manager import (
        SmartSessionManager,
    )

    primary_smk = _FakeSessionMaker("primary")
    replica_smk = _FakeSessionMaker("replica")
    manager = SmartSessionManager(
        primary_sessionmaker=primary_smk, replica_sessionmaker=replica_smk
    )

    async with manager.acquire(mode="read") as session:
        assert session.label == "replica"
    async with manager.acquire(mode="write") as session:
        assert session.label == "primary"


@pytest.mark.asyncio
async def test_smart_session_manager_without_replica_falls_back() -> None:
    """Без replica_session_maker manager работает в single-primary режиме."""
    from src.backend.infrastructure.database.smart_session_manager import (
        SmartSessionManager,
    )

    primary_smk = _FakeSessionMaker("primary")
    manager = SmartSessionManager(
        primary_sessionmaker=primary_smk, replica_sessionmaker=None
    )

    async with manager.acquire(mode="read") as session:
        assert session.label == "primary"
    assert manager.has_replica is False


@pytest.mark.asyncio
async def test_smart_session_manager_singleton_uses_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_smart_session_manager() конструирует manager из bundle (с/без replica)."""
    from src.backend.infrastructure.database import database as db_mod

    replica_smk = _FakeSessionMaker("replica")
    primary_smk = _FakeSessionMaker("primary")
    fake_bundle = DatabaseBundle(
        name="main",
        settings=MagicMock(),
        async_engine=MagicMock(),
        async_session_maker=primary_smk,  # type: ignore[arg-type]
        sync_engine=None,
        sync_session_maker=None,
        replica_engine=MagicMock(),
        replica_session_maker=replica_smk,  # type: ignore[arg-type]
    )

    class _FakeInit:
        def as_bundle(self) -> DatabaseBundle:
            return fake_bundle

    monkeypatch.setattr(db_mod, "get_db_initializer", lambda: _FakeInit())
    # lru_cache singleton — сбросим, чтобы тест видел подменённый bundle.
    db_mod.get_smart_session_manager.cache_clear()  # type: ignore[attr-defined]

    manager = db_mod.get_smart_session_manager()
    assert manager.has_replica is True

    async with manager.acquire(mode="read") as session:
        assert session.label == "replica"

    # Очистим singleton после теста, чтобы не утечь fake-bundle в другие тесты.
    db_mod.get_smart_session_manager.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_smart_read_write_depends_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FastAPI Depends-генераторы возвращают соответствующие сессии."""
    from src.backend.infrastructure.database import database as db_mod
    from src.backend.infrastructure.database.session_manager import (
        get_smart_read_session,
        get_smart_write_session,
    )
    from src.backend.infrastructure.database.smart_session_manager import (
        SmartSessionManager,
    )

    primary_smk = _FakeSessionMaker("primary")
    replica_smk = _FakeSessionMaker("replica")

    fake_manager = SmartSessionManager(
        primary_sessionmaker=primary_smk, replica_sessionmaker=replica_smk
    )
    monkeypatch.setattr(db_mod, "get_smart_session_manager", lambda: fake_manager)

    async def _consume(generator: Any) -> Any:
        async for sess in generator:
            return sess
        return None

    read_session = await _consume(get_smart_read_session())
    write_session = await _consume(get_smart_write_session())

    assert read_session.label == "replica"
    assert write_session.label == "primary"
