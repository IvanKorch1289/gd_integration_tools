"""Unit-тесты ``services.ai.eval.suites`` — coverage ratchet (Post-Plan A Sprint 16).

core/ai/eval/suites subpackage (K4 S6 W1): re-exports 7 reference Inspect AI
suites (knowledge_qa, instruction_following, hallucination_check, safety,
context_recall, tool_use, multi_turn_coherence). ~25 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + callable identity.

NOTE: ``REFERENCE_SUITES`` is the only symbol в ``__all__`` — это tuple
containing all 7 suites. Проверяем tuple identity + length.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai.eval import suites


@pytest.mark.unit
class TestEvalSuitesFacadeAllExports:
    """``__all__`` audit + REFERENCE_SUITES tuple identity."""

    def test_reference_suites_in_all(self) -> None:
        """``REFERENCE_SUITES`` доступен через facade."""
        assert hasattr(suites, "REFERENCE_SUITES")
        assert "REFERENCE_SUITES" in suites.__all__

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 1 symbol."""
        assert len(suites.__all__) == 1

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает reference Inspect AI suites (K4 S6 W1)."""
        assert suites.__doc__ is not None
        assert "Inspect" in suites.__doc__ or "suite" in suites.__doc__.lower()


@pytest.mark.unit
class TestEvalSuitesFacadeIdentity:
    """Identity checks для ``REFERENCE_SUITES`` tuple + 7 suite callables."""

    def test_reference_suites_is_tuple(self) -> None:
        """``REFERENCE_SUITES`` — tuple of 7 suites."""
        assert isinstance(suites.REFERENCE_SUITES, tuple)
        assert len(suites.REFERENCE_SUITES) == 7

    def test_reference_suites_contains_all_suites(self) -> None:
        """``REFERENCE_SUITES`` содержит все 7 suite objects (Inspect AI Task)."""
        for suite in suites.REFERENCE_SUITES:
            # Inspect AI Task objects have ``name`` + ``description`` attrs
            assert hasattr(suite, "name"), f"{suite!r} missing 'name'"
            assert hasattr(suite, "description"), (
                f"{suite!r} missing 'description'"
            )
