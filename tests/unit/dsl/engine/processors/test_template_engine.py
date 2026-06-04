"""Unit-тесты TemplateEngine processors."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.template_engine import RenderTemplateProcessor


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.mark.asyncio
async def test_render_template_from_body() -> None:
    proc = RenderTemplateProcessor(
        template_string="Hello {{ name }}!", result_property="out"
    )
    exchange = _ex({"name": "Alice"})
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["out"] == "Hello Alice!"


@pytest.mark.asyncio
async def test_render_template_from_body_field() -> None:
    proc = RenderTemplateProcessor(
        template_string="{{ greeting }}",
        context_from="body.context",
        result_property="out",
    )
    exchange = _ex({"context": {"greeting": "Hi"}})
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["out"] == "Hi"


@pytest.mark.asyncio
async def test_render_template_from_properties() -> None:
    proc = RenderTemplateProcessor(
        template_string="Value: {{ val }}",
        context_from="properties.ctx",
        result_property="out",
    )
    exchange = _ex({})
    exchange.properties["ctx"] = {"val": 42}
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["out"] == "Value: 42"


@pytest.mark.asyncio
async def test_render_template_non_dict_body() -> None:
    proc = RenderTemplateProcessor(
        template_string="Hello {{ name }}!", result_property="out"
    )
    exchange = _ex("text")
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["out"] == "Hello !"
