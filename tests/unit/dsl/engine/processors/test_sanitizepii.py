"""Unit tests for SanitizePIIProcessor."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.ai.sanitizepii_processor import (
    SanitizePIIProcessor,
)


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@pytest.mark.asyncio
async def test_sanitize_str_body() -> None:
    with patch(
        "src.backend.infrastructure.security.ai_sanitizer.get_ai_sanitizer"
    ) as mock_get:
        sanitizer = AsyncMock()
        sanitizer.sanitize.return_value = MagicMock(
            sanitized_text="hello [REDACTED]", replacements={"name": "[REDACTED]"}
        )
        mock_get.return_value = sanitizer

        proc = SanitizePIIProcessor()
        exchange = _ex("My name is Alice")
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.in_message.body == "hello [REDACTED]"
        assert exchange.properties["_pii_original"] == "My name is Alice"
        assert exchange.properties["_pii_mapping"] == {"name": "[REDACTED]"}


@pytest.mark.asyncio
async def test_sanitize_non_str_body() -> None:
    with patch(
        "src.backend.infrastructure.security.ai_sanitizer.get_ai_sanitizer"
    ) as mock_get:
        sanitizer = AsyncMock()
        sanitizer.sanitize.return_value = MagicMock(
            sanitized_text="42", replacements={}
        )
        mock_get.return_value = sanitizer

        proc = SanitizePIIProcessor()
        exchange = _ex(42)
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.in_message.body == "42"


def test_sanitizepii_to_spec() -> None:
    proc = SanitizePIIProcessor()
    assert proc.to_spec() == {"sanitize_pii": {}}
