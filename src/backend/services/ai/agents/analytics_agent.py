"""AnalyticsAgent — агрегации Polars + SQL-запросы DuckDB (Wave 8.7).

Загружает ``@agent_tool``-функции из ``plugins/example_plugin/tools/
analytics_tools.py`` и предоставляет единый ``invoke(prompt, payload)``
интерфейс. LangGraph-планирование ставится опционально: если
``langgraph`` недоступен — агент работает в режиме ``direct-call``
(один tool вызывается напрямую по hint'у пользователя).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.backend.core.di import app_state_singleton
from src.backend.services.ai.tools import AgentTool, ToolRegistry

__all__ = ("AnalyticsAgent", "get_analytics_agent")

logger = logging.getLogger(__name__)

_PLUGIN_FILE = (
    Path(__file__).resolve().parents[3].parent
    / "plugins"
    / "example_plugin"
    / "tools"
    / "analytics_tools.py"
)


class AnalyticsAgent:
    """Агент для аналитических запросов через Polars/DuckDB."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry or ToolRegistry()
        self._loaded = False

    def _ensure_tools(self) -> None:
        """Lazy-load инструментов из plugin-файла."""
        if self._loaded:
            return
        if _PLUGIN_FILE.is_file():
            try:
                self._registry.from_plugin_file(_PLUGIN_FILE)
            except Exception as exc:  # noqa: BLE001
                logger.warning("AnalyticsAgent: tools load failed: %s", exc)
        self._loaded = True

    def list_tools(self) -> list[AgentTool]:
        """Возвращает список инструментов, доступных агенту."""
        self._ensure_tools()
        return self._registry.list()

    async def invoke(
        self,
        prompt: str,
        *,
        tool: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Выполняет аналитический запрос.

        Если задан ``tool`` (например ``aggregate_polars``) — direct-call
        с ``payload`` в качестве kwargs. Иначе — пытается выбрать
        инструмент через LangGraph (если установлен).

        Args:
            prompt: Текст запроса (используется для LangGraph).
            tool: Явное имя инструмента для direct-call.
            payload: Аргументы для direct-call.

        Returns:
            Словарь ``{success, tool, result|error}``.
        """
        self._ensure_tools()
        tools = self._registry.list()
        if not tools:
            return {"success": False, "error": "AnalyticsAgent: tools не загружены"}

        if tool:
            target = next(
                (t for t in tools if t.name == tool or t.id.endswith(tool)), None
            )
            if target is None:
                return {
                    "success": False,
                    "error": f"unknown tool: {tool}",
                    "available": [t.name for t in tools],
                }
            try:
                result = await target.callable(**(payload or {}))
                return {"success": True, "tool": target.id, "result": result}
            except Exception as exc:  # noqa: BLE001
                logger.warning("AnalyticsAgent: tool %s failed: %s", target.id, exc)
                return {"success": False, "tool": target.id, "error": str(exc)}

        # Без указанного инструмента возвращаем каталог — LangGraph wiring
        # будет добавлен в отдельной волне (Wave 8.7+).
        return {
            "success": True,
            "mode": "catalog",
            "prompt": prompt,
            "tools": [t.to_dict() for t in tools],
        }


@app_state_singleton("analytics_agent", factory=AnalyticsAgent)
def get_analytics_agent() -> AnalyticsAgent:
    """Singleton AnalyticsAgent (через app.state)."""
