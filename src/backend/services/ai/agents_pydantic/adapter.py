"""Adapter ``pydantic_ai.Model`` поверх :class:`LiteLLMGateway`.

PydanticAI 0.5+ ожидает реализацию ``pydantic_ai.models.Model``. Сигнатуры
ещё нестабильны (см. ``CHANGELOG``); мы реализуем минимально достаточный
shim. Если внутреннее API изменится — Sprint 4 переведёт на нативный
adapter ``pydantic_ai_litellm``.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from collections.abc import AsyncIterator
from typing import Any

logger = get_logger(__name__)

__all__ = ("LiteLLMModel",)

from contextlib import asynccontextmanager  # noqa: E402

try:
    from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
    from pydantic_ai.models import Model, ModelRequestParameters
    from pydantic_ai.result import StreamedResponse
    from pydantic_ai.settings import ModelSettings

    HAS_PYDANTIC_AI = True
except ImportError:
    HAS_PYDANTIC_AI = False
    Model = object
    ModelMessage = Any
    ModelResponse = Any
    TextPart = None
    ModelSettings = Any
    ModelRequestParameters = Any
    StreamedResponse = Any


class LiteLLMModel(Model if HAS_PYDANTIC_AI else object):  # type: ignore[misc]
    """Минимальный adapter: forward chat-completion к LiteLLM-шлюзу.

    Реализует ``pydantic_ai.models.Model`` ABC (pydantic-ai 0.5.x)
    чтобы ``isinstance(model, Model)`` возвращал True и pydantic-ai
    не пытался парсить model name как строку.
    """

    def __init__(self, *, gateway: Any, model_name: str | None = None) -> None:
        if HAS_PYDANTIC_AI:
            super().__init__()
        self._gateway = gateway
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        """The model name used for LiteLLM."""
        return self._model_name or "litellm-default"

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Delegate to gateway.acompletion."""
        # Convert ModelMessage → dict for gateway
        dict_messages: list[dict[str, Any]] = []
        for msg in messages:
            if hasattr(msg, "parts"):
                role = getattr(msg, "role", "user")
                text = ""
                for part in getattr(msg, "parts", []):
                    if hasattr(part, "content"):
                        text += str(getattr(part, "content", ""))
                dict_messages.append({"role": str(role), "content": text})
            elif hasattr(msg, "content"):
                dict_messages.append({"role": "user", "content": str(msg.content)})

        result = await self._gateway.acompletion(
            messages=dict_messages, model=self._model_name, stream=False
        )
        # Extract text from LiteLLM response
        content = ""
        if hasattr(result, "choices") and result.choices:
            msg_obj = result.choices[0].message
            content = str(getattr(msg_obj, "content", "") or "")
        # pydantic-ai ModelResponse uses parts (TextPart), not content kwarg
        if TextPart is not None:
            return ModelResponse(parts=[TextPart(content=content)])
        # Fallback when pydantic_ai not installed (shouldn't reach here in practice)
        return result

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> AsyncIterator[StreamedResponse]:
        """Streaming not supported yet."""
        raise NotImplementedError(
            f"Streaming not yet supported by {self.__class__.__name__}"
        )
