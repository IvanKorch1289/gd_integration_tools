"""Skill registry exporters — RE_AUDIT_2026-08-26 (god-object 3/5).

Extracted from skill_registry.py (658→500 LOC). The 3 export_to_*
methods are still callable as SkillRegistry methods for backward
compatibility, but their logic now lives in pure functions here.

Exports:
* to_mcp(skills) — MCP tool format
* to_langgraph(skills) — LangGraph tool format
* to_openai_tools(skills) — OpenAI function-calling spec format

Each function is a pure transformation (skills → exported list).
This makes them:
* Trivially testable in isolation
* Reusable from any caller (not just SkillRegistry)
* Single responsibility per file (exporting vs registry management)
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "to_mcp",
    "to_langgraph",
    "to_openai_tools",
)


def to_mcp(skills: list[Any]) -> list[Any]:
    """Экспортировать skills с ``"mcp"`` в :attr:`SkillSpec.protocols`.

    Returns:
        Список MCP-совместимых tool specs.

    """
    tools: list[dict[str, Any]] = []
    for skill in skills:
        if "mcp" not in (skill.protocols or []):
            continue
        tools.append(
            {
                "name": skill.id,
                "description": skill.description or "",
                "inputSchema": skill.input_schema or {"type": "object", "properties": {}},
            }
        )
    return tools


def to_langgraph(skills: list[Any]) -> list[Any]:
    """Экспортировать skills с ``"langgraph"`` в protocols.

    Returns:
        Список LangGraph tool adapters.

    """
    tools: list[dict[str, Any]] = []
    for skill in skills:
        if "langgraph" not in (skill.protocols or []):
            continue
        tools.append(
            {
                "name": skill.id,
                "description": skill.description or "",
                "args_schema": skill.input_schema or {"type": "object", "properties": {}},
                "func_ref": f"src.backend.skills.{skill.id}",
            }
        )
    return tools


def to_openai_tools(skills: list[Any]) -> list[dict[str, Any]]:
    """Экспортировать skills как OpenAI function-calling spec.

    Returns:
        Список dict-ов формата OpenAI tools.

    """
    tools: list[dict[str, Any]] = []
    for skill in skills:
        params = skill.input_schema or {"type": "object", "properties": {}}
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": skill.id,
                    "description": skill.description or "",
                    "parameters": params,
                },
            }
        )
    return tools
