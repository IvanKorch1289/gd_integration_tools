"""Unit-тесты ``services.execution.middlewares`` — coverage ratchet (Post-Plan A Sprint 7).

core/execution middlewares subpackage (W14.1.C + ADR-0062): re-exports
3 middleware classes (Audit, Idempotency, RateLimit). ~6 stmts, 0%.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.execution import middlewares
from src.backend.services.execution.middlewares import (
    AuditMiddleware,
    IdempotencyMiddleware,
    RateLimitMiddleware,
)


@pytest.mark.unit
class TestMiddlewaresFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["AuditMiddleware", "IdempotencyMiddleware", "RateLimitMiddleware"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(middlewares, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in middlewares.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 3 символа."""
        assert len(middlewares.__all__) == 3

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает middleware subpackage (W14.1.C, ADR-0062)."""
        assert middlewares.__doc__ is not None
        assert "middleware" in middlewares.__doc__.lower()


@pytest.mark.unit
class TestMiddlewaresFacadeIdentity:
    """Identity checks для 3 middleware classes."""

    def test_audit_middleware_is_class(self) -> None:
        """``AuditMiddleware`` — class (audit logging middleware)."""
        assert isinstance(AuditMiddleware, type)

    def test_idempotency_middleware_is_class(self) -> None:
        """``IdempotencyMiddleware`` — class (idempotency cache middleware)."""
        assert isinstance(IdempotencyMiddleware, type)

    def test_rate_limit_middleware_is_class(self) -> None:
        """``RateLimitMiddleware`` — class (rate limit middleware)."""
        assert isinstance(RateLimitMiddleware, type)
