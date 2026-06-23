"""Async browser automation client через Playwright.

Поддерживает: navigation, clicks, form fill, extraction, screenshots.
Human-like: random delays, viewport randomization.
Anti-detection: stealth mode, user-agent rotation.

S163 W5: добавлен per-instance Circuit Breaker (canonical pattern из smtp.py).
Каждая network-операция (navigate/extract/click/screenshot/fill_form/
run_scenario) обёрнута в ``async with self._breaker.guard():``.
Lifecycle-методы (start/stop) — без обёртки.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

# NB: порядок импортов критичен (S163 W3 lesson, см. ftp.py).
# ``core.config.settings`` грузится ПЕРВЫМ — pre-breaks circular import chain
# breaker → core.logging → infrastructure.logging → core.interfaces → breaker.
from src.backend.core.config.settings import settings as _settings  # noqa: F401
from src.backend.core.logging import get_logger
from src.backend.core.resilience.breaker import BreakerSpec, get_breaker_registry

__all__ = ("BrowserClient", "get_browser_client")

logger = get_logger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


class BrowserClient:
    """Async browser automation через Playwright.

    S163 W5: per-instance Circuit Breaker через ``get_breaker_registry()``.
    Дефолт: failure_threshold=5, recovery_timeout=60s.
    """

    def __init__(
        self,
        headless: bool = True,
        stealth: bool = True,
        proxy: str | None = None,
        default_timeout: int = 30000,
        human_like_delays: bool = True,
    ) -> None:
        self._headless = headless
        self._stealth = stealth
        self._proxy = proxy
        self._timeout = default_timeout
        self._human_delays = human_like_delays
        self._playwright: Any = None
        self._browser: Any = None
        # S163 W5: per-instance Circuit Breaker (canonical pattern из smtp.py).
        self._breaker = get_breaker_registry().get_or_create(
            "browser",
            BreakerSpec(name="browser", failure_threshold=5, recovery_timeout=60.0),
        )

    async def start(self) -> None:
        """Запуск Playwright (lifecycle — без breaker)."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": self._headless}
        if self._proxy:
            launch_kwargs["proxy"] = {"server": self._proxy}
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        logger.info(
            "Browser started (headless=%s, stealth=%s)", self._headless, self._stealth
        )

    async def stop(self) -> None:
        """Остановка Playwright (lifecycle — без breaker)."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
        logger.info("Browser stopped")

    async def _new_context(self) -> Any:
        """Create new browser context with stealth settings.

        Returns:
            Playwright browser context.
        """
        ctx_kwargs: dict[str, Any] = {
            "viewport": {
                "width": random.randint(  # noqa: S311  # non-cryptographic use
                    1280, 1920
                ),  # stealth fingerprint randomization, не криптография
                "height": random.randint(  # noqa: S311  # non-cryptographic use
                    720, 1080
                ),  # stealth fingerprint randomization, не криптография
            },
            "user_agent": random.choice(  # noqa: S311  # non-cryptographic use
                _USER_AGENTS
            ),  # stealth UA rotation, не криптография
        }
        if self._stealth:
            ctx_kwargs["java_script_enabled"] = True
            ctx_kwargs["locale"] = "ru-RU"
            ctx_kwargs["timezone_id"] = "Europe/Moscow"
        return await self._browser.new_context(**ctx_kwargs)

    async def _human_delay(self, min_ms: int = 100, max_ms: int = 500) -> None:
        """Add human-like delay between actions.

        Args:
            min_ms: Minimum delay in milliseconds.
            max_ms: Maximum delay in milliseconds.
        """
        if self._human_delays:
            await asyncio.sleep(
                random.randint(min_ms, max_ms) / 1000  # noqa: S311  # non-cryptographic use
            )  # human-like delay jitter, не криптография

    async def navigate(
        self, url: str, wait_until: str = "domcontentloaded"
    ) -> dict[str, Any]:
        """Navigate to URL.

        Args:
            url: Target URL.
            wait_until: Wait condition.

        Returns:
            Dict with url, status, title.
        """
        async with self._breaker.guard():
            ctx = await self._new_context()
            page = await ctx.new_page()
            try:
                response = await page.goto(
                    url, wait_until=wait_until, timeout=self._timeout
                )
                await self._human_delay()
                return {
                    "url": page.url,
                    "status": response.status if response else 0,
                    "title": await page.title(),
                }
            finally:
                await ctx.close()

    async def extract_text(self, url: str, selector: str) -> list[str]:
        """Extract text from elements matching selector.

        Args:
            url: Target URL.
            selector: CSS selector.

        Returns:
            List of text content from matching elements.
        """
        async with self._breaker.guard():
            ctx = await self._new_context()
            page = await ctx.new_page()
            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self._timeout
                )
                await self._human_delay()
                elements = await page.query_selector_all(selector)
                texts = [await el.inner_text() for el in elements]
                return texts
            finally:
                await ctx.close()

    async def extract_table(self, url: str, selector: str) -> list[dict[str, str]]:
        """Extract table data as list of dicts.

        Args:
            url: Target URL.
            selector: CSS selector for table.

        Returns:
            List of row dicts with header keys.
        """
        async with self._breaker.guard():
            ctx = await self._new_context()
            page = await ctx.new_page()
            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self._timeout
                )
                await self._human_delay()
                return await page.evaluate(f"""
                    () => {{
                        const table = document.querySelector('{selector}');
                        if (!table) return [];
                        const headers = [...table.querySelectorAll('th')].map(th => th.innerText.trim());
                        return [...table.querySelectorAll('tbody tr')].map(tr => {{
                            const cells = [...tr.querySelectorAll('td')].map(td => td.innerText.trim());
                            return Object.fromEntries(headers.map((h, i) => [h, cells[i] || '']));
                        }});
                    }}
                """)
            finally:
                await ctx.close()

    async def fill_form(
        self, url: str, fields: dict[str, str], submit_selector: str | None = None
    ) -> dict[str, Any]:
        """Fill form fields and optionally submit.

        Args:
            url: Target URL.
            fields: Dict of selector -> value pairs.
            submit_selector: Optional submit button selector.

        Returns:
            Dict with final url and title.
        """
        async with self._breaker.guard():
            ctx = await self._new_context()
            page = await ctx.new_page()
            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self._timeout
                )
                for selector, value in fields.items():
                    await self._human_delay(50, 200)
                    await page.fill(selector, value)
                if submit_selector:
                    await self._human_delay(200, 500)
                    await page.click(submit_selector)
                    await page.wait_for_load_state("domcontentloaded")
                return {"url": page.url, "title": await page.title()}
            finally:
                await ctx.close()

    async def click(self, url: str, selector: str) -> dict[str, Any]:
        """Navigate to URL and click element.

        Args:
            url: Target URL.
            selector: CSS selector to click.

        Returns:
            Dict with final url and title.
        """
        async with self._breaker.guard():
            ctx = await self._new_context()
            page = await ctx.new_page()
            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self._timeout
                )
                await self._human_delay()
                await page.click(selector)
                await page.wait_for_load_state("domcontentloaded")
                return {"url": page.url, "title": await page.title()}
            finally:
                await ctx.close()

    async def screenshot(self, url: str, full_page: bool = True) -> bytes:
        """Take screenshot of URL.

        Args:
            url: Target URL.
            full_page: Capture full page.

        Returns:
            Screenshot bytes (PNG).
        """
        async with self._breaker.guard():
            ctx = await self._new_context()
            page = await ctx.new_page()
            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=self._timeout
                )
                await self._human_delay()
                return await page.screenshot(full_page=full_page)
            finally:
                await ctx.close()

    async def run_scenario(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Выполняет сценарий из списка шагов."""
        async with self._breaker.guard():
            ctx = await self._new_context()
            page = await ctx.new_page()
            results: list[dict[str, Any]] = []

            try:
                for step in steps:
                    action = step.get("action", "")
                    await self._human_delay()

                    if action == "navigate":
                        resp = await page.goto(
                            step["url"],
                            wait_until="domcontentloaded",
                            timeout=self._timeout,
                        )
                        results.append(
                            {
                                "action": "navigate",
                                "url": page.url,
                                "status": resp.status if resp else 0,
                            }
                        )

                    elif action == "click":
                        await page.click(step["selector"])
                        results.append(
                            {"action": "click", "selector": step["selector"]}
                        )

                    elif action == "fill":
                        await page.fill(step["selector"], step["value"])
                        results.append({"action": "fill", "selector": step["selector"]})

                    elif action == "wait":
                        await page.wait_for_selector(
                            step["selector"], timeout=step.get("timeout", self._timeout)
                        )
                        results.append({"action": "wait", "selector": step["selector"]})

                    elif action == "extract":
                        elements = await page.query_selector_all(step["selector"])
                        texts = [await el.inner_text() for el in elements]
                        results.append({"action": "extract", "data": texts})

                    elif action == "screenshot":
                        data = await page.screenshot(
                            full_page=step.get("full_page", True)
                        )
                        results.append({"action": "screenshot", "size": len(data)})

                    elif action == "scroll":
                        await page.evaluate("window.scrollBy(0, window.innerHeight)")
                        results.append({"action": "scroll"})

                    elif action == "keyboard":
                        await page.keyboard.press(step["key"])
                        results.append({"action": "keyboard", "key": step["key"]})

                return results
            finally:
                await ctx.close()


_browser_client: BrowserClient | None = None


def get_browser_client() -> BrowserClient:
    global _browser_client
    if _browser_client is None:
        _browser_client = BrowserClient()
    return _browser_client
