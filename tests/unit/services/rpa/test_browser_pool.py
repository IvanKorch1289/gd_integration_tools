"""Tests for PlaywrightBrowserPool (PERF-6.6 Sprint 14 coverage ratchet).

Coverage target: browser_pool.py 33% → 70%+.
"""

from __future__ import annotations

import pytest

from src.backend.services.rpa.browser_pool import (
    PlaywrightBrowserPool,
)


def test_init_explicit_params() -> None:
    """Constructor with explicit size, browser_kind, headless."""
    pool = PlaywrightBrowserPool(
        size=8,
        browser_kind="firefox",
        headless=False,
        viewport={"width": 1920, "height": 1080},
    )
    assert pool.size == 8
    assert pool.is_started is False


def test_size_property() -> None:
    """size property — int, reflects maxsize."""
    pool = PlaywrightBrowserPool(size=16)
    assert pool.size == 16
    assert isinstance(pool.size, int)


def test_is_started_false_initially() -> None:
    """Fresh pool not started."""
    pool = PlaywrightBrowserPool(size=2)
    assert pool.is_started is False


def test_is_started_property_not_callable() -> None:
    """is_started — bool property, не метод."""
    pool = PlaywrightBrowserPool(size=2)
    # Должна быть property, не method. Доступ без parens.
    assert isinstance(pool.is_started, bool)


def test_size_with_chromium_default() -> None:
    """Default browser_kind = 'chromium'."""
    pool = PlaywrightBrowserPool(size=4)
    # Internal _browser_kind field должен быть 'chromium'
    assert pool._browser_kind == "chromium"
