"""Unit-тесты HtmlTemplateProcessor — Wave [wave:s5/k3-w1-processor-pack-1]."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.html_template import HtmlTemplateProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.fixture(autouse=True)
def _enable_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_html_template", True)


@pytest.mark.asyncio
async def test_renders_template_into_body() -> None:
    proc = HtmlTemplateProcessor("Hello {{ name }}!", to="body.greeting")
    exchange = _ex({"name": "World"})

    await proc.process(exchange, AsyncMock())

    assert exchange.in_message.body["greeting"] == "Hello World!"


@pytest.mark.asyncio
async def test_renders_into_properties() -> None:
    proc = HtmlTemplateProcessor(
        "Total: {{ total }}", to="properties.summary", context_from="merged"
    )
    exchange = _ex({"total": 42})

    await proc.process(exchange, AsyncMock())

    assert exchange.properties.get("summary") == "Total: 42"


@pytest.mark.asyncio
async def test_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "proc_html_template", False)
    proc = HtmlTemplateProcessor("X={{ x }}", to="body.r")
    exchange = _ex({"x": 1})

    await proc.process(exchange, AsyncMock())

    assert exchange.properties.get("html_template_status") == "skipped"
    assert "r" not in exchange.in_message.body
