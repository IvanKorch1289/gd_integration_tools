"""Unit-тесты ``services.ai.gateway`` — coverage ratchet (Post-Plan A Sprint 19).

core/ai/gateway service package facade (LiteLLM Gateway, К4 MVP): re-exports
5 symbols (LiteLLMGateway class + get_litellm_gateway singleton getter +
3 Exception classes GatewayError/GatewayRateLimited/GatewayUnavailable).
~8 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import gateway
from src.backend.services.ai.gateway import (
    GatewayError,
    GatewayRateLimited,
    GatewayUnavailable,
    LiteLLMGateway,
    get_litellm_gateway,
)


@pytest.mark.unit
class TestGatewayFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "GatewayError",
            "GatewayRateLimited",
            "GatewayUnavailable",
            "LiteLLMGateway",
            "get_litellm_gateway",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(gateway, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in gateway.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 5 символов."""
        assert len(gateway.__all__) == 5

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает LiteLLM Gateway (К4 MVP)."""
        assert gateway.__doc__ is not None
        assert "LiteLLM" in gateway.__doc__ or "Gateway" in gateway.__doc__


@pytest.mark.unit
class TestGatewayFacadeIdentity:
    """Identity checks для 5 re-exports."""

    def test_litellm_gateway_is_class(self) -> None:
        """``LiteLLMGateway`` — class (unified LLM client)."""
        assert isinstance(LiteLLMGateway, type)

    def test_get_litellm_gateway_is_callable(self) -> None:
        """``get_litellm_gateway`` — callable (singleton getter)."""
        assert callable(get_litellm_gateway)

    def test_gateway_error_is_exception(self) -> None:
        """``GatewayError`` — Exception subclass (base for other Gateway errors)."""
        assert isinstance(GatewayError, type)
        assert issubclass(GatewayError, Exception)

    def test_gateway_rate_limited_is_exception(self) -> None:
        """``GatewayRateLimited`` — Exception subclass (likely extends GatewayError)."""
        assert isinstance(GatewayRateLimited, type)
        assert issubclass(GatewayRateLimited, Exception)
        # Per convention, RateLimited extends base GatewayError:
        assert issubclass(GatewayRateLimited, GatewayError)

    def test_gateway_unavailable_is_exception(self) -> None:
        """``GatewayUnavailable`` — Exception subclass."""
        assert isinstance(GatewayUnavailable, type)
        assert issubclass(GatewayUnavailable, Exception)
        assert issubclass(GatewayUnavailable, GatewayError)
