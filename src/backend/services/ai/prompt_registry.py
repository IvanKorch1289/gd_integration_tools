"""Re-export шим: реализация перенесена в ``core.ai.prompt_registry``.

Инверсия зависимости (волна 33, LAYERS): ядро не должно зависеть от
``services``. Реализация переехала в core, публичный путь импорта
``src.backend.services.ai.prompt_registry`` сохранён шимом.
"""

from __future__ import annotations

from src.backend.core.ai.prompt_registry import PromptRegistry as PromptRegistry
from src.backend.core.ai.prompt_registry import PromptVersion as PromptVersion
from src.backend.core.ai.prompt_registry import (
    get_prompt_registry as get_prompt_registry,
)

__all__ = ("PromptRegistry", "PromptVersion", "get_prompt_registry")
