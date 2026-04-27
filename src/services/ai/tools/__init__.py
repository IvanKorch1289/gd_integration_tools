"""AI ToolRegistry — декларативная экспозиция методов как инструментов LLM.

Пакет собирает инструменты агента из разных источников:
  * публичные методы сервисов (``ToolRegistry.from_service``);
  * функции-плагины, помеченные декоратором ``@agent_tool``
    (``ToolRegistry.from_plugin_file``);
  * прямая регистрация через ``ToolRegistry.register``.

Каждый инструмент описывается ``AgentTool`` (name, description,
parameters, callable) и может быть использован LangChain/LangGraph
агентами, а также экспортирован через REST (``GET /api/v1/ai/tools``).
"""

from __future__ import annotations

from src.services.ai.tools.registry import (
    AgentTool,
    ToolRegistry,
    agent_tool,
    get_tool_registry,
)

__all__ = ("AgentTool", "ToolRegistry", "agent_tool", "get_tool_registry")
