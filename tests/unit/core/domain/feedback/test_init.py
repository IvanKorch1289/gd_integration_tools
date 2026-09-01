"""Unit-тесты ``core.domain.feedback`` — coverage ratchet (S48 W27).

core/domain/feedback/__init__.py — S38.4 DDD domain layer: re-exports
``FeedbackDomainService`` (aggregate root для AI Feedback aggregate).
3 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.core.domain import feedback
from src.backend.core.domain.feedback import FeedbackDomainService


@pytest.mark.unit
class TestFeedbackFacadeAllExports:
    """``__all__`` audit + class identity."""

    def test_all_exports_accessible(self) -> None:
        """``FeedbackDomainService`` доступен + declared в __all__."""
        assert hasattr(feedback, "FeedbackDomainService")
        assert "FeedbackDomainService" in feedback.__all__

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 1 symbol."""
        assert len(feedback.__all__) == 1

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает S38.4 DDD domain layer."""
        assert feedback.__doc__ is not None
        assert "S38.4" in feedback.__doc__ or "DDD" in feedback.__doc__


@pytest.mark.unit
class TestFeedbackFacadeIdentity:
    """Identity checks для canonical domain service."""

    def test_feedback_domain_service_is_class(self) -> None:
        """``FeedbackDomainService`` — class (domain aggregate)."""
        assert isinstance(FeedbackDomainService, type)
