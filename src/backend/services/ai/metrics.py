"""Re-export шим: реализация перенесена в ``core.ai.metrics``.

Инверсия зависимости (волна 33, LAYERS): ядро не должно зависеть от
``services``. Реализация переехала в core, публичный путь импорта
``src.backend.services.ai.metrics`` сохранён шимом.
"""

from __future__ import annotations

from src.backend.core.ai.metrics import AgentMetricsService as AgentMetricsService
from src.backend.core.ai.metrics import (
    get_agent_metrics_service as get_agent_metrics_service,
)

__all__ = ("AgentMetricsService", "get_agent_metrics_service")
