"""Adapter ``pydantic_ai.Model`` поверх :class:`LiteLLMGateway`.

PydanticAI 0.5+ ожидает реализацию ``pydantic_ai.models.Model``. Сигнатуры
ещё нестабильны (см. ``CHANGELOG``); мы реализуем минимально достаточный
shim. Если внутреннее API изменится — Sprint 4 переведёт на нативный
adapter ``pydantic_ai_litellm``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("LiteLLMModel",)


class LiteLLMModel:
    """Минимальный adapter: forward chat-completion к LiteLLM-шлюзу."""

    def __init__(
        self,
        *,
        gateway: Any,
        model_name: str | None = None,
    ) -> None:
        self._gateway = gateway
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name or "litellm-default"

    async def request(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        """PydanticAI-совместимый entry-point: делегирует в gateway.acompletion."""
        return await self._gateway.acompletion(
            messages=messages, model=self._model_name, stream=stream, **kwargs
        )
