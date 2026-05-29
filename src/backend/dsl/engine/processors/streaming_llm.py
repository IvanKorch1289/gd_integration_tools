"""TokenStreamLLMProcessor — token-level стриминг LLM (К4 MVP, Шаг 6).

Параллельный с :class:`dsl.engine.processors.ml_inference.StreamingLLMProcessor`
процессор поверх :class:`LiteLLMGateway` с native streaming. Поддерживает
output_mode = ``sse | ws | webhook``. На отмене (CancelledError) корректно
закрывает upstream-stream через ``stream.aclose()``.

Регистрация в реестре processors-плагинов выполняется в
``plugins/composition/setup_ai_2026.py`` через ``register_class`` API.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

logger = logging.getLogger(__name__)

__all__ = ("TokenStreamLLMProcessor",)


class TokenStreamLLMProcessor(BaseProcessor):
    """Стримит токены LLM в SSE / WS / Webhook publisher."""

    def __init__(
        self,
        *,
        prompt_property: str = "_composed_prompt",
        output_mode: str = "sse",
        publisher: Any | None = None,
        model: str | None = None,
        chunk_size: int = 1,
        gateway: Any | None = None,
        streaming_service: Any | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        if output_mode not in {"sse", "ws", "webhook"}:
            raise ValueError(
                f"output_mode должен быть sse|ws|webhook, получен {output_mode!r}"
            )
        self._prompt_property = prompt_property
        self._output_mode = output_mode
        self._publisher = publisher
        self._model = model
        self._chunk_size = chunk_size
        self._gateway = gateway
        self._streaming_service = streaming_service

    def _ensure_gateway(self) -> Any:
        if self._gateway is not None:
            return self._gateway
        from src.backend.services.ai.gateway.client import get_litellm_gateway

        self._gateway = get_litellm_gateway()
        return self._gateway

    def _ensure_streaming_service(self) -> Any:
        """Wave D.3: lazy-init LLMStreamingService via DI.

        If a gateway was injected into the processor, pass it through to the
        service so that tests can inject a mock and `LITELLM_ENABLED=false`
        does not cause a spurious GatewayUnavailable error.
        """
        if self._streaming_service is not None:
            return self._streaming_service
        from src.backend.services.ai.streaming_service import LLMStreamingService

        self._streaming_service = LLMStreamingService(gateway=self._gateway)
        return self._streaming_service

    def _ensure_publisher(self) -> Any:
        if self._publisher is not None:
            return self._publisher
        from src.backend.dsl.engine.processors.streaming_llm_publishers import (
            SSEPublisher,
            WebhookChunkedPublisher,
            WSPublisher,
        )

        match self._output_mode:
            case "sse":
                self._publisher = SSEPublisher()
            case "ws":
                self._publisher = WSPublisher()
            case "webhook":
                self._publisher = WebhookChunkedPublisher()
        return self._publisher

    @staticmethod
    def _normalize_chunk(chunk: Any) -> dict[str, Any]:
        """Унифицирует разные форматы чанков провайдеров к {delta, finish_reason}."""
        delta = ""
        finish_reason: str | None = None
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
        return {"delta": delta, "finish_reason": finish_reason}

    async def _iter_stream(self, prompt: str) -> AsyncIterator[Any]:
        """Legacy-итератор через прямой gateway (для обратной совместимости)."""
        gateway = self._ensure_gateway()
        result = await gateway.acompletion(
            messages=[{"role": "user", "content": prompt}],
            model=self._model,
            stream=True,
        )
        async for chunk in result:
            yield chunk

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        prompt = exchange.properties.get(self._prompt_property)
        if not isinstance(prompt, str) or not prompt:
            body = exchange.in_message.body
            prompt = body if isinstance(body, str) else str(body)

        publisher = self._ensure_publisher()
        service = self._ensure_streaming_service()
        accumulated: list[str] = []
        try:
            astream = service.astream(
                [{"role": "user", "content": prompt}], model=self._model
            )
            async for chunk in astream:
                norm = {"delta": chunk.delta, "finish_reason": chunk.finish_reason}
                if norm["delta"]:
                    accumulated.append(norm["delta"])
                    await publisher.publish_chunk(exchange=exchange, chunk=norm)
                if norm["finish_reason"]:
                    await publisher.publish_done(
                        exchange=exchange, finish_reason=norm["finish_reason"]
                    )
                    break
        except asyncio.CancelledError:
            aclose = getattr(astream, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("aclose() при отмене стрима: %s", exc)
            raise
        exchange.set_property("llm.streamed_text", "".join(accumulated))

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {
            "output_mode": self._output_mode,
            "prompt_property": self._prompt_property,
        }
        if self._model:
            spec["model"] = self._model
        if self._chunk_size != 1:
            spec["chunk_size"] = self._chunk_size
        return {"token_stream_llm": spec}
