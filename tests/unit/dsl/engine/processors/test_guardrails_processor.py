"""Unit tests for GuardrailsProcessor.

Covers: max_length, blocklist, required_fields, no-block pass-through.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.processors.ai.guardrails_processor import (
    GuardrailsProcessor,
)


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body


class _Exchange:
    def __init__(self, body: Any = None) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = {}
        self._error: str | None = None

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def fail(self, msg: str) -> None:
        self._error = msg


class _Context:
    pass


class TestGuardrailsProcessor:
    """Tests for :class:`GuardrailsProcessor`."""

    @pytest.mark.asyncio
    async def test_passes_within_max_length(self) -> None:
        """Short text passes max_length check."""
        proc = GuardrailsProcessor(max_length=100)
        exchange = _Exchange(body="hello")
        await proc.process(exchange, _Context())
        assert exchange._error is None

    @pytest.mark.asyncio
    async def test_fails_on_max_length(self) -> None:
        """Text exceeding max_length fails exchange."""
        proc = GuardrailsProcessor(max_length=5)
        exchange = _Exchange(body="hello world")
        await proc.process(exchange, _Context())
        assert exchange._error is not None
        assert "too long" in exchange._error

    @pytest.mark.asyncio
    async def test_fails_on_blocked_pattern(self) -> None:
        """Blocked regex pattern fails exchange."""
        proc = GuardrailsProcessor(blocked_patterns=["badword"])
        exchange = _Exchange(body="this has badword here")
        await proc.process(exchange, _Context())
        assert exchange._error is not None
        assert "blocked pattern" in exchange._error

    @pytest.mark.asyncio
    async def test_passes_without_blocked_pattern(self) -> None:
        """Text without blocked pattern passes."""
        proc = GuardrailsProcessor(blocked_patterns=["badword"])
        exchange = _Exchange(body="clean text")
        await proc.process(exchange, _Context())
        assert exchange._error is None

    @pytest.mark.asyncio
    async def test_fails_on_missing_required_fields(self) -> None:
        """Dict body missing required fields fails exchange."""
        proc = GuardrailsProcessor(required_fields=["name", "age"])
        exchange = _Exchange(body={"name": "Alice"})
        await proc.process(exchange, _Context())
        assert exchange._error is not None
        assert "missing required fields" in exchange._error

    @pytest.mark.asyncio
    async def test_passes_with_all_required_fields(self) -> None:
        """Dict body with all required fields passes."""
        proc = GuardrailsProcessor(required_fields=["name"])
        exchange = _Exchange(body={"name": "Alice"})
        await proc.process(exchange, _Context())
        assert exchange._error is None

    @pytest.mark.asyncio
    async def test_non_dict_body_ignores_required(self) -> None:
        """String body ignores required_fields check."""
        proc = GuardrailsProcessor(required_fields=["name"])
        exchange = _Exchange(body="just text")
        await proc.process(exchange, _Context())
        assert exchange._error is None

    @pytest.mark.asyncio
    async def test_multiple_patterns_checks_all(self) -> None:
        """Multiple blocked patterns are checked in order."""
        proc = GuardrailsProcessor(blocked_patterns=["foo", "bar"])
        exchange = _Exchange(body="has bar")
        await proc.process(exchange, _Context())
        assert exchange._error is not None
        assert "bar" in exchange._error
