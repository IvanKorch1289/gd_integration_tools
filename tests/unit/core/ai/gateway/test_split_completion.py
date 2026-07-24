"""S175 #8: тесты AIGateway split completion (move gateway.py → subpackage).

Проверяет:
- AIGateway теперь живёт в src.backend.core.ai.gateway.gateway
- _legacy_gateway.py удалён
- backward-compat re-export через subpackage __init__ работает
- EnforcedInvokeMixin / AIRequest / AIResponse re-export работают
"""

# ruff: noqa: S101

from __future__ import annotations

import importlib
import os



class TestAIGatewaySplit:
    """S175 #8: AIGateway moved from god-file to subpackage."""

    def test_aigateway_lives_in_subpackage(self) -> None:
        """AIGateway class now в ``src.backend.core.ai.gateway.gateway``."""
        from src.backend.core.ai.gateway import AIGateway

        assert AIGateway.__module__ == "src.backend.core.ai.gateway.gateway", (
            f"AIGateway should live in gateway.gateway, got {AIGateway.__module__}"
        )

    def test_aigateway_subpackage_init_exports(self) -> None:
        """``from src.backend.core.ai.gateway import AIGateway`` работает."""
        from src.backend.core.ai.gateway import (
            AIGateway,
            AIRequest,
            AIResponse,
            EnforcedInvokeMixin,
        )

        assert AIGateway.__name__ == "AIGateway"
        assert AIRequest.__name__ == "AIRequest"
        assert AIResponse.__name__ == "AIResponse"
        assert EnforcedInvokeMixin.__name__ == "EnforcedInvokeMixin"

    def test_aigateway_subpackage_all(self) -> None:
        """``__all__`` subpackage содержит все ожидаемые exports."""
        from src.backend.core.ai import gateway as gateway_pkg

        expected = {"EnforcedInvokeMixin", "AIGateway", "AIRequest", "AIResponse"}
        assert set(gateway_pkg.__all__) >= expected, (
            f"gateway.__all__ should include {expected}, got {set(gateway_pkg.__all__)}"
        )

    def test_legacy_file_removed(self) -> None:
        """``_legacy_gateway.py`` больше не существует (split завершён)."""
        legacy_path = "src/backend/core/ai/_legacy_gateway.py"
        assert not os.path.exists(legacy_path), (
            f"{legacy_path} should be deleted after S175 #8 split"
        )

    def test_aigateway_init_signature(self) -> None:
        """AIGateway.__init__ принимает стандартные параметры."""
        from src.backend.core.ai.gateway import AIGateway

        import inspect

        sig = inspect.signature(AIGateway.__init__)
        params = list(sig.parameters.keys())
        # Ожидаемые параметры: self + 8 keyword-only.
        assert "self" in params
        assert "policy_resolver" in params
        assert "capability_gate" in params
        assert "audit_service" in params
        assert "cost_tracker" in params
        assert "sanitizer" in params
        assert "llm_gateway" in params
        assert "policy_enforcer" in params
        assert "token_budget" in params

    def test_aigateway_methods_present(self) -> None:
        """AIGateway имеет ожидаемые public methods."""
        from src.backend.core.ai.gateway import AIGateway

        for method_name in (
            "get_policy",
            "invoke",
            "run_agent_code",
            "attach_sandbox",
        ):
            assert hasattr(AIGateway, method_name), (
                f"AIGateway should have {method_name}"
            )

    def test_aigateway_inherits_mixins(self) -> None:
        """AIGateway наследует EnforcedInvokeMixin + PipelineStepsMixin."""
        from src.backend.core.ai.gateway import AIGateway

        # Проверяем MRO содержит ожидаемые mixins.
        mro_names = {cls.__name__ for cls in AIGateway.__mro__}
        assert "EnforcedInvokeMixin" in mro_names, (
            f"AIGateway MRO should include EnforcedInvokeMixin, got {mro_names}"
        )
        assert "PipelineStepsMixin" in mro_names, (
            f"AIGateway MRO should include PipelineStepsMixin, got {mro_names}"
        )

    def test_orchestrator_module_loadable(self) -> None:
        """Orchestrator subpackage (enforced_invoke.py) загружается."""
        enforced_invoke_mod = importlib.import_module(
            "src.backend.core.ai.gateway.orchestrator.enforced_invoke"
        )
        # EnforcedInvokeMixin находится в этом модуле (re-exported).
        assert hasattr(enforced_invoke_mod, "EnforcedInvokeMixin")


class TestAIGatewayInstantiation:
    """S175 #8: AIGateway() — минимальный smoke test без DI."""

    def test_instantiate_without_args(self) -> None:
        """AIGateway() — все DI-args optional (backward-compat)."""
        from src.backend.core.ai.gateway import AIGateway

        gateway = AIGateway()
        assert gateway is not None
        # Все slots = None default.
        assert gateway._policy_resolver is None
        assert gateway._capability_gate is None
        assert gateway._audit_service is None
        assert gateway._cost_tracker is None
        assert gateway._sanitizer is None
        assert gateway._llm_gateway is None
        assert gateway._policy_enforcer is None
        assert gateway._token_budget is None

    def test_attach_sandbox(self) -> None:
        """``attach_sandbox()`` сохраняет в ``self._sandbox``."""
        from src.backend.core.ai.gateway import AIGateway

        gateway = AIGateway()
        sentinel = object()
        gateway.attach_sandbox(sentinel)
        assert gateway._sandbox is sentinel