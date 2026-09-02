"""Unit-тесты ``services.rpa`` — coverage ratchet (Post-Plan A Sprint 11).

core/rpa service package facade: re-exports ``PlaywrightBrowserPool``
(browser-pool: patchright/playwright context pool). ~4 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.services import rpa
from src.backend.services.rpa import PlaywrightBrowserPool


@pytest.mark.unit
class TestRpaFacadeAllExports:
    """``__all__`` audit + class identity."""

    def test_all_exports_accessible(self) -> None:
        """``PlaywrightBrowserPool`` доступен через facade."""
        assert hasattr(rpa, "PlaywrightBrowserPool")
        assert "PlaywrightBrowserPool" in rpa.__all__

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 1 symbol."""
        assert len(rpa.__all__) == 1

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает RPA services (browser-pool, OCR, antidetect)."""
        assert rpa.__doc__ is not None
        assert "RPA" in rpa.__doc__ or "browser" in rpa.__doc__.lower()


@pytest.mark.unit
class TestRpaFacadeIdentity:
    """Identity checks для re-export."""

    def test_playwright_browser_pool_is_class(self) -> None:
        """``PlaywrightBrowserPool`` — class (browser context pool)."""
        assert isinstance(PlaywrightBrowserPool, type)
