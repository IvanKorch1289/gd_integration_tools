"""SearchAgent — RAG + AgentMemory (Wave 8.7).

Загружает поисковые ``@agent_tool``-функции из
``plugins/example_plugin/tools/search_tools.py`` и предоставляет единый
``invoke(prompt, payload)`` интерфейс. Поведение симметрично
:class:`AnalyticsAgent`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.backend.core.di import app_state_singleton
from src.backend.services.ai.tools import AgentTool, ToolRegistry

__all__ = ("SearchAgent", "get_search_agent")

logger = logging.getLogger(__name__)

_PLUGIN_FILE = (
    Path(__file__).resolve().parents[3].parent
    / "plugins"
    / "example_plugin"
    / "tools"
    / "search_tools.py"
)


class SearchAgent:
    """Агент для семантического поиска и работы с долговременной памятью."""

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
                logger.warning("SearchAgent: tools load failed: %s", exc)
        self._loaded = True

    def list_tools(self) -> list[AgentTool]:
        """Список доступных инструментов."""
        self._ensure_tools()
        return self._registry.list()

    async def invoke(
        self,
        prompt: str,
        *,
        tool: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Выполняет поисковый запрос.

        Если ``tool`` не указан — по умолчанию вызывается ``rag_search``
        с ``query=prompt``.

        Args:
            prompt: Текст запроса.
            tool: Имя tool'а; ``None`` — auto = ``rag_search``.
            payload: kwargs для tool'а.

        Returns:
            Словарь ``{success, tool, result|error}``.
        """
        self._ensure_tools()
        tools = self._registry.list()
        if not tools:
            return {"success": False, "error": "SearchAgent: tools не загружены"}

        target_name = tool or "rag_search"
        target = next(
            (t for t in tools if t.name == target_name or t.id.endswith(target_name)),
            None,
        )
        if target is None:
            return {
                "success": False,
                "error": f"unknown tool: {target_name}",
                "available": [t.name for t in tools],
            }

        kwargs = dict(payload or {})
        if target.name == "rag_search" and "query" not in kwargs:
            kwargs["query"] = prompt
        if target.name == "rag_augment" and "query" not in kwargs:
            kwargs["query"] = prompt

        try:
            result = await target.callable(**kwargs)
            return {"success": True, "tool": target.id, "result": result}
        except Exception as exc:  # noqa: BLE001
            logger.warning("SearchAgent: tool %s failed: %s", target.id, exc)
            return {"success": False, "tool": target.id, "error": str(exc)}


@app_state_singleton("search_agent", factory=SearchAgent)
def get_search_agent() -> SearchAgent:
    """Singleton SearchAgent (через app.state)."""
