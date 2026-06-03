"""Unit tests for LLMParserProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.llmparser_processor import LLMParserProcessor


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body

    def set_body(self, value: Any) -> None:
        self.body = value


class _Exchange:
    def __init__(self, body: Any = None) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = {}

    def fail(self, msg: str) -> None:
        self.properties["_error"] = msg


class _Context:
    pass


class TestLLMParserProcessor:
    """Tests for :class:`LLMParserProcessor`."""

    @pytest.mark.asyncio
    async def test_extracts_and_parses_json(self) -> None:
        exchange = _Exchange(body='Some text {"status": "ok", "v": 1} more')
        proc = LLMParserProcessor(format="json")
        await proc.process(exchange, _Context())
        assert exchange.in_message.body == {"status": "ok", "v": 1}

    @pytest.mark.asyncio
    async def test_parses_plain_json(self) -> None:
        exchange = _Exchange(body='{"a": 1}')
        proc = LLMParserProcessor(format="json")
        await proc.process(exchange, _Context())
        assert exchange.in_message.body == {"a": 1}

    @pytest.mark.asyncio
    async def test_fails_on_invalid_json(self) -> None:
        exchange = _Exchange(body="not json")
        proc = LLMParserProcessor(format="json")
        await proc.process(exchange, _Context())
        assert exchange.properties["_error"] is not None
        assert "not valid JSON" in exchange.properties["_error"]

    @pytest.mark.asyncio
    async def test_noop_on_non_string_body(self) -> None:
        exchange = _Exchange(body={"already": "dict"})
        proc = LLMParserProcessor(format="json")
        await proc.process(exchange, _Context())
        assert exchange.in_message.body == {"already": "dict"}

    @pytest.mark.asyncio
    async def test_text_format_returns_stripped_text(self) -> None:
        exchange = _Exchange(body="  hello world  ")
        proc = LLMParserProcessor(format="text")
        await proc.process(exchange, _Context())
        assert exchange.in_message.body == "hello world"

    @pytest.mark.asyncio
    async def test_schema_validation_success(self) -> None:
        from pydantic import BaseModel

        class Item(BaseModel):
            name: str
            count: int

        exchange = _Exchange(body='{"name": "x", "count": 5}')
        proc = LLMParserProcessor(schema=Item, format="json")
        await proc.process(exchange, _Context())
        assert isinstance(exchange.in_message.body, Item)
        assert exchange.in_message.body.name == "x"

    @pytest.mark.asyncio
    async def test_schema_validation_failure(self) -> None:
        from pydantic import BaseModel

        class Item(BaseModel):
            name: str

        exchange = _Exchange(body='{"name": 123}')
        proc = LLMParserProcessor(schema=Item, format="json")
        await proc.process(exchange, _Context())
        assert exchange.properties["_error"] is not None
        assert "schema validation failed" in exchange.properties["_error"]

    @pytest.mark.asyncio
    async def test_non_basemodel_schema_ignored(self) -> None:
        exchange = _Exchange(body='{"a": 1}')
        proc = LLMParserProcessor(schema=dict, format="json")
        await proc.process(exchange, _Context())
        assert exchange.in_message.body == {"a": 1}
