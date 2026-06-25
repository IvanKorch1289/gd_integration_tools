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
    """DSL-процессор ``prompt_get``.

    Возвращает скомпилированный template из PromptRegistry по имени.
    Поддерживает выбор версии (``version``) и label (default: ``"production"``).

    Args:
        name: Имя prompt в registry.
        to: Куда записать template string (default ``"body.prompt"``).
        version: Конкретная версия (default — production).
        processor_name: Имя процессора (default ``"prompt_get:<name>"``).

    Example:
        >>> p = PromptGetProcessor(name="osint_report", version="v2")
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
        # P0 fix (S170 review): get() is async — must await
        # get_version() does NOT exist — version is kwarg to get()
        version_obj = await registry.get(
            self.prompt_name,
            version=self.version,
            label="production",
        )
        # version_obj is PromptVersion dataclass — extract .compiled
        template = (
            getattr(version_obj, "compiled", None) or
            getattr(version_obj, "text", None) or
            str(version_obj)
        )
        self.set_result(exchange, self.target, template)
