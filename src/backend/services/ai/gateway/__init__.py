"""LiteLLM Gateway — единый шлюз LLM-провайдеров (К4 MVP, Шаг 1).

Назначение — параллельный с :mod:`services.ai.ai_providers` каркас
unified-клиента поверх ``litellm`` с native streaming, cost-callback и
fallback-цепочкой. Sprint 1+ доводит до production: на этом этапе
живой shim, default-OFF.
"""

from src.backend.services.ai.gateway.client import LiteLLMGateway, get_litellm_gateway
from src.backend.services.ai.gateway.exceptions import (
    GatewayError,
    GatewayRateLimited,
    GatewayUnavailable,
)

__all__ = (
    "GatewayError",
    "GatewayRateLimited",
    "GatewayUnavailable",
    "LiteLLMGateway",
    "get_litellm_gateway",
)
