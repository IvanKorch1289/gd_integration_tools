"""Unit-тесты ``core.ai.guardrails`` — coverage ratchet (S48 W33).

core/ai/guardrails/__init__.py — safety runtime facade для AI-агентов.
S48 W33 fix: убран broken import ``llamaguard`` (submodule не существует
в этой ревизии — TODO для реализации LlamaGuardRuntime). Facade остаётся
importable с пустым ``__all__``.

Цель slice: 0% → 100% через:
1. fix broken import (P0 — module был unimportable из-за missing llamaguard.py)
2. coverage тесты empty facade
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestGuardrailsFacadeEmpty:
    """Empty facade после fix broken import (S48 W33)."""

    def test_module_importable(self) -> None:
        """``core.ai.guardrails`` importable (после S48 W33 broken import fix)."""
        import src.backend.core.ai.guardrails as g  # noqa: F401

        assert g is not None

    def test_all_is_empty(self) -> None:
        """``__all__`` empty (submodule llamaguard.py ещё не реализован)."""
        import src.backend.core.ai.guardrails as g

        assert g.__all__ == ()

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Guardrails purpose + S48 W33 TODO."""
        import src.backend.core.ai.guardrails as g

        assert g.__doc__ is not None
        assert "Guardrails" in g.__doc__ or "safety" in g.__doc__.lower()

    def test_llamaguard_submodule_not_yet_implemented(self) -> None:
        """``llamaguard`` submodule отсутствует — TODO для будущей реализации.

        Это документированный gap (см. S48 W33 retro + module docstring).
        """
        import importlib.util

        spec = importlib.util.find_spec("src.backend.core.ai.guardrails.llamaguard")
        assert spec is None, "llamaguard submodule unexpectedly exists"
