"""RPA сервисы: browser-pool, OCR, antidetect.

Wave: ``[wave:s8/k3-rpa-universal-stage1]``. Public API:
* :class:`PlaywrightBrowserPool` — пул контекстов patchright/playwright.
"""

from __future__ import annotations

from src.backend.services.rpa.browser_pool import PlaywrightBrowserPool

__all__ = ("PlaywrightBrowserPool",)
