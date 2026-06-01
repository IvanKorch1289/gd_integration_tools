"""Auto-generated from ai_processors.py — single processor files."""

from __future__ import annotations

from typing import Any, Callable

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class TokenBudgetProcessor(BaseProcessor):
    """Обрезает текст по token budget (tiktoken для точного подсчёта)."""

    def __init__(
        self,
        max_tokens: int = 4096,
        source_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self._max_tokens = max_tokens
        self._source_property = source_property
        self._encoder: Any = None

    def _get_encoder(self) -> Any:
        if self._encoder is None:
            try:
                import tiktoken

                self._encoder = tiktoken.encoding_for_model("gpt-4")
            except ImportError:
                return None
        return self._encoder

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self._source_property:
            text = exchange.properties.get(self._source_property, "")
        else:
            text = exchange.in_message.body
        if not isinstance(text, str):
            return

        encoder = self._get_encoder()
        if encoder is not None:
            tokens = encoder.encode(text)
            if len(tokens) > self._max_tokens:
                text = encoder.decode(tokens[: self._max_tokens]) + "\n...[truncated]"
        else:
            max_chars = self._max_tokens * 4
            if len(text) > max_chars:
                text = text[:max_chars] + "\n...[truncated]"

        if self._source_property:
            exchange.set_property(self._source_property, text)
        else:
            exchange.in_message.set_body(text)
