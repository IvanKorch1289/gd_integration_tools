"""Re-export шим: реализация перенесена в ``core.ai.gateway.callbacks``.

Инверсия зависимости (волна 33, LAYERS): ядро не должно зависеть от
``services``. Реализация переехала в core, публичный путь импорта
``src.backend.services.ai.gateway.callbacks`` сохранён шимом.
"""

from __future__ import annotations

from src.backend.core.ai.gateway.callbacks import (
    CostTrackingCallback as CostTrackingCallback,
)
from src.backend.core.ai.gateway.callbacks import (
    FallbackTrackingCallback as FallbackTrackingCallback,
)

__all__ = ("CostTrackingCallback", "FallbackTrackingCallback")
