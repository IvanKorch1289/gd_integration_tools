"""Тесты :class:`SecretBrokerImpl` (V15 S1+S3 DoD)."""

from __future__ import annotations

import pytest

from src.backend.infrastructure.secrets.broker import SecretBrokerImpl, SecretValue


class _FakeBackend:
    def __init__(self) -> None:
        self.versions: dict[str, list[SecretValue]] = {}

    def push(self, snapshot: SecretValue) -> None:
        self.versions.setdefault(snapshot.name, []).append(snapshot)

    def get(self, name: str) -> SecretValue:
        return self.versions[name][-1]

    def get_versioned(self, name: str, version: int) -> SecretValue:
        if version <= 0:
            return self.versions[name][-1]
        for snap in self.versions[name]:
            if snap.version == version:
                return snap
        raise KeyError((name, version))


def test_get_secret_returns_current_version() -> None:
    backend = _FakeBackend()
    backend.push(SecretValue(name="db/pg", value="v1", version=1))
    backend.push(SecretValue(name="db/pg", value="v2", version=2))
    broker = SecretBrokerImpl(backend=backend)
    assert broker.get_secret("db/pg").value == "v2"


def test_get_versioned_returns_explicit_version() -> None:
    backend = _FakeBackend()
    backend.push(SecretValue(name="db/pg", value="v1", version=1))
    backend.push(SecretValue(name="db/pg", value="v2", version=2))
    broker = SecretBrokerImpl(backend=backend)
    assert broker.get_versioned("db/pg", 1).value == "v1"


def test_capability_check_invoked_on_get() -> None:
    """``capability_check`` получает (plugin, 'secrets.read', name)."""
    seen: list[tuple[str, str, str | None]] = []

    def fake_check(plugin: str, capability: str, scope: str | None) -> None:
        seen.append((plugin, capability, scope))

    backend = _FakeBackend()
    backend.push(SecretValue(name="db/pg", value="x"))
    broker = SecretBrokerImpl(backend=backend, capability_check=fake_check)
    broker.get_secret("db/pg")
    assert seen == [("core", "secrets.read", "db/pg")]


def test_capability_denied_propagates() -> None:
    class _Denied(Exception):
        pass

    def deny(*_args: object) -> None:
        raise _Denied()

    backend = _FakeBackend()
    backend.push(SecretValue(name="db/pg", value="x"))
    broker = SecretBrokerImpl(backend=backend, capability_check=deny)
    with pytest.raises(_Denied):
        broker.get_secret("db/pg")


def test_subscribe_rotation_receives_callback() -> None:
    backend = _FakeBackend()
    backend.push(SecretValue(name="db/pg", value="v2", version=2))
    broker = SecretBrokerImpl(backend=backend)

    received: list[SecretValue] = []
    broker.subscribe_rotation("db/pg", received.append)
    broker.notify_rotation(SecretValue(name="db/pg", value="v3", version=3))
    assert received == [SecretValue(name="db/pg", value="v3", version=3)]


def test_unsubscribe_removes_callback() -> None:
    backend = _FakeBackend()
    broker = SecretBrokerImpl(backend=backend)

    received: list[SecretValue] = []
    broker.subscribe_rotation("db/pg", received.append)
    broker.unsubscribe_rotation("db/pg", received.append)
    broker.notify_rotation(SecretValue(name="db/pg", value="v3", version=3))
    assert received == []


def test_failing_subscriber_does_not_break_others() -> None:
    backend = _FakeBackend()
    broker = SecretBrokerImpl(backend=backend)

    def bad(_snap: SecretValue) -> None:
        raise RuntimeError("nope")

    delivered: list[SecretValue] = []
    broker.subscribe_rotation("db/pg", bad)
    broker.subscribe_rotation("db/pg", delivered.append)
    broker.notify_rotation(SecretValue(name="db/pg", value="v3", version=3))
    assert delivered == [SecretValue(name="db/pg", value="v3", version=3)]
