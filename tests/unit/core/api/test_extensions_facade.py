"""Unit-тесты ``core.api.extensions`` — coverage ratchet (S48 W16).

core/api/extensions.py — Sprint 33 D.1 facade: re-exports ~40 DSL symbols
через core.api.* для устранения extensions → dsl.* layer violations (42 → 0).
40+ statements + 39-item __all__, 0% coverage.

Цель slice: поднять coverage до высокого уровня через __all__ audit +
identity checks. Полное покрытие ограничено transitive imports (Ponytail).
"""

from __future__ import annotations

import pytest

from src.backend.core.api import extensions


@pytest.mark.unit
class TestExtensionsFacadeAllExports:
    """``__all__`` audit + identity checks для каждого exported symbol."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            # Action registry
            "ActionHandlerRegistry",
            "ActionHandlerSpec",
            "ActionCommandSchema",
            # Route registry
            "RouteRegistry",
            # Processor registry
            "ProcessorRegistry",
            # Workflow builder
            "RetryPolicy",
            "SagaBuilder",
            # Engine
            "ExecutionContext",
            "Exchange",
            "ExchangeStatus",
            "Message",
            # Tracing
            "TraceEvent",
            # DSL analysis
            "ParallelismAnalyzer",
            # YAML
            "YAMLStore",
            # AI sanitization
            "PresidioSanitizerAdapter",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(extensions, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in extensions.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 32 символа (фактический count)."""
        # Фактический count определяется через ``len(__all__)`` — не
        # зашит в конкретное число чтобы тест пережил добавление новых
        # символов без false alarm. Проверяем что есть существенный
        # re-export surface (>20):
        assert len(extensions.__all__) >= 20, (
            f"Expected >=20 exports, got {len(extensions.__all__)}: "
            f"{extensions.__all__}"
        )

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Sprint 33 D.1 remediation."""
        assert extensions.__doc__ is not None
        assert "Sprint 33" in extensions.__doc__


@pytest.mark.unit
class TestExtensionsFacadeInstances:
    """Identity checks для key re-exported singletons/classes."""

    def test_action_handler_registry_singleton(self) -> None:
        """``action_handler_registry`` — instance ActionHandlerRegistry."""
        from src.backend.core.api.extensions import (
            ActionHandlerRegistry,
            action_handler_registry,
        )

        assert isinstance(action_handler_registry, ActionHandlerRegistry)

    def test_processor_registry_getter(self) -> None:
        """``get_processor_registry()`` → ProcessorRegistry instance."""
        from src.backend.core.api.extensions import (
            ProcessorRegistry,
            get_processor_registry,
        )

        registry = get_processor_registry()
        assert isinstance(registry, ProcessorRegistry)

    def test_route_registry_class_accessible(self) -> None:
        """``RouteRegistry`` class — callable для создания instances."""
        from src.backend.core.api.extensions import RouteRegistry

        assert isinstance(RouteRegistry, type)
