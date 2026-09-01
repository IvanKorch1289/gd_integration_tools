"""Unit-тесты ``core.actions`` — coverage ratchet (S49 W4).

core/actions/__init__.py — Wave 14.1.B action adapters facade: re-exports
``action_spec_to_metadata`` (single export). 7 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + callable identity + smoke test.
"""

from __future__ import annotations

import pytest

from src.backend.core import actions
from src.backend.core.actions import action_spec_to_metadata


@pytest.mark.unit
class TestActionsFacadeAllExports:
    """``__all__`` audit + callable identity."""

    def test_all_exports_accessible(self) -> None:
        """``action_spec_to_metadata`` доступен через facade."""
        assert hasattr(actions, "action_spec_to_metadata")
        assert "action_spec_to_metadata" in actions.__all__

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 1 symbol."""
        assert len(actions.__all__) == 1

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Wave 14.1.B action adapters."""
        assert actions.__doc__ is not None
        assert "Wave 14.1.B" in actions.__doc__ or "action" in actions.__doc__.lower()


@pytest.mark.unit
class TestActionsFacadeIdentity:
    """Identity checks для ``action_spec_to_metadata``."""

    def test_action_spec_to_metadata_is_callable(self) -> None:
        """``action_spec_to_metadata`` — callable (function)."""
        assert callable(action_spec_to_metadata)

    def test_action_spec_to_metadata_basic_call(self) -> None:
        """``action_spec_to_metadata(spec)`` — callable с простым dict.

        Note: функция ожидает ActionSpec (dataclass/pydantic) с attr ``.name``,
        НЕ dict. Тест проверяет что функция callable — semantic content не тестируется
        (требует setup ActionSpec fixture).
        """
        # Function exists and callable — content validation out of scope.
        assert callable(action_spec_to_metadata)
        # Smoke: dict without ``.name`` raises AttributeError (semantic contract).
        with pytest.raises(AttributeError, match="dict"):
            action_spec_to_metadata({"name": "x"})  # type: ignore[arg-type]
