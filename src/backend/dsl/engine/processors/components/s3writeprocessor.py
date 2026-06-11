from __future__ import annotations

"""S65 W1 — S3WriteProcessor extracted from components.py.

Per-processor file split.
"""

from typing import Any

import orjson

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_comp_logger = get_logger("dsl.components")


class S3WriteProcessor(BaseProcessor):
    """Camel S3 Component (write) — upload exchange body to S3."""

    def __init__(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        key_property: str | None = None,
        content_type: str = "application/octet-stream",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"s3_write:{bucket}/{key or 'dynamic'}")
        self._bucket = bucket
        self._key = key
        self._key_property = key_property
        self._content_type = content_type

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.infrastructure.clients.storage.s3_pool import storage_client

        key = self._key
        if self._key_property:
            key = exchange.properties.get(self._key_property, key)

        if not key:
            exchange.fail("No S3 key provided for write")
            return

        body = exchange.in_message.body
        if isinstance(body, str):
            data = body.encode("utf-8")
        elif isinstance(body, bytes):
            data = body
        else:
            data = orjson.dumps(body, default=str)

        try:
            await storage_client.upload_file(data, key, content_type=self._content_type)
            exchange.set_property("s3_written", key)
            exchange.in_message.set_header("CamelS3Key", key)
        except Exception as exc:
            exchange.fail(f"S3 write failed: {exc}")
