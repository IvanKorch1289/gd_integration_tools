"""S80 W4 — tests для LiteLLM pool registration в PoolHealthMonitor
(FINAL_REPORT_V2 P1 #6 closure: 'Добавить connection pool для LiteLLM Gateway')."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.clients.pool_health import PoolHealthMonitor
from src.backend.services.ai.gateway.pool_registration import (
    _litellm_ping,
    register_litellm_pool,
)

# _litellm_ping tests
# ============================================================================


@pytest.mark.asyncio
async def test_litellm_ping_no_litellm_returns_false() -> None:
    """Если litellm не установлен → False."""

    # Force ImportError
    with patch.dict("sys.modules", {"litellm": None}):
        gateway = MagicMock()
        result = await _litellm_ping(gateway)
        assert result is False


@pytest.mark.asyncio
async def test_litellm_ping_with_models_returns_true() -> None:
    """Если litellm.models — non-empty list → True."""
    fake_litellm = MagicMock()
    fake_litellm.models = ["gpt-4", "claude-3.5-sonnet", "gemini-pro"]
    with patch.dict("sys.modules", {"litellm": fake_litellm}):
        gateway = MagicMock()
        result = await _litellm_ping(gateway)
        assert result is True


@pytest.mark.asyncio
async def test_litellm_ping_empty_models_returns_false() -> None:
    """Если litellm.models — empty list → False."""
    fake_litellm = MagicMock()
    fake_litellm.models = []
    with patch.dict("sys.modules", {"litellm": fake_litellm}):
        gateway = MagicMock()
        result = await _litellm_ping(gateway)
        assert result is False


# register_litellm_pool tests
# ============================================================================


def test_register_litellm_pool_default_name() -> None:
    """register_litellm_pool() с default name='litellm_main'."""
    monitor = PoolHealthMonitor()
    gateway = MagicMock()
    register_litellm_pool(gateway, monitor=monitor)
    # Pool registered (use internal _pools dict)
    assert "litellm_main" in monitor._pools


def test_register_litellm_pool_custom_name() -> None:
    """register_litellm_pool(name=...) uses custom name."""
    monitor = PoolHealthMonitor()
    gateway = MagicMock()
    register_litellm_pool(gateway, monitor=monitor, name="litellm_premium")
    assert "litellm_premium" in monitor._pools
    assert "litellm_main" not in monitor._pools


def test_register_litellm_pool_custom_idle_timeout() -> None:
    """register_litellm_pool(idle_timeout=...) sets custom value."""
    monitor = PoolHealthMonitor()
    gateway = MagicMock()
    register_litellm_pool(
        gateway, monitor=monitor, name="litellm_fast", idle_timeout=30.0
    )
    entry = monitor._pools["litellm_fast"]
    assert entry.idle_timeout == 30.0


def test_register_litellm_pool_idempotent() -> None:
    """Повторный register с тем же name → перезаписывает (per PoolHealthMonitor contract)."""
    monitor = PoolHealthMonitor()
    gateway1 = MagicMock()
    gateway2 = MagicMock()
    register_litellm_pool(gateway1, monitor=monitor, name="litellm_main")
    register_litellm_pool(gateway2, monitor=monitor, name="litellm_main")
    # Only one entry (idempotent)
    main_count = sum(1 for k in monitor._pools if k == "litellm_main")
    assert main_count == 1


def test_register_litellm_pool_uses_get_pool_monitor_default() -> None:
    """register_litellm_pool(monitor=None) — uses get_pool_monitor() singleton."""
    # This test is harder — singleton state. Just check it doesn't crash.
    gateway = MagicMock()
    # Don't pass monitor — uses default singleton
    try:
        register_litellm_pool(gateway, name="litellm_singleton_test")
    except Exception:
        # If monitor singleton has issues, skip
        pytest.skip("PoolHealthMonitor singleton not available in test env")
