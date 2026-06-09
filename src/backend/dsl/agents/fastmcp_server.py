"""FastMCPserver — MCP-native tool exposure (GAP-AI-1, S35).

Wraps :class:`mcp.server.fastmcp.FastMCP` and exports:

* **SkillRegistry tools** — all skills with ``"mcp"`` in their :attr:`SkillSpec.protocols`
  list are exposed as MCP tools with JSON-Schema input validation.
* **Workflow definitions** — every :class:`WorkflowDescriptor` registered in
  :data:`workflow_registry` is exposed as an **MCP prompt**, so AI clients
  can reason about available business processes without invoking them directly.
* **Tool handler** — calls :meth:`SkillRegistry.invoke` and returns JSON-serialised
  results.

The :meth:`asgi_app` property returns the ASGI application that can be mounted
in any ASGI-compatible server (uvicorn, FastAPI, etc.) at path ``/mcp``.

Integration
-----------
* :mod:`src.backend.entrypoints.fastmcp` creates a FastAPI app and mounts
  the ASGI app at ``/mcp``.

S35 GAP-AI-1
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts.base import Prompt, PromptArgument

from src.backend.core.ai.skill_registry import SkillRegistry, SkillSpec
from src.backend.core.logging import get_logger
from src.backend.workflows.registry import WorkflowDescriptor, workflow_registry

__all__ = ("FastMCPserver",)

logger = get_logger("dsl.agents.fastmcp_server")


# ── Workflow prompts ──────────────────────────────────────────────────────────


def _build_workflow_prompt_fn(wf: WorkflowDescriptor) -> Any:
    """Build an async prompt function that returns workflow catalogue information."""

    async def prompt_fn(
        payload: str = "{}", wait: bool = False, timeout_s: int = 300
    ) -> str:
        """Return workflow catalogue information (read-only)."""
        return json.dumps(
            {
                "workflow_name": wf.name,
                "description": wf.description,
                "tags": list(wf.tags),
                "input_schema": (
                    wf.input_schema.model_json_schema()
                    if wf.input_schema
                    else {"type": "object"}
                ),
                "message": (
                    "This is a catalogue prompt. "
                    f"To execute workflow '{wf.name}', use the workflow tool with "
                    f"payload={payload}, wait={wait}, timeout_s={timeout_s}"
                ),
            },
            ensure_ascii=False,
            default=str,
        )

    return prompt_fn


# ── FastMCPserver ─────────────────────────────────────────────────────────────


class FastMCPserver:
    """MCP-native tool exporter wrapping :class:`mcp.server.fastmcp.FastMCP`.

    Args:
        skill_registry: SkillRegistry instance to export tools from.
            Defaults to a fresh :class:`SkillRegistry` instance.
        host: Bind address stored for reference (used by the caller).
        port: Bind port stored for reference (used by the caller).

    Methods:
        asgi_app: Returns the ASGI Starlette application (mount in FastAPI).
        start: No-op for this class — lifecycle is managed by the caller.
        stop: No-op for this class.
    """

    def __init__(
        self,
        skill_registry: SkillRegistry | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        self._skill_registry = skill_registry or SkillRegistry()
        self._host = host
        self._port = port
        self._mcp: FastMCP | None = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def host(self) -> str:
        """Bind address."""
        return self._host

    @property
    def port(self) -> int:
        """Bind port."""
        return self._port

    @property
    def asgi_app(self) -> Any:
        """Return the ASGI Starlette application.

        Mount this in FastAPI at path ``/mcp``::

            app.mount("/mcp", fastmcp_server.asgi_app)
        """
        self._ensure_mcp()
        assert self._mcp is not None
        return self._mcp.streamable_http_app()

    # ── Lifecycle (no-ops — managed by caller) ────────────────────────────────

    async def start(self) -> None:
        """No-op. Server is managed by the ASGI host (uvicorn/FastAPI)."""
        logger.debug(
            "FastMCPserver.start() called — ASGI app lifecycle managed by caller"
        )

    async def stop(self) -> None:
        """No-op. Server is managed by the ASGI host (uvicorn/FastAPI)."""
        logger.debug(
            "FastMCPserver.stop() called — ASGI app lifecycle managed by caller"
        )

    # ── Internal ─────────────────────────────────────────────────────────────

    def _ensure_mcp(self) -> None:
        """Lazily initialise the FastMCP instance and register tools/prompts."""
        if self._mcp is not None:
            return

        self._mcp = FastMCP(
            "gd-integration-tools-mcp",
            instructions=(
                "GD Integration Tools MCP server — exposes AI skills "
                "(SkillRegistry) and durable workflows as tools and prompts."
            ),
        )

        self._register_tools()
        self._register_prompts()

    def _register_tools(self) -> None:
        """Register all SkillRegistry skills with ``"mcp"`` in protocols as MCP tools."""
        self._ensure_mcp()
        assert self._mcp is not None

        for skill in self._skill_registry.list_skills():
            if "mcp" not in skill.protocols and "all" not in skill.protocols:
                continue
            tool_name = skill.id.replace(".", "_").replace("-", "_")
            self._mcp.add_tool(
                _build_tool_callback(skill, self._skill_registry),
                name=tool_name,
                description=skill.description or f"Skill: {skill.id}",
            )

        logger.info(
            "FastMCPserver registered %d tools from SkillRegistry",
            len(self._skill_registry.list_skills()),
        )

    def _register_prompts(self) -> None:
        """Register workflow definitions as MCP prompts (read-only catalogue)."""
        self._ensure_mcp()
        assert self._mcp is not None

        for wf in workflow_registry.list_all():
            safe_name = f"workflow_{wf.name.replace('.', '_').replace('-', '_')}"
            prompt_fn = _build_workflow_prompt_fn(wf)
            prompt_obj = Prompt(
                name=safe_name,
                title=None,
                description=wf.description or f"Workflow catalogue: {wf.name}",
                arguments=[
                    PromptArgument(
                        name="payload",
                        description="JSON payload for the workflow",
                        required=True,
                    ),
                    PromptArgument(
                        name="wait",
                        description="Wait for workflow completion",
                        required=False,
                    ),
                    PromptArgument(
                        name="timeout_s",
                        description="Timeout in seconds",
                        required=False,
                    ),
                ],
                fn=prompt_fn,
                context_kwarg=None,
            )
            self._mcp.add_prompt(prompt_obj)

        logger.info(
            "FastMCPserver registered %d workflow prompts",
            len(workflow_registry.list_all()),
        )


# ── Tool callback factory ──────────────────────────────────────────────────────


def _build_tool_callback(skill: SkillSpec, registry: SkillRegistry) -> Any:
    """Build an async tool callback for a given SkillSpec."""

    async def tool_callback(arguments: dict[str, Any]) -> str:
        try:
            result = await registry.invoke(skill.id, **arguments)
            return json.dumps(result, default=str, ensure_ascii=False)
        except Exception as exc:
            logger.exception("Skill %s failed: %s", skill.id, exc)
            return json.dumps({"error": str(exc)})

    return tool_callback
