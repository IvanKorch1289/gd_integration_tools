"""S58 W3 — protobuf.py part of format_converters decomp.

Classes: ProtobufEncodeProcessor, ProtobufDecodeProcessor.

Protobuf encode + decode + _resolve_protobuf_class helper.
"""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

_logger = get_logger("dsl.format_converters")


class ProtobufEncodeProcessor(BaseProcessor):
    """Сериализация dict → protobuf bytes через runtime-resolve message-класса.

    Args:
        message_class: Полный путь к protobuf-классу в формате
            ``"my.proto.module:OrderMessage"``.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, message_class: str, *, name: str | None = None) -> None:
        super().__init__(name=name or f"protobuf_encode:{message_class}")
        self._message_class = message_class

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        cls = _resolve_protobuf_class(self._message_class)
        body = exchange.in_message.body
        if isinstance(body, bytes):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return
        if not isinstance(body, dict):
            exchange.fail("protobuf_encode: body must be dict or bytes")
            return
        try:
            from google.protobuf.json_format import ParseDict

            msg = ParseDict(body, cls())
        except ImportError:
            msg = cls(**body)
        encoded = msg.SerializeToString()
        exchange.set_out(body=encoded, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        return {"protobuf_encode": {"message_class": self._message_class}}


class ProtobufDecodeProcessor(BaseProcessor):
    """Десериализация protobuf bytes → dict через runtime-resolve.

    Args:
        message_class: Полный путь к protobuf-классу.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, message_class: str, *, name: str | None = None) -> None:
        super().__init__(name=name or f"protobuf_decode:{message_class}")
        self._message_class = message_class

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        cls = _resolve_protobuf_class(self._message_class)
        body = exchange.in_message.body
        if not isinstance(body, (bytes, bytearray)):
            exchange.fail("protobuf_decode: body must be bytes")
            return
        msg = cls()
        msg.ParseFromString(bytes(body))
        try:
            from google.protobuf.json_format import MessageToDict

            decoded = MessageToDict(msg, preserving_proto_field_name=True)
        except ImportError:
            decoded = {f.name: getattr(msg, f.name) for f in msg.DESCRIPTOR.fields}
        exchange.set_out(body=decoded, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        return {"protobuf_decode": {"message_class": self._message_class}}


def _resolve_protobuf_class(message_class: str) -> Any:
    """Импортирует protobuf message-класс по строковому пути.

    Поддерживает форматы:
    * ``"package.module:ClassName"`` (рекомендуется);
    * ``"package.module.ClassName"`` (legacy fallback).
    """
    if ":" in message_class:
        module_name, class_name = message_class.split(":", 1)
    else:
        module_name, _, class_name = message_class.rpartition(".")
        if not module_name:
            raise ValueError(
                f"protobuf message_class must be 'module:Class' or 'module.Class', got: {message_class!r}"
            )
    module = importlib.import_module(module_name)
    return getattr(module, class_name)
