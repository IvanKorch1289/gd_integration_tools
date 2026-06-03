"""Unit tests for src.backend.infrastructure.registry."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.infrastructure.registry import (
    ConnectorAlreadyRegisteredError,
    ConnectorNotRegisteredError,
    ConnectorRegistry,
    ConnectorSpec,
    get_registry,
)


@pytest.fixture(autouse=True)
def _reset_registry() -> Iterator[None]:
    ConnectorRegistry.reset()
    yield
    ConnectorRegistry.reset()


def _fake_client(name: str) -> MagicMock:
    client = MagicMock()
    client.name = name
    client.start = AsyncMock()
    client.stop = AsyncMock()
    client.health = AsyncMock()
    client.reload = AsyncMock()
    client.pooling.acquire_timeout_s = 5.0
    return client


class TestSingleton:
    def test_instance_creates_once(self) -> None:
        r1 = ConnectorRegistry.instance()
        r2 = ConnectorRegistry.instance()
        assert r1 is r2

    def test_reset(self) -> None:
        r1 = ConnectorRegistry.instance()
        ConnectorRegistry.reset()
        r2 = ConnectorRegistry.instance()
        assert r1 is not r2

    def test_get_registry(self) -> None:
        assert isinstance(get_registry(), ConnectorRegistry)


class TestRegistration:
    def test_register_and_get(self) -> None:
        reg = ConnectorRegistry.instance()
        client = _fake_client("redis")
        reg.register(client)
        assert reg.get("redis") is client

    def test_register_duplicate_raises(self) -> None:
        reg = ConnectorRegistry.instance()
        client = _fake_client("db")
        reg.register(client)
        with pytest.raises(ConnectorAlreadyRegisteredError):
            reg.register(client)

    def test_register_with_vault_path(self) -> None:
        reg = ConnectorRegistry.instance()
        client = _fake_client("pg")
        reg.register(client, vault_path="secret/db")
        assert reg.vault_path("pg") == "secret/db"

    def test_unregister(self) -> None:
        reg = ConnectorRegistry.instance()
        client = _fake_client("redis")
        reg.register(client)
        reg.unregister("redis")
        with pytest.raises(ConnectorNotRegisteredError):
            reg.get("redis")

    def test_unregister_unknown_noop(self) -> None:
        reg = ConnectorRegistry.instance()
        reg.unregister("nobody")  # should not raise

    def test_get_unknown_raises(self) -> None:
        reg = ConnectorRegistry.instance()
        with pytest.raises(ConnectorNotRegisteredError):
            reg.get("missing")

    def test_names_order(self) -> None:
        reg = ConnectorRegistry.instance()
        c1 = _fake_client("a")
        c2 = _fake_client("b")
        reg.register(c1)
        reg.register(c2)
        assert reg.names() == ["a", "b"]

    def test_names_empty(self) -> None:
        reg = ConnectorRegistry.instance()
        assert reg.names() == []

    def test_vault_path_none(self) -> None:
        reg = ConnectorRegistry.instance()
        client = _fake_client("x")
        reg.register(client)
        assert reg.vault_path("x") is None

    def test_vault_path_unknown(self) -> None:
        reg = ConnectorRegistry.instance()
        assert reg.vault_path("x") is None


class TestConnectorSpec:
    def test_defaults(self) -> None:
        client = _fake_client("c")
        spec = ConnectorSpec(client=client)
        assert spec.client is client
        assert spec.vault_path is None
        assert spec.register_order == 0


@pytest.mark.asyncio
class TestStartAll:
    async def test_start_all_success(self) -> None:
        reg = ConnectorRegistry.instance()
        c1 = _fake_client("a")
        c2 = _fake_client("b")
        reg.register(c1)
        reg.register(c2)
        await reg.start_all()
        c1.start.assert_awaited_once()
        c2.start.assert_awaited_once()

    async def test_start_all_rollback(self) -> None:
        reg = ConnectorRegistry.instance()
        c1 = _fake_client("a")
        c2 = _fake_client("b")
        c2.start = AsyncMock(side_effect=RuntimeError("boom"))
        reg.register(c1)
        reg.register(c2)
        with pytest.raises(RuntimeError, match="boom"):
            await reg.start_all()
        c1.start.assert_awaited_once()
        c1.stop.assert_awaited_once()
        c2.start.assert_awaited_once()
        c2.stop.assert_not_awaited()


@pytest.mark.asyncio
class TestStopAll:
    async def test_stop_all_reverse_order(self) -> None:
        reg = ConnectorRegistry.instance()
        c1 = _fake_client("a")
        c2 = _fake_client("b")
        reg.register(c1)
        reg.register(c2)
        await reg.stop_all()
        # reversed order: b then a
        assert reg._connectors["b"].client.stop.await_args_list == [()]  # type: ignore[attr-defined]
        assert reg._connectors["a"].client.stop.await_args_list == [()]  # type: ignore[attr-defined]

    async def test_stop_all_timeout(self, caplog: pytest.LogCaptureFixture) -> None:
        reg = ConnectorRegistry.instance()
        c1 = _fake_client("a")
        c1.stop = AsyncMock(side_effect=TimeoutError)
        reg.register(c1)
        with caplog.at_level("WARNING"):
            await reg.stop_all()
        assert "timed out" in caplog.text

    async def test_stop_all_error(self, caplog: pytest.LogCaptureFixture) -> None:
        reg = ConnectorRegistry.instance()
        c1 = _fake_client("a")
        c1.stop = AsyncMock(side_effect=ValueError("err"))
        reg.register(c1)
        with caplog.at_level("ERROR"):
            await reg.stop_all()
        assert "errored" in caplog.text


@pytest.mark.asyncio
class TestHealthAll:
    async def test_health_all_ok(self) -> None:
        from src.backend.infrastructure.clients.base_connector import HealthResult

        reg = ConnectorRegistry.instance()
        c1 = _fake_client("a")
        c1.health = AsyncMock(return_value=HealthResult.ok(latency_ms=1.0, mode="fast"))
        reg.register(c1)
        results = await reg.health_all(mode="fast")
        assert results["a"].status == "ok"

    async def test_health_all_exception(self) -> None:
        reg = ConnectorRegistry.instance()
        c1 = _fake_client("a")
        c1.health = AsyncMock(side_effect=ConnectionError("down"))
        reg.register(c1)
        results = await reg.health_all(mode="fast")
        assert results["a"].status == "failed"
        assert results["a"].error is not None
        assert "down" in results["a"].error

    async def test_health_all_empty(self) -> None:
        reg = ConnectorRegistry.instance()
        assert await reg.health_all() == {}


@pytest.mark.asyncio
class TestReload:
    async def test_reload_success(self) -> None:
        reg = ConnectorRegistry.instance()
        c1 = _fake_client("a")
        reg.register(c1)
        ms = await reg.reload("a")
        assert ms >= 0.0
        c1.reload.assert_awaited_once()

    async def test_reload_unknown_raises(self) -> None:
        reg = ConnectorRegistry.instance()
        with pytest.raises(ConnectorNotRegisteredError):
            await reg.reload("missing")

    async def test_reload_concurrent_lock(self) -> None:
        reg = ConnectorRegistry.instance()
        c1 = _fake_client("a")
        reg.register(c1)
        # calling reload twice sequentially should work (lock released between)
        await reg.reload("a")
        await reg.reload("a")
        assert c1.reload.await_count == 2
