"""LLMStreamingService — token-level streaming поверх LiteLLMGateway (D.3).

Сервис нормализует чанки разных провайдеров и буферизует их по
``streaming_llm_settings.chunk_size``. Используется SSE/WS endpoint'ами
и DSL-процессором ``token_stream_llm``.

При ``CancelledError`` upstream-итератор корректно закрывается через
``aclose()``. При несовместимости провайдера со streaming (``BadRequestError``
от litellm) — fallback на non-stream вызов с выдачей одной chunk.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

__all__ = ("LLMStreamingService", "StreamChunk", "get_llm_streaming_service")


@dataclass(slots=True, frozen=True)
class StreamChunk:
    """Унифицированный чанк stream-ответа LLM."""

    delta: str
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


def _normalize_chunk(chunk: Any) -> StreamChunk:
    """Сводит формат провайдера к StreamChunk."""
    delta = ""
    finish_reason: str | None = None
    usage = None
    choices = getattr(chunk, "choices", None)
    if choices is None and isinstance(chunk, dict):
        choices = chunk.get("choices")
    if choices:
        first = choices[0]
        d = getattr(first, "delta", None)
        if d is None and isinstance(first, dict):
            d = first.get("delta")
        if d is not None:
            content = getattr(d, "content", None)
            if content is None and isinstance(d, dict):
                content = d.get("content")
            delta = str(content or "")
        fr = getattr(first, "finish_reason", None)
        if fr is None and isinstance(first, dict):
            fr = first.get("finish_reason")
        finish_reason = fr
    raw_usage = getattr(chunk, "usage", None)
    if raw_usage is None and isinstance(chunk, dict):
        raw_usage = chunk.get("usage")
    if isinstance(raw_usage, dict):
        usage = raw_usage
    elif raw_usage is not None:
        usage = {
            "prompt_tokens": getattr(raw_usage, "prompt_tokens", 0),
            "completion_tokens": getattr(raw_usage, "completion_tokens", 0),
            "total_tokens": getattr(raw_usage, "total_tokens", 0),
        }
    return StreamChunk(delta=delta, finish_reason=finish_reason, usage=usage)


class LLMStreamingService:
    """Высокоуровневый адаптер над LiteLLMGateway.astream_completion."""

    def __init__(
        self, gateway: Any | None = None, *, chunk_size: int | None = None
    ) -> None:
        self._gateway = gateway
        from src.backend.core.config.ai_stack import streaming_llm_settings

        self._chunk_size = (
            chunk_size if chunk_size is not None else streaming_llm_settings.chunk_size
        )

    def _ensure_gateway(self) -> Any:
        if self._gateway is not None:
            return self._gateway
        from src.backend.services.ai.gateway.client import get_litellm_gateway

        self._gateway = get_litellm_gateway()
        return self._gateway

    async def astream(
        self, messages: list[dict[str, Any]], *, model: str | None = None, **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        """Возвращает асинхронный поток ``StreamChunk``.

        Args:
            messages: chat-completion messages.
            model: переопределяет дефолтный.
            **kwargs: прозрачные параметры litellm.
        """
        gateway = self._ensure_gateway()
        try:
            stream = await gateway.acompletion(
                messages=messages, model=model, stream=True, **kwargs
            )
        except Exception as exc:
            if _is_bad_request(exc):
                logger.warning(
                    "Stream not supported, falling back to non-stream: %s", exc
                )
                async for chunk in self._fallback_nonstream(
                    messages, model=model, **kwargs
                ):
                    yield chunk
                return
            raise

        buffer: list[StreamChunk] = []
        try:
            async for raw in stream:
                norm = _normalize_chunk(raw)
                if not norm.delta and not norm.finish_reason:
                    continue
                buffer.append(norm)
                if len(buffer) >= self._chunk_size:
                    for piece in buffer:
                        yield piece
                    buffer.clear()
                if norm.finish_reason:
                    break
            for piece in buffer:
                yield piece
        except asyncio.CancelledError:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception as exc:
                    logger.debug("astream aclose failed: %s", exc)
            raise

    async def _fallback_nonstream(
        self, messages: list[dict[str, Any]], *, model: str | None, **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        gateway = self._ensure_gateway()
        kwargs.pop("stream", None)
        result = await gateway.acompletion(
            messages=messages, model=model, stream=False, **kwargs
        )
        content = _extract_full_text(result)
        usage = _extract_usage(result)
        yield StreamChunk(delta=content, finish_reason="stop", usage=usage)


def _is_bad_request(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    if "badrequest" in name:
        return True
    msg = str(exc).lower()
    return "stream" in msg and ("not support" in msg or "unsupported" in msg)


def _extract_full_text(response: Any) -> str:
    choices = getattr(response, "choices", None)
    if choices is None and isinstance(response, dict):
        choices = response.get("choices") or []
    if not choices:
        return ""
    first = choices[0]
    message = getattr(first, "message", None)
    if message is None and isinstance(first, dict):
        message = first.get("message")
    if message is None:
        return ""
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return str(content or "")


def _extract_usage(response: Any) -> dict[str, Any] | None:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if isinstance(usage, dict):
        return usage
    if usage is None:
        return None
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
        "total_tokens": getattr(usage, "total_tokens", 0),
    }


_singleton: LLMStreamingService | None = None


def get_llm_streaming_service() -> LLMStreamingService:
    """Возвращает singleton :class:`LLMStreamingService`."""
    global _singleton
    if _singleton is None:
        _singleton = LLMStreamingService()
    return _singleton
