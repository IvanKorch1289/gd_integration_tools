"""Tests for :func:`get_ai_agent_service` factory (cycle-5/D-AUDIT-501).

Regression на Phase-1 finding ``AGENTS-P0-001``: ранее функция
поднимала :class:`NotImplementedError`; cycle-5 заменил её на
composition-root DI lookup по pattern :func:`get_ai_gateway`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.services.ai.ai_agent import AIAgentService, get_ai_agent_service


class TestGetAiAgentServiceFactory:
    """Factory contract: возвращает :class:`AIAgentService` или падает fail-closed."""

    def test_returns_ai_agent_service_instance(self) -> None:
        """Bare fallback: без app.state возвращает AIAgentService instance."""
        with patch(
            "src.backend.core.di.app_state.get_app_ref", return_value=None
        ):
            agent = get_ai_agent_service()

        assert isinstance(agent, AIAgentService)

    def test_no_longer_raises_not_implemented_error(self) -> None:
        """Regression: AGENTS-P0-001 — функция больше не поднимает NotImplementedError."""
        with patch(
            "src.backend.core.di.app_state.get_app_ref", return_value=None
        ):
            try:
                get_ai_agent_service()
            except NotImplementedError:
                pytest.fail(
                    "get_ai_agent_service() must not raise NotImplementedError "
                    "(cycle-5/D-AUDIT-501)"
                )

    def test_prefers_app_state_singleton(self) -> None:
        """Если в ``app.state.ai_agent_service`` есть instance — он возвращается."""
        sentinel = MagicMock(spec=AIAgentService)
        sentinel_app = MagicMock()
        sentinel_app.state.ai_agent_service = sentinel

        with patch(
            "src.backend.core.di.app_state.get_app_ref",
            return_value=sentinel_app,
        ):
            agent = get_ai_agent_service()

        assert agent is sentinel

    def test_app_state_lookup_raises_falls_back_to_bare(self) -> None:
        """Если get_app_ref raises — fallback на bare AIAgentService (dev)."""
        with patch(
            "src.backend.core.di.app_state.get_app_ref",
            side_effect=RuntimeError("not in app context"),
        ):
            agent = get_ai_agent_service()

        assert isinstance(agent, AIAgentService)

    def test_ai_gateway_production_wiring_error_on_construction_failure(self) -> None:
        """При падении bare construction поднимается AIGatewayProductionWiringError."""
        from src.backend.core.ai.errors import AIGatewayProductionWiringError

        with (
            patch(
                "src.backend.core.di.app_state.get_app_ref", return_value=None
            ),
            patch(
                "src.backend.services.ai.ai_agent.AIAgentService",
                side_effect=RuntimeError("settings missing"),
            ),
        ):
            with pytest.raises(AIGatewayProductionWiringError) as exc_info:
                get_ai_agent_service()

        assert "ai_agent_service" in exc_info.value.missing

    def test_docstring_marker_cycle_5_d_audit_501(self) -> None:
        """Docstring содержит cycle-5/D-AUDIT-501 маркер (per AGENTS.md)."""
        assert "cycle-5/D-AUDIT-501" in (get_ai_agent_service.__doc__ or "")