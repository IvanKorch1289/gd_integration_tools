"""Тесты LongRunningSecretRotator (Sprint 4 Wave E)."""
# ruff: noqa: S101

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

from src.backend.infrastructure.secrets.long_running_rotation import (
    LongRunningSecretRotator,
)


class _FakeBackend:
    """Минимальный fake-backend секретов для unit-тестов."""

    def __init__(self, values: Iterator[Any]) -> None:
        self._values = iter(values)
        self.call_count = 0

    def get(self, name: str) -> Any:
        self.call_count += 1
        return next(self._values)


class _Clock:
    """Управляемый источник времени для тестов."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_first_fetch_reads_backend() -> None:
    """Первый вызов fetch_with_rotation читает backend и кеширует значение."""
    backend = _FakeBackend(iter(["secret_v1"]))
    clock = _Clock()
    rotator = LongRunningSecretRotator(
        backend, "secret/db", refresh_interval_s=60.0, time_source=clock
    )
    value = asyncio.run(rotator.fetch_with_rotation())
    assert value == "secret_v1"
    assert backend.call_count == 1


def test_no_refresh_within_interval() -> None:
    """Повторные вызовы внутри интервала возвращают кеш без backend-вызовов."""
    backend = _FakeBackend(iter(["v1", "v2"]))
    clock = _Clock()
    rotator = LongRunningSecretRotator(
        backend, "secret/db", refresh_interval_s=60.0, time_source=clock
    )

    async def _run() -> tuple[Any, Any]:
        a = await rotator.fetch_with_rotation()
        clock.advance(30.0)  # внутри интервала
        b = await rotator.fetch_with_rotation()
        return a, b

    a, b = asyncio.run(_run())
    assert a == "v1"
    assert b == "v1"
    assert backend.call_count == 1


def test_rotation_refresh_after_interval() -> None:
    """После истечения интервала — повторный fetch обновляет кеш."""
    backend = _FakeBackend(iter(["v1", "v2"]))
    clock = _Clock()
    rotator = LongRunningSecretRotator(
        backend, "secret/db", refresh_interval_s=60.0, time_source=clock
    )

    async def _run() -> tuple[Any, Any]:
        a = await rotator.fetch_with_rotation()
        clock.advance(120.0)  # больше интервала
        b = await rotator.fetch_with_rotation()
        return a, b

    a, b = asyncio.run(_run())
    assert a == "v1"
    assert b == "v2"
    assert backend.call_count == 2


def test_invalidate_clears_cache() -> None:
    """invalidate() сбрасывает кеш — следующий fetch принудительно идёт в backend."""
    backend = _FakeBackend(iter(["v1", "v2"]))
    rotator = LongRunningSecretRotator(backend, "secret/db", refresh_interval_s=600.0)

    async def _run() -> tuple[Any, Any]:
        a = await rotator.fetch_with_rotation()
        await rotator.invalidate()
        b = await rotator.fetch_with_rotation()
        return a, b

    a, b = asyncio.run(_run())
    assert a == "v1"
    assert b == "v2"
    assert backend.call_count == 2


def test_heartbeat_called_on_refresh() -> None:
    """heartbeat-callback вызывается после refresh."""
    backend = _FakeBackend(iter(["v1"]))
    heartbeat_calls: list[int] = []

    def _heartbeat() -> None:
        heartbeat_calls.append(1)

    rotator = LongRunningSecretRotator(
        backend, "secret/db", refresh_interval_s=60.0, heartbeat=_heartbeat
    )
    asyncio.run(rotator.fetch_with_rotation())
    assert heartbeat_calls == [1]


def test_async_heartbeat_supported() -> None:
    """Async heartbeat корректно await'ится."""
    backend = _FakeBackend(iter(["v1"]))
    heartbeat_calls: list[int] = []

    async def _heartbeat() -> None:
        heartbeat_calls.append(1)

    rotator = LongRunningSecretRotator(
        backend, "secret/db", refresh_interval_s=60.0, heartbeat=_heartbeat
    )
    asyncio.run(rotator.fetch_with_rotation())
    assert heartbeat_calls == [1]


def test_invalid_refresh_interval_raises() -> None:
    """refresh_interval_s ≤ 0 → ValueError."""
    backend = _FakeBackend(iter(["v1"]))
    with pytest.raises(ValueError):
        LongRunningSecretRotator(backend, "x", refresh_interval_s=0.0)
    with pytest.raises(ValueError):
        LongRunningSecretRotator(backend, "x", refresh_interval_s=-1.0)
