"""B-05 fix (cycle 33): regression tests для rate_limit_fail_mode.

Tests:
* ``fail_closed_returns_false`` — при ``rate_limit_fail_mode="closed"``
  (default) и ошибке limiter'а ``check_rate_limit`` возвращает ``False``
  (deny-by-default), а не пропускает запрос.
* ``fail_open_returns_true`` — при ``rate_limit_fail_mode="open"`` и
  ошибке limiter'а ``check_rate_limit`` возвращает ``True`` (legacy
  pass-through).

Подход: патчим ``src.backend.core.resilience.get_rate_limiter`` (фабрика
singleton'а, импортируется в ``facade.py`` через ``from ... import
get_rate_limiter``). Чтение ``settings.resilience.rate_limit_fail_mode``
идёт через helper ``_get_rate_limit_settings()`` (lazy import), который
тоже патчится для детерминированного override без env-var.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core import resilience as core_resilience
from src.backend.services.resilience.facade import ResilienceFacade

# ── fail_closed (default) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_fail_closed_returns_false() -> None:
    """fail_mode=closed → возвращаем False при ошибке limiter'а (deny-by-default)."""

    fake_limiter = MagicMock()
    fake_limiter.check = AsyncMock(side_effect=RuntimeError("redis down"))

    def _factory() -> Any:
        return fake_limiter

    fake_settings = MagicMock()
    fake_settings.resilience.rate_limit_fail_mode = "closed"

    with patch.object(core_resilience, "get_rate_limiter", _factory), patch(
        "src.backend.services.resilience.facade._get_rate_limit_settings",
        return_value=fake_settings,
    ):
        facade = ResilienceFacade()
        result = await facade.check_rate_limit(
            "client-1", limit=10, window_seconds=1.0
        )
        # B-05 fix: closed → False (deny-by-default).
        assert result is False


# ── fail_open (legacy / opt-in) ────────────────────────────────────


@pytest.mark.asyncio
async def test_fail_open_returns_true() -> None:
    """fail_mode=open → возвращаем True при ошибке limiter'а (pass-through)."""

    fake_limiter = MagicMock()
    fake_limiter.check = AsyncMock(side_effect=RuntimeError("redis down"))

    def _factory() -> Any:
        return fake_limiter

    fake_settings = MagicMock()
    fake_settings.resilience.rate_limit_fail_mode = "open"

    with patch.object(core_resilience, "get_rate_limiter", _factory), patch(
        "src.backend.services.resilience.facade._get_rate_limit_settings",
        return_value=fake_settings,
    ):
        facade = ResilienceFacade()
        result = await facade.check_rate_limit(
            "client-1", limit=10, window_seconds=1.0
        )
        # B-05 fix: open → True (legacy pass-through).
        assert result is True


# ── happy path (no exception) — sanity check ───────────────────────


@pytest.mark.asyncio
async def test_check_rate_limit_happy_path() -> None:
    """happy path: allowed=True возвращается как есть (fail-mode не вмешивается)."""

    fake_limiter = MagicMock()
    fake_limiter.check = AsyncMock(return_value={"allowed": True})

    def _factory() -> Any:
        return fake_limiter

    # Любое значение fail_mode должно игнорироваться в happy path.
    fake_settings = MagicMock()
    fake_settings.resilience.rate_limit_fail_mode = "closed"

    with patch.object(core_resilience, "get_rate_limiter", _factory), patch(
        "src.backend.services.resilience.facade._get_rate_limit_settings",
        return_value=fake_settings,
    ):
        facade = ResilienceFacade()
        result = await facade.check_rate_limit(
            "client-1", limit=10, window_seconds=1.0
        )
        assert result is True


# ── settings default value ─────────────────────────────────────────


def test_resilience_settings_default_is_closed() -> None:
    """``ResilienceSettings.rate_limit_fail_mode`` default = ``closed`` (deny-by-default)."""

    from src.backend.core.config.services.resilience import ResilienceSettings

    settings = ResilienceSettings()
    assert settings.rate_limit_fail_mode == "closed"


def test_resilience_settings_accepts_open() -> None:
    """``ResilienceSettings.rate_limit_fail_mode`` принимает ``open`` через env."""

    from src.backend.core.config.services.resilience import ResilienceSettings

    with patch.dict(
        "os.environ",
        {"RESILIENCE_RATE_LIMIT_FAIL_MODE": "open"},
    ):
        settings = ResilienceSettings()
        assert settings.rate_limit_fail_mode == "open"
