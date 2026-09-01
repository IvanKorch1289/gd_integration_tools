"""Unit-тесты ``core.types`` — coverage ratchet (S48 W25).

core/types/__init__.py — facade для core-уровневых DTO/Pydantic types
(ActionCommandSchema, ActionCommandMetaSchema, InvocationOptionsSchema,
InvocationResultSchema) — перенесены из schemas/ для устранения core → schemas
layer-violation. 6 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.core import types as core_types
from src.backend.core.types import (
    ActionCommandMetaSchema,
    ActionCommandSchema,
    InvocationOptionsSchema,
    InvocationResultSchema,
)


@pytest.mark.unit
class TestTypesFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "ActionCommandMetaSchema",
            "ActionCommandSchema",
            "InvocationOptionsSchema",
            "InvocationResultSchema",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(core_types, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in core_types.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа."""
        assert len(core_types.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает core DTO types (S120 W1+ refactor)."""
        assert core_types.__doc__ is not None
        assert "DTO" in core_types.__doc__ or "core" in core_types.__doc__


@pytest.mark.unit
class TestTypesFacadeIdentity:
    """Identity checks: canonical Pydantic schemas."""

    def test_action_command_schema_is_class(self) -> None:
        """``ActionCommandSchema`` — class (Pydantic model)."""
        assert isinstance(ActionCommandSchema, type)

    def test_action_command_meta_schema_is_class(self) -> None:
        """``ActionCommandMetaSchema`` — class (Pydantic model)."""
        assert isinstance(ActionCommandMetaSchema, type)

    def test_invocation_options_schema_is_class(self) -> None:
        """``InvocationOptionsSchema`` — class (Pydantic model)."""
        assert isinstance(InvocationOptionsSchema, type)

    def test_invocation_result_schema_is_class(self) -> None:
        """``InvocationResultSchema`` — class (Pydantic model)."""
        assert isinstance(InvocationResultSchema, type)
