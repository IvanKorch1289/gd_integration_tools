"""WebAutomationService — универсальный сервис для web automation.

Доступен через все протоколы: REST API, gRPC, GraphQL, SOAP, WebSocket, Queue, MCP.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.di.app_state import app_state_singleton
from src.core.di.providers import get_browser_client_provider
from src.core.interfaces.integrations import BrowserClientProtocol

__all__ = ("WebAutomationService", "get_web_automation_service")

logger = logging.getLogger(__name__)


class WebAutomationService:
    """Web automation — парсинг, заполнение форм, мониторинг, сценарии."""

    def __init__(self, client: BrowserClientProtocol | None = None) -> None:
        self._client = client or get_browser_client_provider()

    async def navigate(self, url: str) -> dict[str, Any]:
        return await self._client.navigate(url)

    async def click(self, url: str, selector: str) -> dict[str, Any]:
        return await self._client.click(url, selector)

    async def fill_form(
        self, url: str, fields: dict[str, str], submit: str | None = None
    ) -> dict[str, Any]:
        return await self._client.fill_form(url, fields, submit)

    async def extract_text(self, url: str, selector: str) -> list[str]:
        return await self._client.extract_text(url, selector)

    async def extract_table(self, url: str, selector: str) -> list[dict[str, str]]:
        return await self._client.extract_table(url, selector)

    async def screenshot(self, url: str) -> bytes:
        return await self._client.screenshot(url)

    async def run_scenario(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return await self._client.run_scenario(steps)

    async def parse_page(
        self, url: str, selectors: dict[str, str]
    ) -> dict[str, list[str]]:
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
                changes.append(
                    {"check": i, "previous": prev_content, "current": current}
                )
            prev_content = current
            if i < max_checks - 1:
                await asyncio.sleep(interval_seconds)

        return changes


@app_state_singleton("web_automation_service", factory=WebAutomationService)
def get_web_automation_service() -> WebAutomationService:
    raise NotImplementedError  # заменяется декоратором
