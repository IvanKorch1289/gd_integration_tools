"""Auto-generated from ai_processors.py — single processor files."""
from __future__ import annotations

from typing import Any, Callable

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

class LLMParserProcessor(BaseProcessor):
    """Парсит ответ LLM в структурированный формат."""

    def __init__(
        self, schema: type | None = None, format: str = "json", name: str | None = None
    ) -> None:
        super().__init__(name)
        self._schema = schema
        self._format = format

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, str):
            return
        text = body.strip()
        if self._format == "json":
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]
            try:
                parsed = orjson.loads(text)
            except (orjson.JSONDecodeError, ValueError):
                exchange.fail(f"LLM output is not valid JSON: {text[:100]}")
                return
        else:
            parsed = text
        if self._schema is not None:
            try:
                from pydantic import BaseModel

                if issubclass(self._schema, BaseModel):
                    parsed = self._schema.model_validate(parsed)
            except (ValueError, TypeError) as exc:
                exchange.fail(f"LLM output schema validation failed: {exc}")
                return
        exchange.in_message.set_body(parsed)
