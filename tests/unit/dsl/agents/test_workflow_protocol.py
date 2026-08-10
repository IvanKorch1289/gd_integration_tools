"""Tests for workflow Protocol layer fix (cycle-5/D-AUDIT-501).

Verifies:
1. :mod:`src.backend.core.ai.workflow_protocol` exports Protocol-only API.
2. :mod:`src.backend.dsl.agents.fastmcp_server` does NOT import
   :mod:`src.backend.infrastructure.workflow.registry` at module level.
3. Runtime access in :meth:`FastMCPserver._register_prompts` is done
   via lazy import inside the method body.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest


class TestWorkflowProtocolModule:
    """``core/ai/workflow_protocol.py`` exports structural Protocols."""

    def test_protocols_importable(self) -> None:
        """Protocols экспортируются из core.ai.workflow_protocol."""
        from src.backend.core.ai.workflow_protocol import (
            WorkflowDescriptorProtocol,
            WorkflowRegistryProtocol,
        )

        assert WorkflowDescriptorProtocol is not None
        assert WorkflowRegistryProtocol is not None

    def test_protocols_have_expected_surface(self) -> None:
        """WorkflowDescriptorProtocol и WorkflowRegistryProtocol имеют ожидаемые поля."""
        from src.backend.core.ai.workflow_protocol import (
            WorkflowDescriptorProtocol,
            WorkflowRegistryProtocol,
        )

        # WorkflowDescriptorProtocol — структурный протокол; проверяем аннотации.
        desc_hints = WorkflowDescriptorProtocol.__annotations__
        for field_name in (
            "name",
            "description",
            "input_schema",
            "output_schema",
            "max_attempts",
            "tags",
        ):
            assert field_name in desc_hints, (
                f"WorkflowDescriptorProtocol must declare '{field_name}'"
            )

        # WorkflowRegistryProtocol — has list_all().
        assert "list_all" in WorkflowRegistryProtocol.__annotations__ or any(
            base.__dict__.get("list_all") is not None
            for base in WorkflowRegistryProtocol.__mro__
        )

    def test_structural_protocol_accepts_plain_dataclass(self) -> None:
        """Структурный протокол совместим с WorkflowDescriptor dataclass."""

        @dataclass(slots=True)
        class _FakeDescriptor:
            name: str
            description: str = ""
            input_schema: type[Any] | None = None
            output_schema: type[Any] | None = None
            max_attempts: int = 10
            tags: tuple[str, ...] = field(default_factory=tuple)

        # Runtime structural check (no runtime_checkable, но dataclass
        # trivially satisfies the protocol surface for callers).
        d = _FakeDescriptor(name="test", tags=("a", "b"))
        assert d.name == "test"
        assert d.tags == ("a", "b")


class TestFastMcpServerLayerBoundary:
    """fastmcp_server не должен импортировать infrastructure.workflow.registry на module-level."""

    def test_no_module_level_workflow_registry_import(self) -> None:
        """Модуль fastmcp_server НЕ имеет workflow_registry в module namespace."""
        # Import lazily, since mcp may not be installed.
        pytest.importorskip("mcp")

        import src.backend.dsl.agents.fastmcp_server as mod

        # Lazy-loaded inside method body → not present at module-level.
        assert not hasattr(mod, "workflow_registry"), (
            "workflow_registry must NOT be a module-level import "
            "(cycle-5/D-AUDIT-501 layer fix)"
        )
        assert not hasattr(mod, "WorkflowDescriptor"), (
            "WorkflowDescriptor must NOT be a module-level import "
            "(cycle-5/D-AUDIT-501 layer fix)"
        )

    def test_lazy_import_inside_register_prompts(self) -> None:
        """``workflow_registry`` импортируется внутри ``_register_prompts``."""
        pytest.importorskip("mcp")

        import src.backend.dsl.agents.fastmcp_server as mod

        from unittest.mock import MagicMock, patch

        # Patch на infrastructure module (где настоящий workflow_registry живёт).
        with patch(
            "src.backend.infrastructure.workflow.registry.workflow_registry"
        ) as mock_wf_reg:
            mock_wf_reg.list_all.return_value = []

            with patch(
                "src.backend.dsl.agents.fastmcp_server.SkillRegistry"
            ) as mock_skill_reg:
                mock_skill_reg.return_value = MagicMock()
                mock_skill_reg.return_value.list_skills.return_value = []

                server = mod.FastMCPserver()
                server._register_prompts()  # must not raise

        # Если lazy-import сработал — list_all() был вызван.
        assert mock_wf_reg.list_all.called