"""S58 W3 — avro.py part of format_converters decomp.

Classes: AvroEncodeProcessor, AvroDecodeProcessor.

Avro encode + decode.
"""

from __future__ import annotations

import io
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

_logger = get_logger("dsl.format_converters")


class AvroEncodeProcessor(BaseProcessor):
    """Сериализация dict/list-of-dict → Avro bytes через ``fastavro``.

    Args:
        schema: Avro-схема в виде dict (parsed JSON Schema). Схема
            будет передана в ``fastavro.parse_schema``.
        name: Опциональное имя процессора.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, schema: dict[str, Any], *, name: str | None = None) -> None:
        super().__init__(name=name or "avro_encode")
        self._schema = schema

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        import fastavro

        parsed = fastavro.parse_schema(self._schema)
        body = exchange.in_message.body
        records: list[Any] = body if isinstance(body, list) else [body]
        buf = io.BytesIO()
        fastavro.writer(buf, parsed, records)
        exchange.set_out(body=buf.getvalue(), headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        return {"avro_encode": {"schema": self._schema}}


class AvroDecodeProcessor(BaseProcessor):
    """Десериализация Avro bytes → list[dict] через ``fastavro``.

    Args:
        schema: Avro-схема для reader (writer-схема считывается из
            самого container-файла).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self, schema: dict[str, Any] | None = None, *, name: str | None = None
    ) -> None:
        super().__init__(name=name or "avro_decode")
        self._schema = schema

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        import fastavro

        body = exchange.in_message.body
        if not isinstance(body, (bytes, bytearray)):
            exchange.fail("avro_decode: body must be bytes")
            return
        buf = io.BytesIO(bytes(body))
        reader = (
            fastavro.reader(buf, reader_schema=self._schema)
            if self._schema is not None
            else fastavro.reader(buf)
        )
        records = list(reader)
        exchange.set_out(body=records, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {}
        if self._schema is not None:
            spec["schema"] = self._schema
        return {"avro_decode": spec}
