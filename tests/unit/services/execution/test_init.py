"""Unit-тесты ``services.execution`` — coverage ratchet (Post-Plan A Sprint 6).

core/execution services package facade (W14.1 + W22): re-exports 8 symbols —
DefaultActionDispatcher + get_action_dispatcher + InvocationMode + Invoker
+ get_invoker + AuditMiddleware + IdempotencyMiddleware + RateLimitMiddleware.
~12 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.services import execution
from src.backend.services.execution import (
    AuditMiddleware,
    DefaultActionDispatcher,
    IdempotencyMiddleware,
    InvocationMode,
    Invoker,
    RateLimitMiddleware,
    get_action_dispatcher,
    get_invoker,
)


@pytest.mark.unit
class TestExecutionFacadeAllExports:
    """``__all__`` audit + class/callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "AuditMiddleware",
            "DefaultActionDispatcher",
            "IdempotencyMiddleware",
            "InvocationMode",
            "Invoker",
            "RateLimitMiddleware",
            "get_action_dispatcher",
            "get_invoker",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(execution, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in execution.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 8 символов."""
        assert len(execution.__all__) == 8

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает execution services (W14.1, W22)."""
        assert execution.__doc__ is not None
        assert "execution" in execution.__doc__.lower()


@pytest.mark.unit
class TestExecutionFacadeIdentity:
    """Identity checks для 8 re-exports."""

    def test_default_action_dispatcher_is_class(self) -> None:
        """``DefaultActionDispatcher`` — class (ActionDispatcher impl)."""
        assert isinstance(DefaultActionDispatcher, type)

    def test_invoker_is_class(self) -> None:
        """``Invoker`` — class (main Gateway)."""
        assert isinstance(Invoker, type)

    def test_invocation_mode_is_class(self) -> None:
        """``InvocationMode`` — class (enum of invocation modes)."""
        assert isinstance(InvocationMode, type)

    def test_audit_middleware_is_class(self) -> None:
        """``AuditMiddleware`` — class (audit middleware)."""
        assert isinstance(AuditMiddleware, type)

    def test_idempotency_middleware_is_class(self) -> None:
        """``IdempotencyMiddleware`` — class (idempotency middleware)."""
        assert isinstance(IdempotencyMiddleware, type)

    def test_rate_limit_middleware_is_class(self) -> None:
        """``RateLimitMiddleware`` — class (rate limit middleware)."""
        assert isinstance(RateLimitMiddleware, type)

    def test_get_action_dispatcher_is_callable(self) -> None:
        """``get_action_dispatcher`` — callable (singleton getter)."""
        assert callable(get_action_dispatcher)

    def test_get_invoker_is_callable(self) -> None:
        """``get_invoker`` — callable (singleton getter)."""
        assert callable(get_invoker)
