"""T-P0.1.17: unit-тесты для core/resilience/degradation.py (DegradationManager).

Coverage: degradation.py 68% → 90%+ через тестирование:
- DegradationMode enum, mode_at_least
- DegradationTransition, ComponentState dataclasses
- DegradationManager (init, set_mode, history, current_mode, register, report_failure/success, get_fallback, is_available, mode, report, attach_store)
- Module singleton
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.resilience.degradation import (
    ComponentState,
    DegradationManager,
    DegradationMode,
    DegradationTransition,
    degradation_manager,
    mode_at_least,
)


class TestDegradationMode:
    def test_values(self) -> None:
        assert DegradationMode.FULL.value == "full"
        assert DegradationMode.READ_ONLY.value == "read_only"
        assert DegradationMode.CACHE_ONLY.value == "cache_only"
        assert DegradationMode.ESSENTIAL_ONLY.value == "essential_only"
        assert DegradationMode.MAINTENANCE.value == "maintenance"

    def test_legacy_aliases(self) -> None:
        assert DegradationMode.DEGRADED.value == "degraded"
        assert DegradationMode.EMERGENCY.value == "emergency"


class TestModeAtLeast:
    def test_full_vs_full(self) -> None:
        assert mode_at_least(DegradationMode.FULL, DegradationMode.FULL) is True

    def test_full_vs_read_only(self) -> None:
        assert mode_at_least(DegradationMode.FULL, DegradationMode.READ_ONLY) is False

    def test_read_only_vs_full(self) -> None:
        assert mode_at_least(DegradationMode.READ_ONLY, DegradationMode.FULL) is True

    def test_maintenance_vs_cache_only(self) -> None:
        assert (
            mode_at_least(DegradationMode.MAINTENANCE, DegradationMode.CACHE_ONLY) is True
        )

    def test_legacy_alias_same_level(self) -> None:
        """DEGRADED == READ_ONLY strictness (both 1)."""
        assert mode_at_least(
            DegradationMode.DEGRADED, DegradationMode.READ_ONLY
        ) is True
        assert mode_at_least(
            DegradationMode.EMERGENCY, DegradationMode.ESSENTIAL_ONLY
        ) is True


class TestDataclasses:
    def test_transition(self) -> None:
        t = DegradationTransition(
            timestamp_utc="2026-01-01T00:00:00Z",
            from_mode="full",
            to_mode="read_only",
            actor="admin",
            reason="redis-down",
        )
        assert t.from_mode == "full"
        assert t.to_mode == "read_only"
        assert t.actor == "admin"
        assert t.reason == "redis-down"

    def test_transition_frozen(self) -> None:
        t = DegradationTransition(
            timestamp_utc="x", from_mode="a", to_mode="b", actor="c", reason="d"
        )
        with pytest.raises((AttributeError, Exception)):
            t.from_mode = "z"  # type: ignore[misc]

    def test_component_state_defaults(self) -> None:
        s = ComponentState(name="db")
        assert s.name == "db"
        assert s.available is True
        assert s.last_check == 0.0
        assert s.failure_count == 0
        assert s.fallback_active is False


class TestInit:
    def test_default_state(self) -> None:
        m = DegradationManager()
        assert m._components == {}
        assert m._fallbacks == {}
        assert m._manual_mode is None
        assert m._store is None
        assert len(m._history) == 0


class TestAttachStore:
    def test_attach(self) -> None:
        m = DegradationManager()
        store = MagicMock()
        m.attach_store(store)
        assert m._store is store


class TestSetMode:
    @pytest.mark.asyncio
    async def test_basic(self) -> None:
        m = DegradationManager()
        transition = await m.set_mode(
            DegradationMode.READ_ONLY, actor="admin", reason="test"
        )
        assert isinstance(transition, DegradationTransition)
        assert transition.to_mode == "read_only"
        assert transition.actor == "admin"
        assert transition.reason == "test"
        assert m._manual_mode == DegradationMode.READ_ONLY

    @pytest.mark.asyncio
    async def test_appends_to_history(self) -> None:
        m = DegradationManager()
        await m.set_mode(DegradationMode.READ_ONLY)
        await m.set_mode(DegradationMode.MAINTENANCE)
        assert len(m._history) == 2

    @pytest.mark.asyncio
    async def test_with_store(self) -> None:
        m = DegradationManager()
        store = AsyncMock()
        m.attach_store(store)

        await m.set_mode(DegradationMode.READ_ONLY, actor="admin", reason="test")
        assert store.persist.call_count == 1
        args = store.persist.call_args.args
        assert args[0] == DegradationMode.READ_ONLY
        assert isinstance(args[1], DegradationTransition)

    @pytest.mark.asyncio
    async def test_store_failure_logged(self) -> None:
        m = DegradationManager()
        store = AsyncMock()
        store.persist.side_effect = RuntimeError("store-down")
        m.attach_store(store)

        with patch(
            "src.backend.core.resilience.degradation.logger"
        ) as mock_logger:
            # Should not raise
            await m.set_mode(DegradationMode.READ_ONLY)
            assert mock_logger.exception.called


class TestHistory:
    @pytest.mark.asyncio
    async def test_empty(self) -> None:
        m = DegradationManager()
        assert m.history() == []

    @pytest.mark.asyncio
    async def test_with_entries(self) -> None:
        m = DegradationManager()
        await m.set_mode(DegradationMode.READ_ONLY)
        await m.set_mode(DegradationMode.MAINTENANCE)
        h = m.history(n=10)
        assert len(h) == 2
        assert h[0].to_mode == "read_only"
        assert h[1].to_mode == "maintenance"

    @pytest.mark.asyncio
    async def test_n_limit(self) -> None:
        m = DegradationManager()
        for _ in range(5):
            await m.set_mode(DegradationMode.READ_ONLY)
        h = m.history(n=3)
        assert len(h) == 3


class TestCurrentMode:
    @pytest.mark.asyncio
    async def test_no_manual_no_components(self) -> None:
        m = DegradationManager()
        # mode() без components = FULL
        assert m.current_mode == DegradationMode.FULL

    @pytest.mark.asyncio
    async def test_manual_overrides(self) -> None:
        m = DegradationManager()
        m.register("db")  # mode = FULL (component available)
        await m.set_mode(DegradationMode.MAINTENANCE)
        # Manual > auto
        assert m.current_mode == DegradationMode.MAINTENANCE


class TestRegister:
    def test_without_fallback(self) -> None:
        m = DegradationManager()
        m.register("db")
        assert "db" in m._components
        assert m._components["db"].name == "db"
        assert "db" not in m._fallbacks

    def test_with_fallback(self) -> None:
        m = DegradationManager()
        fallback = lambda: "in-memory"
        m.register("redis", fallback=fallback)
        assert m._fallbacks["redis"] is fallback


class TestReportFailure:
    def test_first_failures_no_degrade(self) -> None:
        """Менее 3 failures — компонент остаётся available."""
        m = DegradationManager()
        m.register("db")
        m.report_failure("db")
        m.report_failure("db")
        assert m._components["db"].available is True
        assert m._components["db"].failure_count == 2

    def test_three_failures_degrade(self) -> None:
        m = DegradationManager()
        m.register("db")
        m.report_failure("db")
        m.report_failure("db")
        m.report_failure("db")
        assert m._components["db"].available is False
        assert m._components["db"].fallback_active is True

    def test_unknown_component_auto_registers(self) -> None:
        m = DegradationManager()
        m.report_failure("unknown")
        assert "unknown" in m._components
        assert m._components["unknown"].failure_count == 1

    def test_degrade_logged(self) -> None:
        m = DegradationManager()
        m.register("db")
        with patch(
            "src.backend.core.resilience.degradation.logger"
        ) as mock_logger:
            for _ in range(3):
                m.report_failure("db")
            assert mock_logger.warning.called


class TestReportSuccess:
    def test_resets_failure_count(self) -> None:
        m = DegradationManager()
        m.register("db")
        m.report_failure("db")
        m.report_success("db")
        assert m._components["db"].failure_count == 0

    def test_recovery(self) -> None:
        m = DegradationManager()
        m.register("db")
        for _ in range(3):
            m.report_failure("db")
        # Now degraded
        assert m._components["db"].available is False
        m.report_success("db")
        assert m._components["db"].available is True
        assert m._components["db"].fallback_active is False

    def test_unknown_auto_registers(self) -> None:
        m = DegradationManager()
        m.report_success("new-component")
        assert "new-component" in m._components

    def test_recovery_logged(self) -> None:
        m = DegradationManager()
        m.register("db")
        for _ in range(3):
            m.report_failure("db")
        with patch(
            "src.backend.core.resilience.degradation.logger"
        ) as mock_logger:
            m.report_success("db")
            assert mock_logger.info.called


class TestGetFallback:
    def test_no_fallback(self) -> None:
        m = DegradationManager()
        m.register("db")
        assert m.get_fallback("db") is None

    def test_fallback_when_degraded(self) -> None:
        m = DegradationManager()
        fb = lambda: "in-mem"
        m.register("db", fallback=fb)
        for _ in range(3):
            m.report_failure("db")
        assert m.get_fallback("db") is fb

    def test_fallback_not_active_when_available(self) -> None:
        m = DegradationManager()
        fb = lambda: "in-mem"
        m.register("db", fallback=fb)
        # Не degraded → None
        assert m.get_fallback("db") is None


class TestIsAvailable:
    def test_unknown_component(self) -> None:
        """Unknown → default ComponentState(available=True)."""
        m = DegradationManager()
        assert m.is_available("unknown") is True

    def test_known_available(self) -> None:
        m = DegradationManager()
        m.register("db")
        assert m.is_available("db") is True

    def test_known_degraded(self) -> None:
        m = DegradationManager()
        m.register("db")
        for _ in range(3):
            m.report_failure("db")
        assert m.is_available("db") is False


class TestMode:
    def test_no_components_full(self) -> None:
        m = DegradationManager()
        assert m.mode() == DegradationMode.FULL

    def test_all_available_full(self) -> None:
        m = DegradationManager()
        m.register("db")
        m.register("redis")
        assert m.mode() == DegradationMode.FULL

    def test_non_critical_down_degraded(self) -> None:
        m = DegradationManager()
        m.register("kafka")  # not critical
        for _ in range(3):
            m.report_failure("kafka")
        assert m.mode() == DegradationMode.DEGRADED

    def test_one_critical_down_degraded(self) -> None:
        m = DegradationManager()
        m.register("database")
        for _ in range(3):
            m.report_failure("database")
        assert m.mode() == DegradationMode.DEGRADED

    def test_two_critical_down_emergency(self) -> None:
        m = DegradationManager()
        m.register("database")
        m.register("redis")
        for _ in range(3):
            m.report_failure("database")
        for _ in range(3):
            m.report_failure("redis")
        assert m.mode() == DegradationMode.EMERGENCY


class TestReport:
    def test_empty(self) -> None:
        m = DegradationManager()
        r = m.report()
        assert r["mode"] == "full"
        assert r["components"] == {}

    def test_with_components(self) -> None:
        m = DegradationManager()
        m.register("db")
        r = m.report()
        assert r["mode"] == "full"
        assert "db" in r["components"]
        assert r["components"]["db"]["available"] is True
        assert r["components"]["db"]["failures"] == 0
        assert r["components"]["db"]["fallback_active"] is False


class TestModuleSingleton:
    def test_singleton_exists(self) -> None:
        assert isinstance(degradation_manager, DegradationManager)


class TestAllExports:
    def test_all(self) -> None:
        from src.backend.core.resilience import degradation as m

        assert set(m.__all__) == {
            "ComponentState",
            "DegradationManager",
            "DegradationMode",
            "DegradationTransition",
            "degradation_manager",
            "mode_at_least",
        }
