"""Format converters package (S58 W3 decomp from format_converters.py 555 LOC).

10 processor classes + 6 helpers decomposed в 5 files (per codec family):
- ``avro.py``: AvroEncodeProcessor, AvroDecodeProcessor
- ``protobuf.py``: ProtobufEncodeProcessor, ProtobufDecodeProcessor + _resolve_protobuf_class
- ``toml.py``: TomlEncodeProcessor, TomlDecodeProcessor + _toml_encode/_toml_encode_table/_toml_key/_toml_value
- ``markdown.py``: MarkdownToHtmlProcessor, HtmlToMarkdownProcessor + _simple_html_to_markdown
- ``jsonlines.py``: JsonLinesEncodeProcessor, JsonLinesDecodeProcessor

Backward-compat: ``from src.backend.dsl.codec.format_converters import AvroEncodeProcessor`` works.
"""

from __future__ import annotations

from src.backend.dsl.codec.format_converters.avro import (
    AvroDecodeProcessor,  # S58 W3: re-export
    AvroEncodeProcessor,  # S58 W3: re-export
)
from src.backend.dsl.codec.format_converters.jsonlines import (
    JsonLinesDecodeProcessor,  # S58 W3: re-export
    JsonLinesEncodeProcessor,  # S58 W3: re-export
)
from src.backend.dsl.codec.format_converters.markdown import (
    HtmlToMarkdownProcessor,  # S58 W3: re-export
    MarkdownToHtmlProcessor,  # S58 W3: re-export
    _simple_html_to_markdown,  # S58 W3: helper re-export
)
from src.backend.dsl.codec.format_converters.protobuf import (
    ProtobufDecodeProcessor,  # S58 W3: re-export
    ProtobufEncodeProcessor,  # S58 W3: re-export
    _resolve_protobuf_class,  # S58 W3: helper re-export
)
from src.backend.dsl.codec.format_converters.toml import (
    TomlDecodeProcessor,  # S58 W3: re-export
    TomlEncodeProcessor,  # S58 W3: re-export
    _toml_encode,  # S58 W3: helper re-export
    _toml_encode_table,  # S58 W3: helper re-export
    _toml_key,  # S58 W3: helper re-export
    _toml_value,  # S58 W3: helper re-export
)

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
    "_resolve_protobuf_class",
    "_toml_encode",
    "_toml_encode_table",
    "_toml_key",
    "_toml_value",
    "_simple_html_to_markdown",
)
