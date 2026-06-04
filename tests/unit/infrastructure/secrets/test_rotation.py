"""Тесты :class:`RotationScheduler` (V15 S3 DoD)."""

from __future__ import annotations

import pytest

from src.backend.infrastructure.secrets.broker import SecretBrokerImpl, SecretValue
from src.backend.infrastructure.secrets.rotation import RotationScheduler


class _FakeBackend:
    def __init__(self, snapshots: list[SecretValue]) -> None:
        self._by_version: dict[int, SecretValue] = {s.version: s for s in snapshots}

    def get(self, name: str) -> SecretValue:
        return max(self._by_version.values(), key=lambda s: s.version)

    def get_versioned(self, name: str, version: int) -> SecretValue:
        return self._by_version[version]


@pytest.mark.asyncio
async def test_poll_once_notifies_on_version_change() -> None:
    backend = _FakeBackend(
        [
            SecretValue(name="db/pg", value="v1", version=1),
            SecretValue(name="db/pg", value="v2", version=2),
        ]
    )
    broker = SecretBrokerImpl(backend=backend)

    received: list[SecretValue] = []
    broker.subscribe_rotation("db/pg", received.append)

    versions = iter([1, 2])
    scheduler = RotationScheduler(
        broker=broker,
        watched_secrets=["db/pg"],
        version_fetcher=lambda _name: next(versions),
    )

    # Первый проход: устанавливает baseline (никаких подписчиков).
    rotated = await scheduler.poll_once()
    assert rotated == 0
    assert received == []

    # Второй проход: обнаруживает new version → notify.
    rotated = await scheduler.poll_once()
    assert rotated == 1
    assert received[-1].version == 2


@pytest.mark.asyncio
async def test_poll_once_skips_when_version_stable() -> None:
    backend = _FakeBackend([SecretValue(name="db/pg", value="v1", version=1)])
    broker = SecretBrokerImpl(backend=backend)
    received: list[SecretValue] = []
    broker.subscribe_rotation("db/pg", received.append)

    scheduler = RotationScheduler(
        broker=broker, watched_secrets=["db/pg"], version_fetcher=lambda _name: 1
    )
    await scheduler.poll_once()
    await scheduler.poll_once()
    assert received == []


@pytest.mark.asyncio
async def test_add_watch_extends_list_without_restart() -> None:
    backend = _FakeBackend([SecretValue(name="api/key", value="k", version=1)])
    broker = SecretBrokerImpl(backend=backend)
    scheduler = RotationScheduler(
        broker=broker, watched_secrets=[], version_fetcher=lambda _name: 1
    )
    scheduler.add_watch("api/key", current_version=1)
    assert "api/key" in scheduler.known_versions()


@pytest.mark.asyncio
async def test_start_and_stop_lifecycle() -> None:
    """``start()`` создаёт task, ``stop()`` отменяет его."""
    backend = _FakeBackend([SecretValue(name="db/pg", value="v1", version=1)])
    broker = SecretBrokerImpl(backend=backend)
    scheduler = RotationScheduler(
        broker=broker,
        watched_secrets=["db/pg"],
        version_fetcher=lambda _name: 1,
        poll_interval_seconds=0.01,
    )
    await scheduler.start()
    await scheduler.stop()
    # Идемпотентность: повторный stop не падает.
    await scheduler.stop()
