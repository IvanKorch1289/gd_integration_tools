"""Unit-тесты ``services.execution.invoker`` — coverage ratchet (Post-Plan A Sprint 8).

core/execution/invoker subpackage (S68 W3 decomp): re-exports 8 symbols
(Invoker + InvocationMode + get_invoker + 4 private helpers). ~10 stmts, 0%.

Цель slice: 0% → 100% через __all__ audit + class/callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.execution import invoker


@pytest.mark.unit
class TestInvokerFacadeAllExports:
    """``__all__`` audit + class/callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "Invoker",
            "InvocationMode",
            "get_invoker",
            "_deserialize_request",
            "_is_async_iterator",
            "_run_deferred_job",
            "_serialize_request",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(invoker, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in invoker.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 7 символов."""
        assert len(invoker.__all__) == 7

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает S68 W3 decomp."""
        assert invoker.__doc__ is not None
        assert "S68 W3" in invoker.__doc__ or "Invoker" in invoker.__doc__


@pytest.mark.unit
class TestInvokerFacadeIdentity:
    """Identity checks для 7 re-exports."""

    def test_invoker_is_class(self) -> None:
        """``Invoker`` — class (main Gateway class)."""
        assert isinstance(invoker.Invoker, type)

    def test_invocation_mode_is_class(self) -> None:
        """``InvocationMode`` — class (enum of invocation modes)."""
        assert isinstance(invoker.InvocationMode, type)

    def test_get_invoker_is_callable(self) -> None:
        """``get_invoker`` — callable (singleton getter)."""
        assert callable(invoker.get_invoker)

    def test_deserialize_request_is_callable(self) -> None:
        """``_deserialize_request`` — callable (private helper, re-exported)."""
        assert callable(invoker._deserialize_request)

    def test_is_async_iterator_is_callable(self) -> None:
        """``_is_async_iterator`` — callable (private helper, re-exported)."""
        assert callable(invoker._is_async_iterator)

    def test_run_deferred_job_is_callable(self) -> None:
        """``_run_deferred_job`` — callable (private helper, re-exported)."""
        assert callable(invoker._run_deferred_job)

    def test_serialize_request_is_callable(self) -> None:
        """``_serialize_request`` — callable (private helper, re-exported)."""
        assert callable(invoker._serialize_request)
