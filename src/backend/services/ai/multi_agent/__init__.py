"""Multi-agent supervisor (K4 Sprint 7).

Назначение:
    LangGraph-based supervisor pattern для координации нескольких
    специализированных агентов через handoff_to(agent_name) tool.

Использование::

    from src.backend.services.ai.multi_agent import (
        MultiAgentSupervisor,
        AgentSpec,
        get_credit_pipeline_supervisor,
    )

    supervisor = MultiAgentSupervisor(
        name="credit_orchestrator",
        agents=[
            AgentSpec(name="scoring_agent", description="Считает credit score"),
            AgentSpec(name="document_parser_agent", description="Парсит документы"),
            AgentSpec(name="decision_agent", description="Финальное решение"),
        ],
    )
    result = await supervisor.run(prompt="Оцени заявку клиента")

Активация:
    ``feature_flags.multi_agent_supervisor_enabled`` (default-OFF).
"""

from __future__ import annotations

from src.backend.services.ai.multi_agent.supervisor import (
    AgentSpec,
    MultiAgentSupervisor,
    MultiAgentSupervisorUnavailable,
    get_credit_pipeline_supervisor,
)

__all__ = (
    "AgentSpec",
    "MultiAgentSupervisor",
    "MultiAgentSupervisorUnavailable",
    "get_credit_pipeline_supervisor",
)
