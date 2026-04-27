"""Async browser automation client через Playwright.

Поддерживает: navigation, clicks, form fill, extraction, screenshots.
Human-like: random delays, viewport randomization.
Anti-detection: stealth mode, user-agent rotation.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

__all__ = ("BrowserClient", "get_browser_client")

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


class BrowserClient:
    """Async browser automation через Playwright."""

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

    async def start(self) -> None:
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
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
        logger.info("Browser stopped")

    async def _new_context(self) -> Any:
        ctx_kwargs: dict[str, Any] = {
            "viewport": {
                "width": random.randint(1280, 1920),
                "height": random.randint(720, 1080),
            },
            "user_agent": random.choice(_USER_AGENTS),
        }
        if self._stealth:
            ctx_kwargs["java_script_enabled"] = True
            ctx_kwargs["locale"] = "ru-RU"
            ctx_kwargs["timezone_id"] = "Europe/Moscow"
        return await self._browser.new_context(**ctx_kwargs)

    async def _human_delay(self, min_ms: int = 100, max_ms: int = 500) -> None:
        if self._human_delays:
            await asyncio.sleep(random.randint(min_ms, max_ms) / 1000)

    async def navigate(
        self, url: str, wait_until: str = "domcontentloaded"
    ) -> dict[str, Any]:
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
        ctx = await self._new_context()
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
            await self._human_delay()
            elements = await page.query_selector_all(selector)
            texts = [await el.inner_text() for el in elements]
            return texts
        finally:
            await ctx.close()

    async def extract_table(self, url: str, selector: str) -> list[dict[str, str]]:
        ctx = await self._new_context()
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
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
        ctx = await self._new_context()
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
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
        ctx = await self._new_context()
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
            await self._human_delay()
            await page.click(selector)
            await page.wait_for_load_state("domcontentloaded")
            return {"url": page.url, "title": await page.title()}
        finally:
            await ctx.close()

    async def screenshot(self, url: str, full_page: bool = True) -> bytes:
        ctx = await self._new_context()
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout)
            await self._human_delay()
            return await page.screenshot(full_page=full_page)
        finally:
            await ctx.close()

    async def run_scenario(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Выполняет сценарий из списка шагов."""
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
                    results.append({"action": "click", "selector": step["selector"]})

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
                    data = await page.screenshot(full_page=step.get("full_page", True))
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
