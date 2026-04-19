"""E2E testing fixtures for Playwright (optional, requires `pip install playwright`).

Usage::
    pytest tests/e2e/ --headed    # visible browser
    pytest tests/e2e/             # headless

Benefits:
- Test web automation DSL processors against real sites
- Validate scraping/pagination behaviour
- Regression test anti-bot patterns (UA rotation)
"""

from __future__ import annotations

import pytest


try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


pytestmark = pytest.mark.skipif(
    not PLAYWRIGHT_AVAILABLE,
    reason="playwright not installed",
)


@pytest.fixture
async def browser():
    """Chromium browser instance (session-scoped)."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture
async def context(browser):
    """Isolated browser context per test."""
    ctx = await browser.new_context()
    yield ctx
    await ctx.close()


@pytest.fixture
async def page(context):
    """Fresh page per test."""
    page = await context.new_page()
    yield page
    await page.close()
