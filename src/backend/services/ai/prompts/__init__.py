"""Пакет prompt-storage: адаптер для хранения и версионирования промптов.

Предоставляет LangfusePromptStorage — storage backend для prompt-registry,
который использует Langfuse SDK при включённом feature-flag и падает
обратно на in-memory хранилище при недоступности Langfuse.
"""

from src.backend.services.ai.prompts.langfuse_storage import (
    LangfusePromptStorage,
    PromptEntry,
    get_prompt_storage,
)

__all__ = (
    "LangfusePromptStorage",
    "PromptEntry",
    "get_prompt_storage",
)
