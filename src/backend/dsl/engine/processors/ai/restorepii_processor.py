"""Auto-generated from ai_processors.py — single processor files."""
from __future__ import annotations

from typing import Any, Callable

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

class RestorePIIProcessor(BaseProcessor):
    """Восстанавливает замаскированные PII из exchange properties."""

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        mapping = exchange.properties.get("_pii_mapping")
        if not mapping:
            return
        body = exchange.in_message.body
        if not isinstance(body, str):
            body = str(body)
        for placeholder, original in mapping.items():
            body = body.replace(placeholder, original)
        exchange.in_message.set_body(body)
        exchange.properties.pop("_pii_mapping", None)
        exchange.properties.pop("_pii_original", None)
