"""Re-export шим: реализация перенесена в ``core.ai.guardrails.lakera_client``.

Инверсия зависимости (волна 33, LAYERS): ядро не должно зависеть от
``services``. Реализация переехала в core, публичный путь импорта
``src.backend.services.ai.guardrails.lakera_client`` сохранён шимом.
"""

from __future__ import annotations

from src.backend.core.ai.guardrails.lakera_client import LakeraClient as LakeraClient
from src.backend.core.ai.guardrails.lakera_client import (
    LakeraGuardrailUnavailableError as LakeraGuardrailUnavailableError,
)
from src.backend.core.ai.guardrails.lakera_client import LakeraResult as LakeraResult

__all__ = ("LakeraClient", "LakeraGuardrailUnavailableError", "LakeraResult")
