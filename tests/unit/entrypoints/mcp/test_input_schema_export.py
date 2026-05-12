"""Тесты native inputSchema экспорта MCP (Wave D.4)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel


class _DemoModel(BaseModel):
    """Демо payload-модель."""

    name: str
    age: int


class _MCPStub:
    """Stub FastMCP, поддерживающий native input_schema."""

    def __init__(self) -> None:
        self.registered: list[dict[str, Any]] = []

    def tool(
        self,
        *,
        name: str = "<anon>",
        description: str = "",
        input_schema: dict | None = None,
        inputSchema: dict | None = None,  # noqa: N803
    ):
        captured = {
            "name": name,
            "description": description,
            "input_schema": input_schema or inputSchema,
        }

        def decorator(fn):  # noqa: ANN001
            self.registered.append(captured)
            return fn

        return decorator


@pytest.mark.asyncio
async def test_register_single_tool_passes_native_input_schema() -> None:
    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.entrypoints.mcp.mcp_server import _register_single_tool

    metadata_cls = type(action_handler_registry.get_metadata)
    captured_action = "demo.action"

    class _FakeMeta:
        input_model = _DemoModel

    from src.backend.entrypoints.mcp import mcp_server

    original_get_metadata = action_handler_registry.get_metadata
    action_handler_registry.get_metadata = lambda name: (  # type: ignore[assignment]
        _FakeMeta() if name == captured_action else None
    )
    try:
        mcp = _MCPStub()
        _register_single_tool(mcp, captured_action)
        assert len(mcp.registered) == 1
        spec = mcp.registered[0]
        assert spec["input_schema"] is not None
        assert "properties" in spec["input_schema"]
        assert "Payload (JSON-Schema):" not in spec["description"]
    finally:
        action_handler_registry.get_metadata = original_get_metadata  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_legacy_description_inline_when_flag_enabled() -> None:
    from src.backend.core.config import ai_2026 as cfg
    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.entrypoints.mcp.mcp_server import _register_single_tool

    class _FakeMeta:
        input_model = _DemoModel

    original_get_metadata = action_handler_registry.get_metadata
    original_legacy = cfg.mcp_settings.legacy_description_schema
    action_handler_registry.get_metadata = lambda name: _FakeMeta()  # type: ignore[assignment]
    cfg.mcp_settings.legacy_description_schema = True
    try:
        mcp = _MCPStub()
        _register_single_tool(mcp, "x.y")
        spec = mcp.registered[0]
        assert "Payload (JSON-Schema):" in spec["description"]
        assert spec["input_schema"] is not None
    finally:
        action_handler_registry.get_metadata = original_get_metadata  # type: ignore[assignment]
        cfg.mcp_settings.legacy_description_schema = original_legacy
