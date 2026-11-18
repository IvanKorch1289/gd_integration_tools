"""Re-export шим: реализация перенесена в ``core.ai.multi_agent``.

Инверсия зависимости (волна 33, LAYERS): ядро не должно зависеть от
``services``. Реализация переехала в core, публичный путь импорта
``src.backend.services.ai.multi_agent.supervisor`` сохранён шимом.
"""

from __future__ import annotations

from src.backend.core.ai.multi_agent import AgentSpec as AgentSpec
from src.backend.core.ai.multi_agent import MultiAgentSupervisor as MultiAgentSupervisor
from src.backend.core.ai.multi_agent import (
    MultiAgentSupervisorUnavailable as MultiAgentSupervisorUnavailable,
)
from src.backend.core.ai.multi_agent import (
    get_credit_pipeline_supervisor as get_credit_pipeline_supervisor,
)

__all__ = (
    "AgentSpec",
    "MultiAgentSupervisor",
    "MultiAgentSupervisorUnavailable",
    "get_credit_pipeline_supervisor",
)
