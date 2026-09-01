"""Unit-тесты ``core.ai.gateway`` — coverage ratchet (S48 W32).

core/ai/gateway/__init__.py — S175 M2.1 ARC-009 facade subpackage:
re-exports AIGateway (main facade), AIRequest/AIResponse (external models),
EnforcedInvokeMixin (orchestrator mixin). 9 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity + mixin check.
"""

from __future__ import annotations

import pytest

from src.backend.core.ai import gateway
from src.backend.core.ai.gateway import (
    AIGateway,
    AIRequest,
    AIResponse,
    EnforcedInvokeMixin,
)


@pytest.mark.unit
class TestAiGatewayFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["AIGateway", "AIRequest", "AIResponse", "EnforcedInvokeMixin"],
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
        """``__all__`` содержит 4 символа."""
        assert len(gateway.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает S175 M2.1 ARC-009 facade subpackage."""
        assert gateway.__doc__ is not None
        assert "S175" in gateway.__doc__ or "ARC-009" in gateway.__doc__


@pytest.mark.unit
class TestAiGatewayFacadeIdentity:
    """Identity checks для canonical classes + mixin."""

    def test_aigateway_is_class(self) -> None:
        """``AIGateway`` — class (main AI gateway facade)."""
        assert isinstance(AIGateway, type)

    def test_ai_request_is_class(self) -> None:
        """``AIRequest`` — class (Pydantic / dataclass for AI requests)."""
        assert isinstance(AIRequest, type)

    def test_ai_response_is_class(self) -> None:
        """``AIResponse`` — class (Pydantic / dataclass for AI responses)."""
        assert isinstance(AIResponse, type)

    def test_enforced_invoke_mixin_is_class(self) -> None:
        """``EnforcedInvokeMixin`` — class (orchestrator mixin)."""
        assert isinstance(EnforcedInvokeMixin, type)

    def test_aigateway_resolves_from_subpackage(self) -> None:
        """``gateway.AIGateway`` — canonical AIGateway (subpackage wins over legacy module)."""
        from src.backend.core.ai.gateway.gateway import (
            AIGateway as SubpackageAIGateway,
        )

        assert AIGateway is SubpackageAIGateway

    def test_enforced_invoke_mixin_is_alias(self) -> None:
        """``EnforcedInvokeMixin`` aliased из ``gateway_orchestrator_mixin``."""
        from src.backend.core.ai.gateway_orchestrator_mixin import (
            EnforcedInvokeMixin as Canonical,
        )

        assert EnforcedInvokeMixin is Canonical
