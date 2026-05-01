"""Wave 6.1 — DSL-процессоры конвертации формата (Avro / Protobuf / TOML / Markdown / JSON Lines).

Каждый процессор реализует ``BaseProcessor`` и выполняет преобразование
``in_message.body`` → ``out_message.body``. Все процессоры async-only,
поддерживают round-trip через ``to_spec()`` и регистрируются в
``RouteBuilder`` как fluent-методы.

Конвертеры:

* ``AvroEncodeProcessor`` / ``AvroDecodeProcessor`` — fastavro;
* ``ProtobufEncodeProcessor`` / ``ProtobufDecodeProcessor`` — runtime-resolve
  message-класса по полному пути ``module:ClassName``;
* ``TomlEncodeProcessor`` / ``TomlDecodeProcessor`` — encode через
  минимальный встроенный сериализатор (без runtime-зависимостей),
  decode через stdlib ``tomllib``;
* ``MarkdownToHtmlProcessor`` / ``HtmlToMarkdownProcessor`` — markdown-it-py
  (transitive dep через rich); HTML→Markdown через простую эвристику +
  опц. ``html-to-markdown`` если установлен;
* ``JsonLinesEncodeProcessor`` / ``JsonLinesDecodeProcessor`` — построчное
  чтение/запись NDJSON через stdlib ``json``.
"""

from __future__ import annotations

import datetime as _dt
import importlib
import io
import json
import logging
from typing import Any, ClassVar

from src.core.types.side_effect import SideEffectKind
from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = (
    "AvroEncodeProcessor",
    "AvroDecodeProcessor",
    "ProtobufEncodeProcessor",
    "ProtobufDecodeProcessor",
    "TomlEncodeProcessor",
    "TomlDecodeProcessor",
    "MarkdownToHtmlProcessor",
    "HtmlToMarkdownProcessor",
    "JsonLinesEncodeProcessor",
    "JsonLinesDecodeProcessor",
)

_logger = logging.getLogger("dsl.format_converters")


# ──────────────────── Avro ────────────────────


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
        import fastavro

        parsed = fastavro.parse_schema(self._schema)
        body = exchange.in_message.body
        records: list[Any] = body if isinstance(body, list) else [body]

        buf = io.BytesIO()
        fastavro.writer(buf, parsed, records)
        exchange.set_out(
            body=buf.getvalue(),
            headers=dict(exchange.in_message.headers),
        )

    def to_spec(self) -> dict[str, Any] | None:
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
        exchange.set_out(
            body=records, headers=dict(exchange.in_message.headers)
        )

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._schema is not None:
            spec["schema"] = self._schema
        return {"avro_decode": spec}


# ──────────────────── Protobuf ────────────────────


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
                f"protobuf message_class must be 'module:Class' or "
                f"'module.Class', got: {message_class!r}"
            )

    module = importlib.import_module(module_name)
    return getattr(module, class_name)


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
        cls = _resolve_protobuf_class(self._message_class)
        body = exchange.in_message.body
        if isinstance(body, bytes):
            exchange.set_out(body=body, headers=dict(exchange.in_message.headers))
            return
        if not isinstance(body, dict):
            exchange.fail("protobuf_encode: body must be dict or bytes")
            return

        # Пытаемся ParseDict (google.protobuf.json_format) — самый универсальный путь.
        try:
            from google.protobuf.json_format import ParseDict

            msg = ParseDict(body, cls())
        except ImportError:
            msg = cls(**body)

        encoded = msg.SerializeToString()
        exchange.set_out(body=encoded, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
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
        return {"protobuf_decode": {"message_class": self._message_class}}


# ──────────────────── TOML ────────────────────


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
            and all(isinstance(item, dict) for item in value)
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
                        f"TOML encoder: nested dict внутри array-of-tables "
                        f"'{name}' не поддерживается"
                    )
                if sub_value is None:
                    continue
                sub_lines.append(
                    f"{_toml_key(sub_key)} = {_toml_value(sub_value)}"
                )
            sections.append("\n".join(sub_lines))

    return "\n\n".join(s for s in sections if s)


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
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"TOML encoder: неподдерживаемый тип {type(value).__name__}")


class TomlEncodeProcessor(BaseProcessor):
    """Сериализация dict → TOML-строка."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or "toml_encode")

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("toml_encode: body must be dict")
            return
        encoded = _toml_encode(body)
        exchange.set_out(body=encoded, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        return {"toml_encode": {}}


class TomlDecodeProcessor(BaseProcessor):
    """Десериализация TOML-строки/bytes → dict через stdlib ``tomllib``."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or "toml_decode")

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
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
        return {"toml_decode": {}}


# ──────────────────── Markdown ↔ HTML ────────────────────


class MarkdownToHtmlProcessor(BaseProcessor):
    """Markdown → HTML через ``markdown-it-py`` (transitive dep, есть в стеке)."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, *, preset: str = "commonmark", name: str | None = None) -> None:
        super().__init__(name=name or "markdown_to_html")
        self._preset = preset

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from markdown_it import MarkdownIt

        body = exchange.in_message.body
        if not isinstance(body, str):
            exchange.fail("markdown_to_html: body must be str")
            return

        md = MarkdownIt(self._preset)
        html = md.render(body)
        exchange.set_out(body=html, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._preset != "commonmark":
            spec["preset"] = self._preset
        return {"markdown_to_html": spec}


class HtmlToMarkdownProcessor(BaseProcessor):
    """HTML → Markdown.

    Если установлен пакет ``markdownify`` — используется он.
    Иначе используется простая эвристика на базе ``html.parser`` для
    основных тегов (h1-h6 / p / a / strong / em / ul / ol / code / pre).
    Для banking-кейсов markdown-вывод обычно достаточен; продакшн
    рекомендуется ставить ``markdownify`` через extras.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or "html_to_markdown")

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, str):
            exchange.fail("html_to_markdown: body must be str")
            return

        md = self._convert(body)
        exchange.set_out(body=md, headers=dict(exchange.in_message.headers))

    @staticmethod
    def _convert(html: str) -> str:
        """Опциональный путь через ``markdownify`` или fallback на эвристику."""
        try:
            import markdownify as _mdfy  # type: ignore[import-not-found]
        except ImportError:
            return _simple_html_to_markdown(html)
        return str(_mdfy.markdownify(html, heading_style="ATX"))

    def to_spec(self) -> dict[str, Any] | None:
        return {"html_to_markdown": {}}


def _simple_html_to_markdown(html: str) -> str:
    """Минимальная эвристика HTML → Markdown без сторонних зависимостей."""
    from html.parser import HTMLParser

    class _MdParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self._stack: list[str] = []
            self._href: str | None = None

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self._stack.append(tag)
            mapping = {
                "h1": "\n# ", "h2": "\n## ", "h3": "\n### ",
                "h4": "\n#### ", "h5": "\n##### ", "h6": "\n###### ",
                "p": "\n", "br": "\n",
                "strong": "**", "b": "**",
                "em": "*", "i": "*",
                "code": "`",
                "li": "\n- ",
                "pre": "\n```\n",
            }
            if tag in mapping:
                self.parts.append(mapping[tag])
            elif tag == "a":
                for k, v in attrs:
                    if k == "href":
                        self._href = v
                self.parts.append("[")

        def handle_endtag(self, tag: str) -> None:
            if self._stack and self._stack[-1] == tag:
                self._stack.pop()
            mapping_close = {
                "strong": "**", "b": "**",
                "em": "*", "i": "*",
                "code": "`",
                "pre": "\n```\n",
                "p": "\n",
            }
            if tag in mapping_close:
                self.parts.append(mapping_close[tag])
            elif tag == "a":
                href = self._href or ""
                self.parts.append(f"]({href})")
                self._href = None

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    parser = _MdParser()
    parser.feed(html)
    return "".join(parser.parts).strip()


# ──────────────────── JSON Lines (NDJSON) ────────────────────


class JsonLinesEncodeProcessor(BaseProcessor):
    """list[dict] → NDJSON-строка (одна запись на строку)."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name=name or "jsonl_encode")

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
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
        exchange.set_out(
            body=buf.getvalue(), headers=dict(exchange.in_message.headers)
        )

    def to_spec(self) -> dict[str, Any] | None:
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
        spec: dict[str, Any] = {}
        if self._ignore_blank is not True:
            spec["ignore_blank_lines"] = self._ignore_blank
        return {"jsonl_decode": spec}
