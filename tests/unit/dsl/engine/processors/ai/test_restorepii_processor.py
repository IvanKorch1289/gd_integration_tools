"""Unit tests for RestorePIIProcessor."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.processors.ai.restorepii_processor import (
    RestorePIIProcessor,
)


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body

    def set_body(self, value: Any) -> None:
        self.body = value


class _Exchange:
    def __init__(
        self, body: Any = None, properties: dict[str, Any] | None = None
    ) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = properties or {}

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value


class _Context:
    pass


class TestRestorePIIProcessor:
    """Tests for :class:`RestorePIIProcessor`."""

    @pytest.mark.asyncio
    async def test_restores_placeholders(self) -> None:
        exchange = _Exchange(body="Email: [E1] Phone: [P1]")
        exchange.set_property("_pii_mapping", {"[E1]": "a@b.com", "[P1]": "+1"})
        exchange.set_property("_pii_original", "orig")
        proc = RestorePIIProcessor()
        await proc.process(exchange, _Context())
        assert "a@b.com" in exchange.in_message.body
        assert "+1" in exchange.in_message.body

    @pytest.mark.asyncio
    async def test_cleans_up_properties(self) -> None:
        exchange = _Exchange(body="x")
        exchange.set_property("_pii_mapping", {"[K]": "v"})
        exchange.set_property("_pii_original", "o")
        proc = RestorePIIProcessor()
        await proc.process(exchange, _Context())
        assert "_pii_mapping" not in exchange.properties
        assert "_pii_original" not in exchange.properties

    @pytest.mark.asyncio
    async def test_noop_when_no_mapping(self) -> None:
        exchange = _Exchange(body="unchanged")
        proc = RestorePIIProcessor()
        await proc.process(exchange, _Context())
        assert exchange.in_message.body == "unchanged"

    @pytest.mark.asyncio
    async def test_converts_non_string_body(self) -> None:
        exchange = _Exchange(body={"k": "[K]"})
        exchange.set_property("_pii_mapping", {"[K]": "value"})
        proc = RestorePIIProcessor()
        await proc.process(exchange, _Context())
        assert "value" in exchange.in_message.body
        assert isinstance(exchange.in_message.body, str)
