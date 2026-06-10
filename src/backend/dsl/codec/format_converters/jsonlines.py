"""S58 W3 — jsonlines.py part of format_converters decomp.

Classes: JsonLinesEncodeProcessor, JsonLinesDecodeProcessor.

JSON Lines encode + decode.
"""
from __future__ import annotations

import datetime as _dt
import importlib
import io
import json
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

_logger = get_logger("dsl.format_converters")

class JsonLinesEncodeProcessor(BaseProcessor):
    """list[dict] → NDJSON-строка (одна запись на строку)."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or "jsonl_encode")

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        body = exchange.in_message.body
        if isinstance(body, dict):
            records: list[Any] = [body]
        elif isinstance(body, list):
            records = body
        else:
            exchange.fail("jsonl_encode: body must be list or dict")
            return
        buf = io.StringIO()
        for record in records:
            buf.write(json.dumps(record, ensure_ascii=False, default=str))
            buf.write("\n")
        exchange.set_out(body=buf.getvalue(), headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        return {"jsonl_encode": {}}

class JsonLinesDecodeProcessor(BaseProcessor):
    """NDJSON-строка → list[dict] (построчное чтение через ``json``)."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self, *, ignore_blank_lines: bool = True, name: str | None = None
    ) -> None:
        super().__init__(name=name or "jsonl_decode")
        self._ignore_blank = ignore_blank_lines

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        body = exchange.in_message.body
        if isinstance(body, (bytes, bytearray)):
            payload = bytes(body).decode("utf-8")
        elif isinstance(body, str):
            payload = body
        else:
            exchange.fail("jsonl_decode: body must be str or bytes")
            return
        records: list[Any] = []
        for line in io.StringIO(payload):
            stripped = line.strip()
            if not stripped:
                if self._ignore_blank:
                    continue
                raise ValueError("jsonl_decode: пустая строка не разрешена")
            records.append(json.loads(stripped))
        exchange.set_out(body=records, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {}
        if self._ignore_blank is not True:
            spec["ignore_blank_lines"] = self._ignore_blank
        return {"jsonl_decode": spec}

