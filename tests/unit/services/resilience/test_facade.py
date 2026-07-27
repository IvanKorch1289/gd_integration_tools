# ruff: noqa: S101
"""Unit tests for services/resilience/facade.py (Sprint C28 fix).

Covers:
* check_rate_limit() — Callable[[], RateLimiter] cast boundary (C28 fix).
* get_breaker() — singleton registry accessor.
* bulkhead() — lazy-create via registry.
* with_retry() — decorator factory from RetryPolicy.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.resilience.facade import ResilienceFacade


# ── check_rate_limit: limiter factory cast (C28 fix) ────────────────


@pytest.mark.asyncio
async def test_check_rate_limit_returns_allowed_flag() -> None:
    """check_rate_limit() вернёт result['allowed'] без raise."""

    fake_limiter = MagicMock()
    fake_limiter.check = AsyncMock(return_value={"allowed": True})

    def _factory() -> Any:
        return fake_limiter

    with patch(
        "src.backend.core.di.providers.infrastructure_facade.get_unified_rate_limiter_attr",
        return_value=_factory,
    ):
        facade = ResilienceFacade()
        result = await facade.check_rate_limit("client-1", limit=10, window_seconds=1.0)
        assert result is True


@pytest.mark.asyncio
async def test_check_rate_limit_returns_disallowed_flag() -> None:
    """check_rate_limit() возвращает False если allowed=False."""

    fake_limiter = MagicMock()
    fake_limiter.check = AsyncMock(return_value={"allowed": False})

    def _factory() -> Any:
        return fake_limiter

    with patch(
        "src.backend.core.di.providers.infrastructure_facade.get_unified_rate_limiter_attr",
        return_value=_factory,
    ):
        facade = ResilienceFacade()
        result = await facade.check_rate_limit("client-1", limit=10, window_seconds=1.0)
        assert result is False


@pytest.mark.asyncio
async def test_check_rate_limit_fails_open_on_exception() -> None:
    """check_rate_limit() — fail-open при исключении в limiter (canonical)."""

    fake_limiter = MagicMock()
    fake_limiter.check = AsyncMock(side_effect=RuntimeError("redis down"))

    def _factory() -> Any:
        return fake_limiter

    with patch(
        "src.backend.core.di.providers.infrastructure_facade.get_unified_rate_limiter_attr",
        return_value=_factory,
    ):
        facade = ResilienceFacade()
        result = await facade.check_rate_limit("client-1", limit=10, window_seconds=1.0)
        # Fail-open: True на любую ошибку.
        assert result is True


# ── get_breaker: registry accessor ─────────────────────────────────


def test_get_breaker_returns_breaker_instance() -> None:
    """get_breaker() возвращает breaker через registry.get_or_create()."""

    fake_breaker = MagicMock(name="breaker")
    fake_registry = MagicMock()
    fake_registry.get_or_create = MagicMock(return_value=fake_breaker)

    with patch(
        "src.backend.core.resilience.get_breaker_registry",
        return_value=fake_registry,
    ):
        facade = ResilienceFacade()
        result = facade.get_breaker("redis")
        assert result is fake_breaker
        fake_registry.get_or_create.assert_called_once_with("redis")


# ── bulkhead: lazy-create via registry (S174) ───────────────────────


def test_bulkhead_returns_existing() -> None:
    """bulkhead() возвращает существующий instance если registered."""

    fake_bh = MagicMock(name="bulkhead")
    fake_registry = MagicMock()
    fake_registry.get = MagicMock(return_value=fake_bh)

    with patch(
        "src.backend.core.resilience.bulkhead_registry.get_bulkhead_registry",
        return_value=fake_registry,
    ):
        facade = ResilienceFacade()
        result = facade.bulkhead("kafka_produce")
        assert result is fake_bh
        fake_registry.register.assert_not_called()


def test_bulkhead_creates_new_when_missing() -> None:
    """bulkhead() создаёт новый AdaptiveBulkhead если missing."""

    fake_registry = MagicMock()
    fake_registry.get = MagicMock(return_value=None)

    fake_bh = MagicMock(name="bulkhead-new")

    with patch(
        "src.backend.core.resilience.bulkhead_registry.get_bulkhead_registry",
        return_value=fake_registry,
    ):
        with patch(
            "src.backend.core.resilience.backpressure.bulkhead.AdaptiveBulkhead",
            return_value=fake_bh,
        ):
            facade = ResilienceFacade()
            result = facade.bulkhead("kafka_produce")
            assert result is fake_bh
            fake_registry.register.assert_called_once_with("kafka_produce", fake_bh)


# ── with_retry: decorator factory (S174) ────────────────────────────


def test_with_retry_returns_decorator() -> None:
    """with_retry() возвращает callable decorator."""

    fake_decorator = MagicMock()

    with patch(
        "src.backend.core.resilience.with_retry",
        return_value=fake_decorator,
    ):
        facade = ResilienceFacade()
        result = facade.with_retry()
        assert result is fake_decorator


# ── capability check passthrough ────────────────────────────────────


def test_capability_check_invoked_for_each_action() -> None:
    """capability_check вызывается для каждой защищённой операции."""

    seen: list[tuple[str, str, str]] = []

    def _check(plugin: str, action: str, resource: str) -> None:
        seen.append((plugin, action, resource))

    facade = ResilienceFacade(capability_check=_check, plugin="test_plugin")

    # rate_limit path — invokes capability check.
    fake_limiter_for_cap = MagicMock()
    fake_limiter_for_cap.check = AsyncMock(return_value={"allowed": True})

    def _factory_for_cap() -> Any:
        return fake_limiter_for_cap

    with patch(
        "src.backend.core.di.providers.infrastructure_facade.get_unified_rate_limiter_attr",
        return_value=_factory_for_cap,
    ):
        # We need to call async method → event loop.
        asyncio.run(facade.check_rate_limit("client-1", 10, 1.0))

    assert ("test_plugin", "resilience.rate_limit", "client-1") in seen


# Helper: keep asyncio import used
_ = asyncio
_ = Any
