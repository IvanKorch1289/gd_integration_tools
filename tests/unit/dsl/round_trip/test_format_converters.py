"""Wave 6.1 — Round-trip тесты для format-конвертеров.

Покрывает builder → to_spec → load_pipeline_from_yaml для:
* avro_encode / avro_decode;
* protobuf_encode / protobuf_decode;
* toml_encode / toml_decode;
* markdown_to_html / html_to_markdown;
* jsonl_encode / jsonl_decode.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest
import yaml

from src.dsl.builder import RouteBuilder
from src.dsl.yaml_loader import load_pipeline_from_yaml


def _round_trip(builder: RouteBuilder) -> tuple[dict, dict]:
    pipeline = builder.build()
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    return dump, rebuilt.to_dict()


_AVRO_SCHEMA: dict = {
    "type": "record",
    "name": "Order",
    "fields": [
        {"name": "id", "type": "long"},
        {"name": "amount", "type": "double"},
    ],
}


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("avro_encode", {"schema": _AVRO_SCHEMA}),
        ("avro_decode", {}),
        ("avro_decode", {"schema": _AVRO_SCHEMA}),
        ("protobuf_encode", {"message_class": "my.proto:OrderMessage"}),
        ("protobuf_decode", {"message_class": "my.proto:OrderMessage"}),
        ("toml_encode", {}),
        ("toml_decode", {}),
        ("markdown_to_html", {}),
        ("markdown_to_html", {"preset": "default"}),
        ("html_to_markdown", {}),
        ("jsonl_encode", {}),
        ("jsonl_decode", {}),
        ("jsonl_decode", {"ignore_blank_lines": False}),
    ],
)
def test_format_converter_round_trip(method: str, kwargs: dict) -> None:
    """Round-trip: builder → YAML → load_pipeline_from_yaml → identical dict."""
    builder = RouteBuilder.from_(f"rt.fc.{method}", source="test:rt.fc")
    getattr(builder, method)(**kwargs)
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt, (
        f"Round-trip mismatch for {method}({kwargs}): {original} != {rebuilt}"
    )


def test_format_converters_full_pipeline() -> None:
    """Реальная цепочка: jsonl_decode → markdown_to_html → toml_encode."""
    builder = (
        RouteBuilder.from_("rt.fc.full", source="test:rt.fc.full")
        .jsonl_decode()
        .markdown_to_html()
        .toml_encode()
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    methods = [next(iter(p)) for p in original["processors"]]
    assert methods == ["jsonl_decode", "markdown_to_html", "toml_encode"]
