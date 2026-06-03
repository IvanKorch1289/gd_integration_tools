"""Unit tests for BindSkillProcessor.

Covers: no registry, pack not found, bind to agent, bind to output key.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.processors.agent_dsl.bind_skill import (
    BindSkillProcessor,
)


class _Exchange:
    def __init__(self) -> None:
        self.properties: dict[str, Any] = {}

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value


class _Context:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = data or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value


class TestBindSkillProcessor:
    """Tests for :class:`BindSkillProcessor`."""

    @pytest.mark.asyncio
    async def test_no_registry_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Without skill_registry in context, processor logs and returns."""
        proc = BindSkillProcessor(pack_id="pk1")
        exchange = _Exchange()
        context = _Context()
        await proc._run(exchange, context)
        assert "skill_registry not in context" in caplog.text

    @pytest.mark.asyncio
    async def test_pack_not_found_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """When pack is not found, processor logs and returns."""
        proc = BindSkillProcessor(pack_id="pk1")
        exchange = _Exchange()
        registry = AsyncMock()
        registry.get_skill_pack.return_value = None
        registry.list_skill_packs.return_value = []
        context = _Context({"skill_registry": registry})
        await proc._run(exchange, context)
        assert "pack_id='pk1' not found" in caplog.text

    @pytest.mark.asyncio
    async def test_bind_to_agent(self) -> None:
        """Binds pack to target_agent in context."""
        proc = BindSkillProcessor(pack_id="pk1", target_agent="agent1")
        exchange = _Exchange()
        pack = {"id": "pk1", "skills": ["s1"]}
        registry = AsyncMock()
        registry.get_skill_pack.return_value = pack
        context = _Context({"skill_registry": registry})
        await proc._run(exchange, context)
        bound = context.get("bound_agents")
        assert bound == {"agent1": pack}

    @pytest.mark.asyncio
    async def test_bind_to_output_key(self) -> None:
        """Binds pack to exchange property when no target_agent."""
        proc = BindSkillProcessor(pack_id="pk1", output_key="skills")
        exchange = _Exchange()
        pack = {"id": "pk1"}
        registry = AsyncMock()
        registry.get_skill_pack.return_value = pack
        context = _Context({"skill_registry": registry})
        await proc._run(exchange, context)
        assert exchange.properties["skills"] == pack

    @pytest.mark.asyncio
    async def test_resolve_pack_via_list(self) -> None:
        """Fallback to list_skill_packs when get_skill_pack is absent."""
        proc = BindSkillProcessor(pack_id="pk1")
        exchange = _Exchange()
        pack = {"id": "pk1"}
        registry = MagicMock(spec=["list_skill_packs"])
        registry.list_skill_packs = AsyncMock(return_value=[pack])
        context = _Context({"skill_registry": registry})
        await proc._run(exchange, context)
        assert exchange.properties.get("skills") is None  # no output_key
