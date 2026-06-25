"""DSL processor ``prompt_get`` (Sprint 170 S170 — agent layer).

Thin wrapper над :func:`src.backend.services.ai.prompt_registry.get_prompt_registry`.
Ponytail: возвращает template text по имени.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("PromptGetProcessor",)
_logger = get_logger(__name__)


class PromptGetProcessor(BaseProcessor):
    """Получает prompt template через PromptRegistry.

    Args:
        name: Имя prompt в registry.
        to: Куда записать template string.
    """

    def __init__(
        self,
        *,
        name: str,
        to: str = "body.prompt",
        version: str | None = None,
        processor_name: str | None = None,
    ) -> None:
        super().__init__(name=processor_name or f"prompt_get:{name}")
        self.prompt_name = name
        self.target = to
        self.version = version

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.services.ai.prompt_registry import get_prompt_registry
        registry = get_prompt_registry()
        # Ponytail: 1-2 LOC over registry interface
        if self.version is not None:
            template = registry.get_version(self.prompt_name, self.version)
        else:
            template = registry.get(self.prompt_name)
        self.set_result(exchange, self.target, template)
