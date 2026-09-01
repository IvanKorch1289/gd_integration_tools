"""Unit-тесты ``core.repositories`` — coverage ratchet (S48 W29).

core/repositories/__init__.py — S38.4 DDD facade: re-exports
``FeedbackRepository`` (abstract interface для AI Feedback aggregate
storage, независимый от конкретной infrastructure-реализации).
3 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.core import repositories as core_repos
from src.backend.core.repositories import FeedbackRepository


@pytest.mark.unit
class TestRepositoriesFacadeAllExports:
    """``__all__`` audit + class identity."""

    def test_all_exports_accessible(self) -> None:
        """``FeedbackRepository`` доступен + declared в __all__."""
        assert hasattr(core_repos, "FeedbackRepository")
        assert "FeedbackRepository" in core_repos.__all__

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 1 symbol."""
        assert len(core_repos.__all__) == 1

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает S38.4 DDD repository abstractions."""
        assert core_repos.__doc__ is not None
        assert "S38.4" in core_repos.__doc__ or "DDD" in core_repos.__doc__


@pytest.mark.unit
class TestRepositoriesFacadeIdentity:
    """Identity checks для canonical repository."""

    def test_feedback_repository_is_class(self) -> None:
        """``FeedbackRepository`` — class (abstract interface)."""
        assert isinstance(FeedbackRepository, type)
