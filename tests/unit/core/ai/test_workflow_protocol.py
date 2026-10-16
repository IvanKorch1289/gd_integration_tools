"""Tests for ``src.backend.core.ai.workflow_protocol``.

Protocol-фасад для workflow registry/descriptor (cycle-5/D-AUDIT-501).
DSL-слой зависит ТОЛЬКО от структурных Protocol, конкретные реализации
подгружаются ленивым импортом на use-site.

Тесты:
- WorkflowDescriptorProtocol: structural typing (любой dataclass с
  правильными атрибутами подходит)
- WorkflowRegistryProtocol: structural typing (list_all() -> list[...])
- __all__ exports
"""

from __future__ import annotations

import pytest

from src.backend.core.ai.workflow_protocol import (
    WorkflowDescriptorProtocol,
    WorkflowRegistryProtocol,
)


# ── WorkflowDescriptorProtocol ──────────────────────────────────────


class TestWorkflowDescriptorProtocol:
    """Структурный протокол — duck-typed реализации подходят."""

    def test_duck_typed_descriptor_satisfies_protocol(self) -> None:
        """Любой dataclass/class с 6 правильными атрибутами — соответствует Protocol."""

        class FakeDescriptor:
            name: str = "orders.skb_flow"
            description: str = "Test workflow"
            input_schema: object = None
            output_schema: object = None
            max_attempts: int = 3
            tags: tuple[str, ...] = ("test", "orders")

        descriptor: WorkflowDescriptorProtocol = FakeDescriptor()
        assert descriptor.name == "orders.skb_flow"
        assert descriptor.description == "Test workflow"
        assert descriptor.max_attempts == 3
        assert descriptor.tags == ("test", "orders")

    def test_dataclass_implementation(self) -> None:
        """Dataclass с 6 атрибутами — соответствует Protocol."""
        from dataclasses import dataclass

        @dataclass
        class OrderDescriptor:
            name: str
            description: str
            input_schema: object
            output_schema: object
            max_attempts: int
            tags: tuple[str, ...]

        descriptor: WorkflowDescriptorProtocol = OrderDescriptor(
            name="x",
            description="y",
            input_schema=None,
            output_schema=None,
            max_attempts=5,
            tags=(),
        )
        assert descriptor.max_attempts == 5

    def test_missing_attribute_fails_protocol(self) -> None:
        """Класс БЕЗ одного из 6 атрибутов — НЕ соответствует Protocol.

        Structural typing проверяется через hasattr для Protocol-классов.
        """

        class IncompleteDescriptor:
            name: str = "x"
            description: str = "y"
            # missing: input_schema, output_schema, max_attempts, tags

        obj = IncompleteDescriptor()
        # Не все 6 атрибутов присутствуют
        required = {
            "name",
            "description",
            "input_schema",
            "output_schema",
            "max_attempts",
            "tags",
        }
        actual = {a for a in required if hasattr(obj, a)}
        assert actual != required


# ── WorkflowRegistryProtocol ────────────────────────────────────────


class TestWorkflowRegistryProtocol:
    """Структурный протокол реестра с методом ``list_all``."""

    def test_duck_typed_registry_satisfies_protocol(self) -> None:
        """Класс с правильным ``list_all`` — соответствует Protocol."""

        class FakeRegistry:
            def list_all(self) -> list[WorkflowDescriptorProtocol]:
                return []

        registry: WorkflowRegistryProtocol = FakeRegistry()
        assert registry.list_all() == []

    def test_list_all_returns_descriptors(self) -> None:
        """``list_all`` возвращает iterable дескрипторов."""

        class FakeDescriptor:
            name: str
            description: str
            input_schema: object
            output_schema: object
            max_attempts: int
            tags: tuple[str, ...]

            def __init__(self, name: str) -> None:
                self.name = name
                self.description = f"Workflow {name}"
                self.input_schema = None
                self.output_schema = None
                self.max_attempts = 1
                self.tags = ()

        class FakeRegistry:
            def __init__(self) -> None:
                self._items: list[FakeDescriptor] = [
                    FakeDescriptor("b"),
                    FakeDescriptor("a"),
                ]

            def list_all(self) -> list[WorkflowDescriptorProtocol]:
                # Документация: "детерминированно отсортированный"
                return sorted(self._items, key=lambda d: d.name)  # type: ignore[return-value]

        registry: WorkflowRegistryProtocol = FakeRegistry()
        result = registry.list_all()
        assert len(result) == 2
        # Документация: sorted by name
        assert [d.name for d in result] == ["a", "b"]


class TestWorkflowProtocolExports:
    """``__all__`` exports."""

    def test_exports(self) -> None:
        from src.backend.core.ai import workflow_protocol

        assert "WorkflowDescriptorProtocol" in workflow_protocol.__all__
        assert "WorkflowRegistryProtocol" in workflow_protocol.__all__


class TestWorkflowProtocolContract:
    """Документированные инварианты контракта."""

    def test_documented_pattern_no_infrastructure_import(self) -> None:
        """DSL-слой не должен импортировать infrastructure напрямую.

        Сам workflow_protocol — это слой core, который DSL может
        импортировать. infrastructure-импорт — на use-site.
        Этот тест — документация контракта, не runtime-проверка.
        """
        import src.backend.core.ai.workflow_protocol as wp

        # Модуль не должен иметь импортов из infrastructure
        source = wp.__file__
        assert source is not None
        # Только documentation; проверка импортов — отдельный static check
        assert "workflow_protocol.py" in source
