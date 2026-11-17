"""Re-export шим: реализация перенесена в ``core.ai.gateway.langfuse_pii_callback``.

Инверсия зависимости (волна 33, LAYERS): ядро не должно зависеть от
``services``. Реализация переехала в core, публичный путь импорта
``src.backend.services.ai.gateway.langfuse_pii_callback`` сохранён шимом.
"""

from __future__ import annotations

from src.backend.core.ai.gateway.langfuse_pii_callback import (
    LangfusePIICallback as LangfusePIICallback,
)
from src.backend.core.ai.gateway.langfuse_pii_callback import (
    anonymize_trace_payload as anonymize_trace_payload,
)

__all__ = ("LangfusePIICallback", "anonymize_trace_payload")
