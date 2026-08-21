"""pydantic_ai LiteLLMModelAdapter — extracted (RE_AUDIT_2026-08-26 god-object 2/5).

S168 W16 P1-5: full pydantic_ai.models.Model Protocol implementation.
Wraps existing LiteLLMGateway. Default-OFF — instantiates only when
pydantic_ai is installed AND user explicitly creates the adapter.

Extracted from pydantic_ai_client.py (667→413 LOC split). The main
PydanticAIClient (LLM gateway) stays in pydantic_ai_client.py.
This module is the Model Protocol adapter for pydantic_ai Agent
integration — separate concern, separate file, single responsibility.

Optional dep: pydantic_ai must be installed (ai-2026 extra in
pyproject.toml). Falls back gracefully if not.
"""

from __future__ import annotations

# Lazy import: pydantic_ai optional (ai-2026 extra in pyproject.toml).
# Falls back gracefully если pydantic_ai не установлен.
try:
    from pydantic_ai.models import Model as _PydanticAIModel

    _PYDANTIC_AI_AVAILABLE = True
except ImportError:  # pragma: no cover — optional dep
    _PydanticAIModel = None  # type: ignore[assignment,misc]
    _PYDANTIC_AI_AVAILABLE = False

__all__ = ("LiteLLMModelAdapter", "_SimpleStreamedResponse")

# ── LiteLLMModelAdapter (S168 W16 P1-5) ────────────────────────────────────
#
# S168 W16 P1-5: full pydantic_ai.models.Model Protocol implementation.
# Wraps existing LiteLLMGateway. Default-OFF — instantiates only when
# pydantic_ai is installed И user explicitly creates the adapter.
# ────────────────────────────────────────────────────────────────────────────

if _PYDANTIC_AI_AVAILABLE and _PydanticAIModel is not None:
    from collections.abc import AsyncGenerator
    from typing import Any as _Any

    from pydantic_ai.messages import ModelMessage as _ModelMessage
    from pydantic_ai.messages import ModelRequest as _ModelRequest
    from pydantic_ai.messages import ModelResponse as _ModelResponse
    from pydantic_ai.messages import ModelResponsePart as _ModelResponsePart
    from pydantic_ai.messages import TextPart as _TextPart
    from pydantic_ai.models import ModelRequestContext as _ModelRequestContext
    from pydantic_ai.models import ModelRequestParameters as _ModelRequestParameters
    from pydantic_ai.models import ModelSettings as _ModelSettings
    from pydantic_ai.models import StreamedResponse as _StreamedResponse
    from pydantic_ai.usage import RequestUsage as _RequestUsage
    from pydantic_ai.usage import Usage as _Usage

    try:
        from pydantic_ai.tools import (
            AbstractNativeTool as _AbstractNativeTool,  # type: ignore[attr-defined]
        )
    except ImportError:  # pragma: no cover — version-specific
        _AbstractNativeTool = object  # type: ignore[assignment,misc]

    class LiteLLMModelAdapter(_PydanticAIModel):  # type: ignore[misc]
        """S168 W16 P1-5: pydantic_ai Model adapter поверх LiteLLMGateway.

        Реализует полный pydantic_ai.models.Model Protocol
        (per master prompt v8 P1-5: request, request_stream,
        prepare_request, supported_builtin_tools, supported_native_tools).

        Args:
            gateway: :class:`LiteLLMGateway` для выполнения HTTP.
            model_name: primary model name (e.g. "gpt-4o", "claude-3-5-sonnet").
            provider: provider label (e.g. "openai", "anthropic", "litellm").

        """

        def __init__(
            self, *, gateway: _Any, model_name: str, provider: str = "litellm"
        ) -> None:
            self._gateway = gateway
            self._model_name = model_name
            self._provider = provider

        @property
        def model_name(self) -> str:
            """Имя модели в формате 'provider:model_name' (e.g. 'openai:gpt-4o')."""
            return self._model_name

        @property
        def system(self) -> str:
            """System prompt (none — handled by caller)."""
            return ""

        async def request(  # type: ignore[override]
            self,
            messages: list[_ModelMessage],
            model_settings: _ModelSettings,
            model_request_parameters: _ModelRequestParameters,
        ) -> _ModelResponse:
            """Single request через LiteLLMGateway."""
            from src.backend.core.ai.gateway.client import LiteLLMGateway

            assert isinstance(self._gateway, LiteLLMGateway)
            prompt = "\n".join(
                str(getattr(m, "content", m)) for m in messages if isinstance(m, _ModelRequest)
            )
            response = await self._gateway.acompletion(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=False,
            )
            text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return _ModelResponse(parts=[_TextPart(text)])  # type: ignore[misc]

        async def request_stream(  # type: ignore[override]
            self,
            messages: list[_ModelMessage],
            model_settings: _ModelSettings,
            model_request_parameters: _ModelRequestParameters,
            *,
            context: _ModelRequestContext | None = None,
        ) -> _StreamedResponse:
            """Streamed request — returns _SimpleStreamedResponse."""
            from src.backend.core.ai.gateway.client import LiteLLMGateway

            assert isinstance(self._gateway, LiteLLMGateway)
            prompt = "\n".join(
                str(getattr(m, "content", m)) for m in messages if isinstance(m, _ModelRequest)
            )
            response = await self._gateway.acompletion(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            text = ""
            async for chunk in response:
                text += chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
            return _SimpleStreamedResponse(text)  # type: ignore[return-value]

        def prepare_request(  # type: ignore[override]
            self,
            model_settings: _ModelSettings,
            model_request_parameters: _ModelRequestParameters,
            *,
            context: _ModelRequestContext | None = None,
        ) -> tuple[_ModelSettings, _ModelRequestParameters]:
            """Hook для модификации settings перед request. Default: pass-through."""
            return model_settings, model_request_parameters

        @property
        def supported_builtin_tools(self) -> list[_AbstractNativeTool]:  # type: ignore[override]
            """Встроенные tools (none — handled by agent loop)."""
            return []

        @property
        def supported_native_tools(self) -> list[_AbstractNativeTool]:  # type: ignore[override]
            """Native tools (none — handled by agent loop)."""
            return []

        @property
        def provider(self) -> str:
            """Имя провайдера ('openai', 'anthropic', 'ollama', etc.)."""
            return self._provider

    class _SimpleStreamedResponse(_StreamedResponse):  # type: ignore[misc]
        """Minimal StreamedResponse для не-streaming LiteLLM adapters."""

        def __init__(self, text: str) -> None:
            self._text = text

        async def _get_event_iterator(self) -> AsyncGenerator[_ModelResponsePart]:
            yield _TextPart(self._text)  # type: ignore[misc]

        @property
        def model_name(self) -> str:
            """Имя модели в формате 'provider:model_name' (e.g. 'openai:gpt-4o')."""
            return ""

        @property
        def provider(self) -> str:
            """Имя провайдера ('openai', 'anthropic', 'ollama', etc.)."""
            return "litellm"

        @property
        def usage(self) -> _RequestUsage:
            return _RequestUsage(input_tokens=0, output_tokens=len(self._text) // 4)
