"""S58 W3 — toml.py part of format_converters decomp.

Classes: TomlEncodeProcessor, TomlDecodeProcessor.

TOML encode + decode + _toml_* helpers.
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

class TomlEncodeProcessor(BaseProcessor):
    """Сериализация dict → TOML-строка."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or "toml_encode")

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("toml_encode: body must be dict")
            return
        encoded = _toml_encode(body)
        exchange.set_out(body=encoded, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        return {"toml_encode": {}}

class TomlDecodeProcessor(BaseProcessor):
    """Десериализация TOML-строки/bytes → dict через stdlib ``tomllib``."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or "toml_decode")

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        import tomllib

        body = exchange.in_message.body
        if isinstance(body, str):
            payload = body.encode("utf-8")
        elif isinstance(body, (bytes, bytearray)):
            payload = bytes(body)
        else:
            exchange.fail("toml_decode: body must be str or bytes")
            return
        decoded = tomllib.loads(payload.decode("utf-8"))
        exchange.set_out(body=decoded, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        return {"toml_decode": {}}

def _toml_encode(data: dict[str, Any]) -> str:
    """Минимальный TOML-энкодер для top-level dict (без runtime-зависимостей).

    Поддерживает:
    * скалярные значения (str, bool, int, float, None→omit, datetime);
    * arrays of primitives и arrays of tables;
    * nested tables через [section.subsection];
    * inline-tables не используются (для простоты).
    """
    if not isinstance(data, dict):
        raise TypeError(f"TOML root must be a dict, got {type(data).__name__}")
    return _toml_encode_table(data, prefix="")

def _toml_encode_table(data: dict[str, Any], *, prefix: str) -> str:
    """Сериализует одну TOML-таблицу + рекурсивно вложенные."""
    primitive_lines: list[str] = []
    nested_tables: list[tuple[str, dict[str, Any]]] = []
    array_of_tables: list[tuple[str, list[dict[str, Any]]]] = []
    for key, value in data.items():
        safe_key = _toml_key(key)
        if isinstance(value, dict):
            nested_tables.append((safe_key, value))
        elif (
            isinstance(value, list)
            and value
            and all((isinstance(item, dict) for item in value))
        ):
            array_of_tables.append((safe_key, value))
        elif value is None:
            continue
        else:
            primitive_lines.append(f"{safe_key} = {_toml_value(value)}")
    chunks: list[str] = []
    if prefix:
        chunks.append(f"[{prefix}]")
    chunks.extend(primitive_lines)
    body = "\n".join(chunks)
    sections: list[str] = [body] if body else []
    for name, sub in nested_tables:
        sub_prefix = f"{prefix}.{name}" if prefix else name
        sections.append(_toml_encode_table(sub, prefix=sub_prefix))
    for name, items in array_of_tables:
        full_prefix = f"{prefix}.{name}" if prefix else name
        for item in items:
            sub_lines = [f"[[{full_prefix}]]"]
            for sub_key, sub_value in item.items():
                if isinstance(sub_value, dict):
                    raise ValueError(
                        f"TOML encoder: nested dict внутри array-of-tables '{name}' не поддерживается"
                    )
                if sub_value is None:
                    continue
                sub_lines.append(f"{_toml_key(sub_key)} = {_toml_value(sub_value)}")
            sections.append("\n".join(sub_lines))
    return "\n\n".join((s for s in sections if s))

def _toml_key(name: str) -> str:
    """Кавычит ключ TOML, если нужно."""
    if name.replace("_", "").replace("-", "").isalnum():
        return name
    return json.dumps(name)

def _toml_value(value: Any) -> str:
    """Сериализует TOML-скаляр или массив примитивов."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join((_toml_value(v) for v in value)) + "]"
    raise TypeError(f"TOML encoder: неподдерживаемый тип {type(value).__name__}")

