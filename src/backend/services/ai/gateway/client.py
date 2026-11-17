"""Re-export шим: реализация перенесена в ``core.ai.gateway.client``.

Инверсия зависимости (волна 33, LAYERS): ядро не должно зависеть от
``services``. Реализация переехала в core, публичный путь импорта
``src.backend.services.ai.gateway.client`` сохранён шимом.
"""

from __future__ import annotations

from src.backend.core.ai.gateway.client import LiteLLMGateway as LiteLLMGateway
from src.backend.core.ai.gateway.client import (
    get_litellm_gateway as get_litellm_gateway,
)

__all__ = ("LiteLLMGateway", "get_litellm_gateway")
