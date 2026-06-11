"""Unit tests for ChaosEngineering probes (S37.4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.chaos.probes import (
    ChaosEngineering,
    get_chaos_engineering,
    is_chaos_enabled,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset singleton state between tests."""
    from src.backend.infrastructure.chaos import probes

    probes._chaos_instance = None
    yield
    probes._chaos_instance = None


class TestChaosEngineering:
    def test_register_experiment(self) -> None:
        chaos = ChaosEngineering()
        cfg = chaos.register("lat", probability=0.5, max_delay_ms=100)
        assert cfg.name == "lat"
        assert cfg.probability == 0.5
        assert chaos.get("lat") is cfg

    def test_unregister_experiment(self) -> None:
        chaos = ChaosEngineering()
        chaos.register("x")
        chaos.unregister("x")
        assert chaos.get("x") is None

    @pytest.mark.asyncio
    async def test_latency_no_op_when_disabled(self) -> None:
        chaos = ChaosEngineering()
        with patch(
            "src.backend.infrastructure.chaos.probes.is_chaos_enabled",
            return_value=False,
        ):
            with patch("asyncio.sleep") as mock_sleep:
                await chaos.latency("lat", probability=1.0, max_delay_ms=1000)
                mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_latency_injects_when_enabled(self) -> None:
        chaos = ChaosEngineering()
        with patch(
            "src.backend.infrastructure.chaos.probes.is_chaos_enabled",
            return_value=True,
        ):
            with patch("asyncio.sleep") as mock_sleep:
                await chaos.latency("lat", probability=1.0, max_delay_ms=10)
                mock_sleep.assert_awaited_once()
                assert 0 <= mock_sleep.call_args[0][0] <= 0.01

    @pytest.mark.asyncio
    async def test_latency_respects_probability(self) -> None:
        chaos = ChaosEngineering()
        with patch(
            "src.backend.infrastructure.chaos.probes.is_chaos_enabled",
            return_value=True,
        ):
            with patch("asyncio.sleep") as mock_sleep:
                await chaos.latency("lat", probability=0.0, max_delay_ms=10)
                mock_sleep.assert_not_called()

    def test_maybe_raise_no_op_when_disabled(self) -> None:
        chaos = ChaosEngineering()
        with patch(
            "src.backend.infrastructure.chaos.probes.is_chaos_enabled",
            return_value=False,
        ):
            chaos.maybe_raise("err", probability=1.0, exc=RuntimeError("boom"))

    def test_maybe_raise_raises_when_enabled(self) -> None:
        chaos = ChaosEngineering()
        with patch(
            "src.backend.infrastructure.chaos.probes.is_chaos_enabled",
            return_value=True,
        ):
            with pytest.raises(RuntimeError, match="Chaos error probe: err"):
                chaos.maybe_raise("err", probability=1.0)

    def test_maybe_raise_respects_probability(self) -> None:
        chaos = ChaosEngineering()
        with patch(
            "src.backend.infrastructure.chaos.probes.is_chaos_enabled",
            return_value=True,
        ):
            chaos.maybe_raise("err", probability=0.0, exc=RuntimeError("boom"))

    @pytest.mark.asyncio
    async def test_exhaust_pool_no_op_when_disabled(self) -> None:
        chaos = ChaosEngineering()
        with patch(
            "src.backend.infrastructure.chaos.probes.is_chaos_enabled",
            return_value=False,
        ):
            async with chaos.exhaust_pool("db_main", duration_seconds=0.1):
                pass

    @pytest.mark.asyncio
    async def test_exhaust_pool_no_op_when_pool_not_found(self) -> None:
        chaos = ChaosEngineering()
        with patch(
            "src.backend.infrastructure.chaos.probes.is_chaos_enabled",
            return_value=True,
        ):
            async with chaos.exhaust_pool("missing", duration_seconds=0.1):
                pass

    @pytest.mark.asyncio
    async def test_exhaust_pool_sets_and_restores_max_size(self) -> None:
        chaos = ChaosEngineering()
        # Use a plain object without _pool so the code finds pool.max_size directly
        pool = type("FakePool", (), {"max_size": 10})()
        reg = MagicMock()
        reg.pool = pool
        reg.ping_fn = AsyncMock()
        with patch(
            "src.backend.infrastructure.chaos.probes.is_chaos_enabled",
            return_value=True,
        ):
            mgr = MagicMock()
            mgr._pools = {"db_main": reg}
            with patch(
                "src.backend.infrastructure.clients.unified_pool_manager.get_unified_pool_manager",
                return_value=mgr,
            ):
                async with chaos.exhaust_pool("db_main", duration_seconds=0.01):
                    assert pool.max_size == 0
                assert pool.max_size == 10

    @pytest.mark.asyncio
    async def test_partition_no_op_when_disabled(self) -> None:
        chaos = ChaosEngineering()
        with patch(
            "src.backend.infrastructure.chaos.probes.is_chaos_enabled",
            return_value=False,
        ):
            async with chaos.partition("db_main", duration_seconds=0.1):
                pass

    def test_singleton(self) -> None:
        a = get_chaos_engineering()
        b = get_chaos_engineering()
        assert a is b

    def test_is_chaos_enabled_safe_default(self) -> None:
        with patch("src.backend.core.config.features.feature_flags") as mock_flags:
            mock_flags.chaos_engineering_enabled = True
            assert is_chaos_enabled() is True
