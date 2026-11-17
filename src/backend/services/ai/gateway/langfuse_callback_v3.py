"""Re-export шим: реализация перенесена в ``core.ai.gateway.langfuse_callback_v3``.

Инверсия зависимости (волна 33, LAYERS): ядро не должно зависеть от
``services``. Реализация переехала в core, публичный путь импорта
``src.backend.services.ai.gateway.langfuse_callback_v3`` сохранён шимом.
"""

from __future__ import annotations

from src.backend.core.ai.gateway.langfuse_callback_v3 import (
    LangFuseCallbackV3 as LangFuseCallbackV3,
)
from src.backend.core.ai.gateway.langfuse_callback_v3 import (
    get_langfuse_callback as get_langfuse_callback,
)

__all__ = ("LangFuseCallbackV3", "get_langfuse_callback")
