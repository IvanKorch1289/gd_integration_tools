"""WebAutomationService — универсальный сервис для web automation.

Доступен через все протоколы: REST API, Queue, Prefect, gRPC, MCP.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.decorators.singleton import singleton
from app.infrastructure.clients.browser import BrowserClient, get_browser_client

__all__ = ("WebAutomationService", "get_web_automation_service")

logger = logging.getLogger(__name__)


@singleton
class WebAutomationService:
    """Web automation — парсинг, заполнение форм, мониторинг, сценарии."""

    def __init__(self, client: BrowserClient | None = None) -> None:
        self._client = client or get_browser_client()

    async def navigate(self, url: str) -> dict[str, Any]:
        return await self._client.navigate(url)

    async def click(self, url: str, selector: str) -> dict[str, Any]:
        return await self._client.click(url, selector)

    async def fill_form(self, url: str, fields: dict[str, str], submit: str | None = None) -> dict[str, Any]:
        return await self._client.fill_form(url, fields, submit)

    async def extract_text(self, url: str, selector: str) -> list[str]:
        return await self._client.extract_text(url, selector)

    async def extract_table(self, url: str, selector: str) -> list[dict[str, str]]:
        return await self._client.extract_table(url, selector)

    async def screenshot(self, url: str) -> bytes:
        return await self._client.screenshot(url)

    async def run_scenario(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return await self._client.run_scenario(steps)

    async def parse_page(self, url: str, selectors: dict[str, str]) -> dict[str, list[str]]:
        """Парсит страницу по набору CSS-селекторов."""
        result: dict[str, list[str]] = {}
        for name, selector in selectors.items():
            result[name] = await self._client.extract_text(url, selector)
        return result

    async def monitor_changes(
        self, url: str, selector: str, interval_seconds: int = 60, max_checks: int = 10
    ) -> list[dict[str, Any]]:
        """Мониторинг изменений элемента на странице."""
        import asyncio

        changes: list[dict[str, Any]] = []
        prev_content: list[str] = []

        for i in range(max_checks):
            current = await self._client.extract_text(url, selector)
            if current != prev_content and prev_content:
                changes.append({
                    "check": i,
                    "previous": prev_content,
                    "current": current,
                })
            prev_content = current
            if i < max_checks - 1:
                await asyncio.sleep(interval_seconds)

        return changes


def get_web_automation_service() -> WebAutomationService:
    return WebAutomationService()
