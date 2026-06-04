"""Unit-тесты SmartSessionManager (S11 K2 W2).

Покрывает:
    1. read_routes_to_replica — read-mode → replica sessionmaker.
    2. write_routes_to_primary — write-mode → primary sessionmaker.
    3. no_replica_falls_back — replica=None → всегда primary.
    4. breaker_opens_on_failures — N подряд ошибок → breaker open → primary.
    5. breaker_recovers — успех на replica сбрасывает счётчик.
    6. breaker_cooldown_blocks_replica — пока cooldown активен, replica не используется.
    7. session_closed_on_exit — session.close вызывается даже при исключении.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from src.backend.infrastructure.database.smart_session_manager import (
    SmartSessionManager,
)


class _FakeSession:
    """Минимальный stub async-session для тестов SmartSessionManager."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeSessionMaker:
    """Фабрика, возвращающая помеченный label'ом :class:`_FakeSession`."""

    def __init__(self, label: str, *, fail_on_create: bool = False) -> None:
        self.label = label
        self.fail_on_create = fail_on_create
        self.calls = 0

    def __call__(self) -> _FakeSession:
        self.calls += 1
        if self.fail_on_create:
            raise RuntimeError(f"{self.label} create failed")
        return _FakeSession(self.label)


@pytest.mark.asyncio
async def test_read_routes_to_replica() -> None:
    """read-mode идёт на replica при её наличии."""
    primary = _FakeSessionMaker("primary")
    replica = _FakeSessionMaker("replica")
    sm = SmartSessionManager(primary_sessionmaker=primary, replica_sessionmaker=replica)

    async with sm.acquire(mode="read") as session:
        assert isinstance(session, _FakeSession)
        assert session.label == "replica"
    assert replica.calls == 1
    assert primary.calls == 0


@pytest.mark.asyncio
async def test_write_routes_to_primary() -> None:
    """write-mode игнорирует replica и идёт на primary."""
    primary = _FakeSessionMaker("primary")
    replica = _FakeSessionMaker("replica")
    sm = SmartSessionManager(primary_sessionmaker=primary, replica_sessionmaker=replica)

    async with sm.acquire(mode="write") as session:
        assert session.label == "primary"
    assert primary.calls == 1
    assert replica.calls == 0


@pytest.mark.asyncio
async def test_no_replica_falls_back_to_primary() -> None:
    """При replica_sessionmaker=None все mode идут на primary."""
    primary = _FakeSessionMaker("primary")
    sm = SmartSessionManager(primary_sessionmaker=primary, replica_sessionmaker=None)

    async with sm.acquire(mode="read") as session:
        assert session.label == "primary"
    async with sm.acquire(mode="write") as session:
        assert session.label == "primary"
    assert primary.calls == 2
    assert sm.has_replica is False


@pytest.mark.asyncio
async def test_breaker_opens_on_consecutive_failures() -> None:
    """N подряд ошибок replica → breaker open → дальнейшие read идут на primary."""
    primary = _FakeSessionMaker("primary")
    replica = _FakeSessionMaker("replica")
    sm = SmartSessionManager(
        primary_sessionmaker=primary,
        replica_sessionmaker=replica,
        failure_threshold=2,
        cooldown_seconds=30.0,
    )

    # Имитируем ошибки запросов на replica.
    for _ in range(2):
        with pytest.raises(RuntimeError):
            async with sm.acquire(mode="read"):
                raise RuntimeError("query failed on replica")

    assert sm.replica_breaker_open is True
    # Следующий read должен пойти на primary.
    async with sm.acquire(mode="read") as session:
        assert session.label == "primary"


@pytest.mark.asyncio
async def test_breaker_recovers_on_success() -> None:
    """Успешная операция на replica сбрасывает счётчик failures."""
    primary = _FakeSessionMaker("primary")
    replica = _FakeSessionMaker("replica")
    sm = SmartSessionManager(
        primary_sessionmaker=primary, replica_sessionmaker=replica, failure_threshold=3
    )
    # 1 ошибка — счётчик 1, breaker всё ещё closed.
    with pytest.raises(RuntimeError):
        async with sm.acquire(mode="read"):
            raise RuntimeError("fail")
    # Успех — счётчик сбрасывается.
    async with sm.acquire(mode="read") as session:
        assert session.label == "replica"
    # После ещё 2 ошибок breaker всё ещё closed (счётчик 2 < threshold 3).
    for _ in range(2):
        with pytest.raises(RuntimeError):
            async with sm.acquire(mode="read"):
                raise RuntimeError("fail")
    assert sm.replica_breaker_open is False


@pytest.mark.asyncio
async def test_breaker_cooldown_blocks_replica() -> None:
    """Пока breaker open, replica не выбирается."""
    primary = _FakeSessionMaker("primary")
    replica = _FakeSessionMaker("replica")
    sm = SmartSessionManager(
        primary_sessionmaker=primary,
        replica_sessionmaker=replica,
        failure_threshold=1,
        cooldown_seconds=60.0,
    )
    # Одна ошибка → breaker open (threshold=1).
    with pytest.raises(RuntimeError):
        async with sm.acquire(mode="read"):
            raise RuntimeError("fail")
    assert sm.replica_breaker_open

    # В cooldown — read идёт на primary, replica.calls не увеличивается.
    pre_replica_calls = replica.calls
    async with sm.acquire(mode="read") as session:
        assert session.label == "primary"
    assert replica.calls == pre_replica_calls


@pytest.mark.asyncio
async def test_session_closed_on_exit_and_on_exception() -> None:
    """session.close() вызывается и на нормальном exit, и при исключении."""
    primary = _FakeSessionMaker("primary")
    sm = SmartSessionManager(primary_sessionmaker=primary)

    captured: list[_FakeSession] = []

    # Нормальный exit.
    async with sm.acquire(mode="write") as session:
        captured.append(session)
    assert captured[-1].closed is True

    # Exit с исключением.
    with pytest.raises(ValueError):
        async with sm.acquire(mode="read") as session:
            captured.append(session)
            raise ValueError("boom")
    assert captured[-1].closed is True
