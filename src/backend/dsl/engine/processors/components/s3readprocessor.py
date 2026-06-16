"""S65 W1 — S3ReadProcessor extracted from components.py.

Per-processor file split.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_comp_logger = get_logger("dsl.components")


class S3ReadProcessor(BaseProcessor):
    """Camel S3 Component (read) — download object from S3."""

    def __init__(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        key_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"s3_read:{bucket}/{key or 'dynamic'}")
        self._bucket = bucket
        self._key = key
        self._key_property = key_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.infrastructure.clients.storage.s3_pool import storage_client

        key = self._key
        if self._key_property:
            key = exchange.properties.get(self._key_property, key)
        if not key:
            body = exchange.in_message.body
            key = body.get("key") if isinstance(body, dict) else None

        if not key:
            exchange.fail("No S3 key provided")
            return

        try:
            data = await storage_client.download_file(key)
            exchange.set_out(body=data, headers=dict(exchange.in_message.headers))
            exchange.in_message.set_header("CamelS3Key", key)
        except Exception as exc:
            exchange.fail(f"S3 read failed: {exc}")
